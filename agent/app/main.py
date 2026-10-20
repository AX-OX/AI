"""단일 worker MVP 실행기. 외부 공개하지 않고 Spring이 내부 토큰으로 호출한다."""
from contextlib import asynccontextmanager
import hmac
import os
from uuid import UUID

from fastapi import FastAPI, Depends, Header, HTTPException
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from .config import Settings
from .schemas import RunRequest, ResumeRequest
from .clients import Gateway
from .mock import MockGateway
from .reasoning import Reasoner, MockReasoner
from .graph import build_graph, task_result
from .runner import TaskRunner



def create_app(settings=None, *, gateway=None, reasoner=None, checkpointer=None):
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app):
        if not settings.internal_token: raise RuntimeError('INTERNAL_TOKEN 필수')
        if settings.mode not in {'live', 'mock', 'llm-demo'}: raise RuntimeError('AGENT_MODE는 live, mock, llm-demo 중 하나여야 합니다.')
        if settings.mode != 'mock' and (not settings.model or not os.getenv('OPENAI_API_KEY')):
            raise RuntimeError('live/llm-demo 모드는 LLM_MODEL과 OPENAI_API_KEY가 필요합니다.')
        app.state.gateway = gateway or (MockGateway(settings) if settings.mode in {'mock','llm-demo'} else Gateway(settings))
        app.state.reasoner = reasoner or (MockReasoner(settings) if settings.mode == 'mock' else Reasoner(settings, observer=app.state.gateway.observe))
        async with _checkpoint(settings, checkpointer) as saver:
            app.state.graph = build_graph(app.state.gateway, app.state.reasoner, saver, settings)
            app.state.runner = TaskRunner(app.state.graph, app.state.gateway, settings)
            app.state.jobs = app.state.runner.jobs
            app.state.guard = app.state.runner.guard
            yield
            await app.state.runner.close()

    app = FastAPI(title='AX Navigator Agent', lifespan=lifespan)

    async def auth(x_internal_token: str | None = Header(default=None)):
        if not x_internal_token or not hmac.compare_digest(x_internal_token, settings.internal_token):
            raise HTTPException(403, '유효한 내부 토큰이 필요합니다.')

    @app.get('/health')
    async def health():
        return {'status': 'ok', 'mode': settings.mode, 'checkpoint': 'postgres' if settings.checkpoint_url else 'memory'}

    @app.post('/tasks/{task_id}/run', status_code=202, dependencies=[Depends(auth)])
    async def run(task_id: UUID, request: RunRequest):
        return await app.state.runner.start(task_id, request)

    @app.post('/tasks/{task_id}/resume', status_code=202, dependencies=[Depends(auth)])
    async def resume(task_id: UUID, request: ResumeRequest):
        return await app.state.runner.resume(task_id, request)

    # 개발·내부 상태 확인용. 공개 사용자 조회 API는 Spring에서 요청자 인가 후 제공한다.
    @app.get('/tasks/{task_id}', dependencies=[Depends(auth)])
    async def state(task_id: UUID):
        snapshot = await app.state.graph.aget_state(TaskRunner._cfg(task_id))
        if not snapshot.values: raise HTTPException(404, '작업이 없습니다.')
        interrupted = any(t.interrupts for t in snapshot.tasks)
        status = snapshot.values.get('status')
        if interrupted and status not in {'FAILED', 'DONE', 'REJECTED'}: status = 'WAITING_APPROVAL'
        return {'taskId': str(task_id), 'status': status, 'mode': settings.mode, 'next': snapshot.next,
                'roadmap': task_result(snapshot.values, settings.mode)['roadmap'],
                'result': task_result(snapshot.values, settings.mode), 'errors': snapshot.values.get('errors', []),
                'trace': app.state.gateway.public_trace.get(task_id)}

    return app


@asynccontextmanager
async def _checkpoint(settings, injected):
    if injected is not None:
        yield injected
    elif settings.checkpoint_url:
        async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_url) as saver:
            await saver.setup()
            yield saver
    elif settings.mode in {'mock','llm-demo'}:
        yield InMemorySaver()
    else:
        raise RuntimeError('live 모드에서는 agent DB의 AGENT_DATABASE_URL이 필요합니다.')

app = create_app()
