import asyncio
from contextlib import asynccontextmanager
import json
from uuid import uuid4

import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver

from agent.app.clients.spring import SpringClient
from agent.app.graph import build_graph
from agent.app.mock import MockGateway
from agent.app.reasoning import MockReasoner
from agent.app.recovery_context import lease_headers, command_headers, RetryableWorkError, PermanentWorkError, tool_failure
from agent.app.runner import TaskRunner, pending_kind
from agent.app.worker import DurableWorker
from agent.tests.test_agent import settings
from agent.tests.test_ingest import text_pdf


def command(kind='RUN', key=None, **payload):
    key = key or str(uuid4())
    body = {'companyId': 1, 'userId': 602, 'requestText': 'AX 과제 추천'} if kind == 'RUN' else {'userId': 602}
    body.update(payload)
    return {'commandId': str(uuid4()), 'aggregateKey': f'task:{key}', 'taskId': key, 'documentId': None,
            'kind': kind, 'payload': body, 'leaseToken': str(uuid4()), 'attempt': 1,
            'leaseSeconds': 90, 'schemaVersion': 1, 'superseded': False}


def make_worker(*, transport=None, saver=None, gateway=None):
    cfg = settings()
    gateway = gateway or MockGateway(cfg)
    runner = TaskRunner(build_graph(gateway, MockReasoner(cfg), saver or InMemorySaver(), cfg), gateway, cfg)
    client = httpx.AsyncClient(base_url='http://spring/internal/', transport=transport or httpx.MockTransport(lambda r: httpx.Response(204)))
    return DurableWorker(cfg, runner, gateway, client=client)


@asynccontextmanager
async def no_lock(*args):
    yield


async def test_replayed_run_preserves_approval_wait_without_repeating_analysis():
    worker = make_worker()
    run = command()
    try:
        await worker.execute_graph(run)
        count = len(worker.gateway.calls)
        notifications = len(worker.gateway.events)
        await worker.execute_graph(run)
        state = await worker.runner.graph.aget_state(worker.runner._cfg(run['taskId']))
        assert pending_kind(state) == 'APPROVAL'
        assert len(worker.gateway.calls) == count
        assert not any(name.startswith('create_') for name, _ in worker.gateway.calls)
        # Replayed notification must not change WAITING -> RUNNING first.
        assert not any(event['body'].get('status') == 'RUNNING' for event in worker.gateway.events[notifications:])
    finally:
        await worker.close()


async def test_lost_completion_ack_replays_result_without_duplicate_roadmap_or_projects():
    worker = make_worker()
    run = command()
    try:
        await worker.execute_graph(run)
        approve = command('RESUME', run['taskId'], decision='APPROVE')
        await worker.execute_graph(approve)
        await worker.execute_graph(approve)
        assert sum(name == 'create_ax_roadmap' for name, _ in worker.gateway.calls) == 1
        assert sum(name == 'create_ax_project' for name, _ in worker.gateway.calls) == 3
        assert worker.gateway.events[-1]['body']['type'] == 'DONE'
    finally:
        await worker.close()


async def test_run_replay_never_crosses_company_confirmation_boundary():
    worker = make_worker()
    try:
        await worker.gateway.index_document(2, 9001, '회사.pdf', [{'page': 1, 'text': 'HR handles policy questions'}])
        run = command(companyId=2, companyDataConfirmed=False, documentIds=[9001])
        await worker.execute_graph(run)
        assert pending_kind(await worker.runner.graph.aget_state(worker.runner._cfg(run['taskId']))) == 'CONFIRMATION'
        # Publishing the same run again does not cross the human confirmation boundary.
        await worker.execute_graph(run)
        assert pending_kind(await worker.runner.graph.aget_state(worker.runner._cfg(run['taskId']))) == 'CONFIRMATION'
    finally:
        await worker.close()


async def test_superseded_run_is_acknowledged_without_overwriting_new_user_decision():
    paths = []
    worker = make_worker(transport=httpx.MockTransport(lambda r: (paths.append(r.url.path) or httpx.Response(204))))
    worker.checkpoint_lock = no_lock
    run = {**command(), 'superseded': True}
    try:
        await worker.process(run, [None])
        assert paths == [f"/internal/agent-commands/{run['commandId']}/heartbeat", f"/internal/agent-commands/{run['commandId']}/complete"]
        assert not worker.gateway.events
    finally:
        await worker.close()


