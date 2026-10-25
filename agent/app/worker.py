"""Pull durable commands from Spring; checkpoints remain in the existing agent DB.

The BE owns leases and fences business writes. An agent-DB advisory lock additionally
serializes checkpoint writers during handover. Neither layer promises exactly-once LLM calls.
"""
import asyncio
import hashlib
import logging
from contextlib import asynccontextmanager

import httpx
from psycopg import AsyncConnection
from pydantic import ValidationError
from langgraph.types import Command

from .ingest import pdf_pages, IngestError
from .recovery_context import lease_headers, PermanentWorkError
from .runner import pending_kind
from .schemas import RunRequest, ResumeRequest, ConfirmRequest

logger = logging.getLogger(__name__)


class DurableWorker:
    def __init__(self, settings, runner, gateway, *, client=None):
        self.settings, self.runner, self.gateway = settings, runner, gateway
        self.client = client or httpx.AsyncClient(
            base_url=settings.spring_url.rstrip('/') + '/', timeout=15,
            headers={'X-Internal-Token': settings.internal_token})
        self.stopping = asyncio.Event()
        self.jobs = set()
        self.poller = None

    async def start(self):
        self.poller = asyncio.create_task(self.poll(), name='durable-agent-poller')

    async def request(self, method, path, **kwargs):
        response = await self.client.request(method, path, **kwargs)
        response.raise_for_status()
        return response

    async def poll(self):
        while not self.stopping.is_set():
            try:
                if len(self.jobs) < self.settings.worker_concurrency:
                    response = await self.request('POST', 'agent-commands/claim', json={})
                    if response.status_code == 200:
                        job = asyncio.create_task(self.leased(response.json()))
                        self.jobs.add(job)
                        job.add_done_callback(self.jobs.discard)
                        continue
            except Exception as exc:
                logger.warning('COMMAND_POLL_FAILED error=%s', type(exc).__name__)
            try:
                await asyncio.wait_for(self.stopping.wait(), self.settings.worker_poll_seconds)
            except TimeoutError:
                pass

    async def leased(self, command):
        """Loss of either ownership or the checkpoint-lock connection stops execution."""
        context = lease_headers.set({'X-Command-Id': command['commandId'], 'X-Command-Lease': command['leaseToken']})
        connection = [None]
        execution = asyncio.create_task(self.process(command, connection))
        heartbeat = asyncio.create_task(self.heartbeat(command, connection))
        try:
            done, _ = await asyncio.wait({execution, heartbeat}, return_when=asyncio.FIRST_COMPLETED)
            if execution in done:
                await execution
            else:
                await heartbeat
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # No payload, token, DSN or raw exception messages in logs.
            logger.warning('COMMAND_STOPPED command_id=%s attempt=%s error=%s',
                           command.get('commandId'), command.get('attempt'), type(exc).__name__)
        finally:
            execution.cancel()
            heartbeat.cancel()
            await asyncio.gather(execution, heartbeat, return_exceptions=True)
            lease_headers.reset(context)

    async def heartbeat(self, command, connection):
        interval = max(1, command['leaseSeconds'] / 3)
        while True:
            await asyncio.sleep(interval)
            await self.request('POST', f"agent-commands/{command['commandId']}/heartbeat",
                               json={'leaseToken': command['leaseToken']})
            if connection[0] is not None:
                await connection[0].execute('SELECT 1')

    @asynccontextmanager
    async def checkpoint_lock(self, aggregate, connection):
        key = int.from_bytes(hashlib.sha256(aggregate.encode()).digest()[:8], 'big', signed=True)
        async with await AsyncConnection.connect(self.settings.checkpoint_url, autocommit=True, connect_timeout=5) as conn:
            connection[0] = conn
            try:
                while True:
                    cursor = await conn.execute('SELECT pg_try_advisory_lock(%s)', (key,))
                    if (await cursor.fetchone())[0]:
                        break
                    await asyncio.sleep(.5)
                yield
            finally:
                connection[0] = None
                # Closing the dedicated session releases the lock, including on cancellation.

    async def process(self, command, connection):
        try:
            if command.get('schemaVersion') != 1:
                raise PermanentWorkError('Unsupported command schema')
            async with self.checkpoint_lock(command['aggregateKey'], connection):
                # Re-check ownership after waiting for the prior checkpoint writer.
                await self.request('POST', f"agent-commands/{command['commandId']}/heartbeat",
                                   json={'leaseToken': command['leaseToken']})
                if not command.get('superseded'):
                    if command['kind'] == 'INGEST':
                        await self.ingest(command)
                    else:
                        await self.execute_graph(command)
                await self.request('POST', f"agent-commands/{command['commandId']}/complete",
                                   json={'leaseToken': command['leaseToken']})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            permanent = isinstance(exc, (PermanentWorkError, ValidationError, IngestError, ValueError))
            if isinstance(exc, httpx.HTTPStatusError):
                permanent = exc.response.status_code in {400, 401, 403, 404, 422}
            logger.warning('COMMAND_FAILED command_id=%s attempt=%s retryable=%s error=%s',
                           command['commandId'], command['attempt'], not permanent, type(exc).__name__)
            # If the lease was lost this request is rejected too. Expiry handles reassignment.
            await self.request('POST', f"agent-commands/{command['commandId']}/fail",
                               json={'leaseToken': command['leaseToken'], 'retryable': not permanent})

    async def execute_graph(self, command):
        key = command['taskId']
        cfg = self.runner._cfg(key)
        snapshot = await self.runner.graph.aget_state(cfg)
        operation, data = command['kind'], command['payload']
        expected = None
        resume_value = None
        if operation == 'RUN':
            request = RunRequest.model_validate(data)
            if not snapshot.values:
                initial = {'task_id': key, 'company_id': request.companyId, 'user_id': request.userId,
                           'request': request.requestText, 'messages': [], 'retry_count': 0, 'errors': [], 'status': 'QUEUED',
                           'company_data_confirmed': request.companyDataConfirmed, 'document_ids': request.documentIds}
                await self.runner.graph.aupdate_state(cfg, initial, as_node='__start__')
                snapshot = await self.runner.graph.aget_state(cfg)
        elif operation == 'CONFIRM':
            request = ConfirmRequest.model_validate(data)
            expected, resume_value = 'CONFIRMATION', {'kind': 'CONFIRMATION', 'userId': request.userId}
        elif operation == 'RESUME':
            request = ResumeRequest.model_validate(data)
            expected, resume_value = 'APPROVAL', request.model_dump()
        else:
            raise PermanentWorkError('Unknown operation')
        if not snapshot.values or snapshot.values['user_id'] != request.userId:
            raise PermanentWorkError('Missing checkpoint or task ownership mismatch')

        pending = pending_kind(snapshot)
        if pending and expected == pending:
            await self.runner.execute(key, Command(resume=resume_value), durable=True)
        elif pending or not snapshot.next:
            result = dict(snapshot.values)
            interrupts = [item for task in snapshot.tasks for item in task.interrupts]
            if interrupts:
                result['__interrupt__'] = interrupts
            await self.runner.execute(key, None, durable=True, publish_only=result)
        else:
            # A previously accepted approval may already be in the checkpoint. Never
            # send it again: continue its remaining nodes with the same thread_id.
            await self.runner.execute(key, None, durable=True)

    async def ingest(self, command):
        response = await self.request('GET', f"agent-commands/{command['commandId']}/input",
                                      headers={'X-Command-Lease': command['leaseToken']})
        pages = await asyncio.to_thread(pdf_pages, response.content)
        data = command['payload']
        await self.gateway.index_document(data['companyId'], command['documentId'], data['fileName'], pages)
        await self.gateway.document_result(command['documentId'], {'status': 'INDEXED', 'pageCount': len(pages), 'pages': pages})

    async def close(self):
        self.stopping.set()
        if self.poller:
            self.poller.cancel()
            await asyncio.gather(self.poller, return_exceptions=True)
        jobs = list(self.jobs)
        if jobs:
            _, pending = await asyncio.wait(jobs, timeout=self.settings.worker_drain_seconds)
            for job in pending:
                job.cancel()
            await asyncio.gather(*jobs, return_exceptions=True)
        await self.client.aclose()
