"""Kill a real process between nodes, then recover using the actual worker and Postgres saver."""
import asyncio
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from uuid import uuid4

import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from agent.app.graph import build_nodes
from agent.app.graph.builder import build_graph
from agent.app.mock import MockGateway
from agent.app.reasoning import MockReasoner
from agent.app.runner import TaskRunner, pending_kind
from agent.app.worker import DurableWorker
from agent.tests.test_agent import settings
from agent.tests.test_durable_worker import command, make_worker

DSN = os.environ.get('AGENT_TEST_PG_DSN')
pytestmark = pytest.mark.skipif(not DSN, reason='AGENT_TEST_PG_DSN not set')


async def killed_process(dsn, run, marker):
    cfg = settings()
    gateway = MockGateway(cfg)
    async with AsyncPostgresSaver.from_conn_string(dsn) as saver:
        await saver.setup()
        nodes = build_nodes(gateway, MockReasoner(cfg), cfg)
        async def stopped(state):
            Path(marker).write_text('retrieve-started')
            await asyncio.Event().wait()
        nodes['retrieve'] = stopped
        runner = TaskRunner(build_graph(saver, nodes), gateway, cfg)
        worker = DurableWorker(cfg, runner, gateway)
        await worker.execute_graph(run)


async def test_sigkill_and_new_worker_resume_after_last_saved_node(tmp_path):
    run = command()
    marker = tmp_path / 'node-started'
    code = 'import asyncio,json,sys; from agent.tests.test_worker_postgres_recovery import killed_process; asyncio.run(killed_process(sys.argv[1],json.loads(sys.argv[2]),sys.argv[3]))'
    proc = subprocess.Popen([sys.executable, '-c', code, DSN, json.dumps(run), str(marker)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(200):
            if marker.exists():
                break
            if proc.poll() is not None:
                pytest.fail(f'child exited before checkpoint: {proc.returncode}')
            await asyncio.sleep(.05)
        assert marker.exists(), 'child never reached second node'
        proc.kill()
        await asyncio.to_thread(proc.wait, 5)
        assert proc.returncode == -signal.SIGKILL
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()

    cfg = settings()
    gateway = MockGateway(cfg)
    async with AsyncPostgresSaver.from_conn_string(DSN) as saver:
        nodes = build_nodes(gateway, MockReasoner(cfg), cfg)
        async def already_completed(_):
            raise AssertionError('completed collect node must not run again')
        nodes['collect'] = already_completed
        runner = TaskRunner(build_graph(saver, nodes), gateway, cfg)
        worker = DurableWorker(cfg, runner, gateway)
        try:
            await worker.execute_graph(run)
            snapshot = await runner.graph.aget_state(runner._cfg(run['taskId']))
            assert pending_kind(snapshot) == 'APPROVAL'
            assert not any(name.startswith('create_') for name, _ in gateway.calls)
            approve = command('RESUME', run['taskId'], decision='APPROVE')
            await worker.execute_graph(approve)
            await worker.execute_graph(approve)  # completion response lost; command delivered again
            assert sum(name == 'create_ax_roadmap' for name, _ in gateway.calls) == 1
            assert sum(name == 'create_ax_project' for name, _ in gateway.calls) == 3
        finally:
            await worker.close()


async def test_checkpoint_lock_serializes_workers_and_is_released_on_cancellation():
    cfg = settings()
    cfg.checkpoint_url = DSN
    worker1, worker2 = make_worker(), make_worker()
    worker1.settings = cfg
    worker2.settings = cfg
    aggregate = 'task:' + str(uuid4())
    entered1, entered2 = asyncio.Event(), asyncio.Event()
    async def hold(worker, entered):
        async with worker.checkpoint_lock(aggregate, [None]):
            entered.set()
            await asyncio.Event().wait()
    first = asyncio.create_task(hold(worker1, entered1))
    second = None
    try:
        await asyncio.wait_for(entered1.wait(), 5)
        second = asyncio.create_task(hold(worker2, entered2))
        await asyncio.sleep(.1)
        assert not entered2.is_set()
        first.cancel()
        await asyncio.gather(first, return_exceptions=True)
        await asyncio.wait_for(entered2.wait(), 5)
    finally:
        first.cancel()
        if second:
            second.cancel()
        await asyncio.gather(*[t for t in (first, second) if t], return_exceptions=True)
        await worker1.close()
        await worker2.close()