@pytest.mark.parametrize('error,retryable', [(RetryableWorkError('offline'), True), (PermanentWorkError('invalid'), False)])
async def test_retry_classification_and_safe_logs(error, retryable, caplog):
    requests = []
    def handler(request):
        requests.append((request.url.path, json.loads(request.content)))
        return httpx.Response(204)
    worker = make_worker(transport=httpx.MockTransport(handler))
    worker.checkpoint_lock = no_lock
    async def broken(_):
        raise error
    worker.execute_graph = broken
    run = command(requestText='private-input-never-log')
    try:
        await worker.process(run, [None])
        assert requests[-1][1]['retryable'] is retryable
        assert 'private-input-never-log' not in caplog.text
        assert run['leaseToken'] not in caplog.text
    finally:
        await worker.close()


async def test_losing_lease_cancels_running_execution():
    worker = make_worker()
    started, cancelled = asyncio.Event(), asyncio.Event()
    async def process(*args):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
    async def lost(*args):
        await started.wait()
        raise ConnectionError('BE unavailable')
    worker.process, worker.heartbeat = process, lost
    try:
        await worker.leased(command())
        assert cancelled.is_set()
        assert command_headers() == {}
    finally:
        await worker.close()


async def test_shutdown_drains_then_cancels_remaining_jobs():
    worker = make_worker()
    worker.settings.worker_drain_seconds = .01
    started, cancelled = asyncio.Event(), asyncio.Event()
    async def running():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
    worker.jobs.add(asyncio.create_task(running()))
    await started.wait()
    await worker.close()
    assert cancelled.is_set()


async def test_poller_obeys_concurrency_and_shutdown_waits_for_accepted_work():
    claims = []
    run = command()
    def handler(request):
        claims.append(request.url.path)
        return httpx.Response(200, json=run)
    worker = make_worker(transport=httpx.MockTransport(handler))
    worker.settings.worker_poll_seconds = .01
    worker.settings.worker_drain_seconds = 1
    started, release, completed = asyncio.Event(), asyncio.Event(), asyncio.Event()
    async def process(*args):
        started.set()
        await release.wait()
        completed.set()
    worker.process = process
    await worker.start()
    await asyncio.wait_for(started.wait(), 1)
    await asyncio.sleep(.03)
    assert len(claims) == 1
    closing = asyncio.create_task(worker.close())
    await asyncio.sleep(.01)
    assert not closing.done()
    release.set()
    await closing
    assert completed.is_set()


async def test_pdf_replay_uses_durable_input_and_callback():
    pdf = text_pdf('HR policy questions')
    worker = make_worker(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=pdf)))
    ingest = {**command('INGEST'), 'taskId': None, 'documentId': 9001,
              'payload': {'companyId': 2, 'fileName': '회사.pdf'}}
    try:
        await worker.ingest(ingest)
        await worker.ingest(ingest)
        assert len(worker.gateway.uploads[2]) == 1
        assert worker.gateway.events[-1]['body']['status'] == 'INDEXED'
    finally:
        await worker.close()


async def test_per_command_headers_are_isolated_and_reach_spring():
    requests = []
    cfg = settings()
    async def send(command_id):
        token = lease_headers.set({'X-Command-Id': command_id, 'X-Command-Lease': 'lease-'+command_id})
        try:
            async with httpx.AsyncClient(base_url='http://spring/internal/', transport=httpx.MockTransport(
                    lambda r: (requests.append(r) or httpx.Response(204)))) as client:
                spring = SpringClient(cfg, client=client)
                await spring.patch_task(command_id, status='RUNNING')
        finally:
            lease_headers.reset(token)
    await asyncio.gather(send('a'), send('b'))
    assert {(r.headers['x-command-id'], r.headers['x-command-lease']) for r in requests} == {('a', 'lease-a'), ('b', 'lease-b')}
    assert command_headers() == {}


def test_input_errors_are_permanent_but_transport_errors_are_retryable():
    assert isinstance(tool_failure(RuntimeError('Spring HTTP 400'), 'MCP_CALL_FAILED', 'invalid'), PermanentWorkError)
    assert isinstance(tool_failure(RuntimeError('Spring HTTP 503'), 'MCP_CALL_FAILED', 'offline'), RetryableWorkError)
    assert isinstance(tool_failure(RuntimeError(), 'RAG_UPLOAD_EMPTY', 'empty'), PermanentWorkError)
