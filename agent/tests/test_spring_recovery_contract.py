"""Opt-in local BE + Business MCP + Worker contract test; no production/LLM access.

Requires a disposable, seeded BE DB and the matching BE PR running on loopback.
RAG retrieval/indexing and LLM outputs are fixtures; business writes are real HTTP.
"""
import os
from urllib.parse import urlparse

import httpx
import pytest
from psycopg import AsyncConnection
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from agent.app.clients.mcp import Gateway, RAG_TOOLS
from agent.app.graph import build_graph
from agent.app.mock import MockGateway
from agent.app.reasoning import MockReasoner
from agent.app.recovery_context import RetryableWorkError
from agent.app.runner import TaskRunner
from agent.app.worker import DurableWorker
from agent.tests.test_agent import settings
from agent.tests.test_ingest import text_pdf

BASE = os.environ.get('RECOVERY_TEST_BE_URL')
pytestmark = pytest.mark.skipif(not BASE, reason='local BE contract environment not configured')


async def test_real_spring_callbacks_mcp_fencing_retry_and_pdf_cleanup():
    assert urlparse(BASE).hostname in {'127.0.0.1', 'localhost'}, 'disposable loopback BE only'
    dsn = os.environ['RECOVERY_TEST_BE_DSN']
    assert urlparse(dsn).hostname in {'127.0.0.1', 'localhost'}, 'disposable loopback DB only'
    cfg = settings()
    cfg.internal_token = os.environ['RECOVERY_TEST_INTERNAL_TOKEN']
    cfg.spring_url = BASE + '/internal'
    cfg.business_url = os.environ['RECOVERY_TEST_BUSINESS_MCP_URL']
    cfg.checkpoint_url = os.environ['AGENT_TEST_PG_DSN']

    class HybridGateway(Gateway):
        def __init__(self):
            super().__init__(cfg)
            self.fixture = MockGateway(cfg)
            self.lose_response = 'save_assessment'
        async def tool(self, task_id, node, name, args):
            if name in RAG_TOOLS:
                return await self.fixture.tool(task_id, node, name, args)
            value = await super().tool(task_id, node, name, args)
            if name == self.lose_response:
                self.lose_response = None
                raise RetryableWorkError('simulated response loss after committed business write')
            return value
        async def index_document(self, *args):
            return await self.fixture.index_document(*args)

    gateway = HybridGateway()
    async with httpx.AsyncClient(base_url=BASE, timeout=30) as user, await AsyncConnection.connect(dsn, autocommit=True) as db:
        login = await user.post('/api/auth/login', json={'email': 'analyst2@gaon.example', 'password': 'ChangeMe123!'})
        login.raise_for_status()
        user.headers['Authorization'] = 'Bearer ' + login.json()['accessToken']
        async with AsyncPostgresSaver.from_conn_string(cfg.checkpoint_url) as saver:
            await saver.setup()
            runner = TaskRunner(build_graph(gateway, MockReasoner(cfg), saver, cfg), gateway, cfg)
            worker = DurableWorker(cfg, runner, gateway)
            async def next_command():
                response = await worker.request('POST', 'agent-commands/claim', json={})
                assert response.status_code == 200
                return response.json()
            async def retry_now():
                await db.execute("UPDATE ai_commands SET available_at=clock_timestamp()-INTERVAL '1 second' WHERE state='READY'")
            async def count(sql, *params):
                return (await (await db.execute(sql, params)).fetchone())[0]
            try:
                response = await user.post('/api/ai/tasks', json={'requestText': '3억 원 내에서 AX 과제 추천'})
                response.raise_for_status()
                key = response.json()['taskId']
                # Response lost after the assessment write: retry must return its existing ID.
                first = await next_command()
                assert first['taskId'] == key
                await worker.leased(first)
                assert await count('SELECT count(*) FROM ax_assessments WHERE task_id=%s', key) == 1
                await retry_now()
                await worker.leased(await next_command())
                detail = (await user.get('/api/ai/tasks/' + key)).json()
                assert detail['status'] == 'WAITING_APPROVAL', detail
                assert await count('SELECT count(*) FROM ax_assessments WHERE task_id=%s', key) == 1

                response = await user.post(f'/api/ai/tasks/{key}/approval', json={'decision': 'APPROVE'})
                response.raise_for_status()
                # Response lost after the first project write: replay the whole register node safely.
                gateway.lose_response = 'create_ax_project'
                await worker.leased(await next_command())
                await retry_now()
                await worker.leased(await next_command())
                detail = (await user.get('/api/ai/tasks/' + key)).json()
                assert detail['status'] == 'DONE', detail
                assert await count('SELECT count(*) FROM ax_roadmaps WHERE task_id=%s', key) == 1
                assert await count('''SELECT count(*) FROM ax_projects p JOIN roadmap_items i ON i.item_id=p.item_id
                    JOIN ax_roadmaps r ON r.roadmap_id=i.roadmap_id WHERE r.task_id=%s''', key) == 3

                response = await user.post('/api/documents', files={'file': ('test.pdf', text_pdf(key), 'application/pdf')})
                response.raise_for_status()
                document_id = response.json()['documentId']
                await worker.leased(await next_command())
                assert await count('SELECT status FROM documents WHERE document_id=%s', document_id) == 'INDEXED'
                assert await count('SELECT count(*) FROM ai_command_inputs') == 0
            finally:
                await worker.close()
