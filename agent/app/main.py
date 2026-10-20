"""단일 worker MVP 실행기. 외부 공개하지 않고 Spring이 내부 토큰으로 호출한다."""
import asyncio
from contextlib import asynccontextmanager
import hmac
import logging
import os
from uuid import UUID, uuid4
import httpx

from fastapi import FastAPI, Depends, Header, HTTPException
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command
from .config import Settings
from .schemas import RunRequest, ResumeRequest
from .clients import Gateway
from .mock import MockGateway
from .reasoning import Reasoner, MockReasoner
from .graph import build_graph, task_result, approval_payload

logger = logging.getLogger(__name__)


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
        app.state.jobs = {}
        app.state.guard = asyncio.Lock()
        async with _checkpoint(settings, checkpointer) as saver:
            app.state.graph = build_graph(app.state.gateway, app.state.reasoner, saver, settings)
            yield
            jobs = list(app.state.jobs.values())
            for job in jobs: job.cancel()
            await asyncio.gather(*jobs, return_exceptions=True)

    app = FastAPI(title='AX Navigator Agent', lifespan=lifespan)

    async def auth(x_internal_token: str | None = Header(default=None)):
        if not x_internal_token or not hmac.compare_digest(x_internal_token, settings.internal_token):
            raise HTTPException(403, '유효한 내부 토큰이 필요합니다.')

    def config(task_id):
        return {'configurable': {'thread_id': str(task_id)}, 'recursion_limit': 40,
                'run_name': 'ax-navigator', 'metadata': {'task_id': str(task_id), 'mode': settings.mode}}

    async def execute(task_id, payload):
        graph, client = app.state.graph, app.state.gateway
        cfg = config(task_id)
        cfg['run_id'] = uuid4()
        trace_url = None
        if os.getenv('LANGSMITH_TRACING', '').lower() == 'true' and os.getenv('LANGSMITH_API_KEY'):
            try:
                from langsmith import Client as TraceClient
                trace_url = TraceClient().get_run_url(run_id=cfg['run_id'], project_name=os.getenv('LANGSMITH_PROJECT', 'ax-navigator'))
            except Exception:
                logger.warning('LangSmith URL unavailable task_id=%s', task_id)
        try:
            await client.status(task_id, 'RUNNING', trace_url=trace_url)
            async with asyncio.timeout(settings.timeout):
                result = await graph.ainvoke(payload, config=cfg)
            if result.get('__interrupt__'):
                await client.status(task_id, 'WAITING_APPROVAL', result=task_result(result, settings.mode))
                # Existing FE renders natural language only from TOKEN events.
                # Send the verified complete answer once; do not expose raw LLM output.
                if result.get('answer'):
                    await client.event(task_id, 'TOKEN', 'roadmap', {'text': task_result(result, settings.mode)['answer']})
                await client.event(task_id, 'APPROVAL_REQUIRED', 'approval', approval_payload(result))
            elif result['status'] == 'REJECTED':
                await client.status(task_id, 'REJECTED')
            else:
                body = task_result(result, settings.mode)
                await client.status(task_id, 'DONE', result=body)
                await client.event(task_id, 'DONE', 'register', {'result': body})
        except asyncio.CancelledError:
            # 프로세스 종료 시 마지막 완료 노드 체크포인트는 보존한다.
            raise
        except Exception as exc:
            logger.error('Agent task failed task_id=%s error=%s', task_id, type(exc).__name__)
            failures=[e for e in client.public_trace.get(task_id) if e['type']=='NODE_ERROR']
            detail=failures[-1]['data'].get('message','') if failures else ''
            if isinstance(exc, httpx.HTTPStatusError):
                detail = f'Spring HTTP {exc.response.status_code}: {exc.request.method} {exc.request.url.path}'
            message = f'작업 실패: {type(exc).__name__}. {detail or "내부 로그와 연동 상태를 확인하세요."}'
            try:
                await graph.aupdate_state(cfg, {'status': 'FAILED', 'errors': [message]})
                await client.status(task_id, 'FAILED', error_message=message)
                await client.event(task_id, 'FAILED', data={'message': message})
            except Exception:
                logger.exception('Failure callback failed task_id=%s', task_id)
        finally:
            app.state.jobs.pop(task_id, None)

    @app.get('/health')
    async def health():
        return {'status': 'ok', 'mode': settings.mode, 'checkpoint': 'postgres' if settings.checkpoint_url else 'memory'}

    @app.post('/tasks/{task_id}/run', status_code=202, dependencies=[Depends(auth)])
    async def run(task_id: UUID, request: RunRequest):
        key = str(task_id)
        if request.companyId != settings.company_id: raise HTTPException(403, '지원하는 회사 범위를 벗어났습니다.')
        async with app.state.guard:
            snapshot = await app.state.graph.aget_state(config(key))
            if key in app.state.jobs or snapshot.values: raise HTTPException(409, '이미 존재하는 작업입니다.')
            if len(app.state.jobs) >= 8: raise HTTPException(503, '동시 실행 한도 초과')
            initial = {'task_id': key, 'company_id': request.companyId, 'user_id': request.userId,
                       'request': request.requestText, 'messages': [], 'retry_count': 0, 'errors': [], 'status': 'QUEUED'}
            # 첫 노드 실행 전에도 중복 작업/소유권을 조회할 수 있게 저장한다.
            await app.state.graph.aupdate_state(config(key), initial, as_node='__start__')
            app.state.jobs[key] = asyncio.create_task(execute(key, None))
        return {'taskId': key, 'status': 'QUEUED', 'mode': settings.mode}

    @app.post('/tasks/{task_id}/resume', status_code=202, dependencies=[Depends(auth)])
    async def resume(task_id: UUID, request: ResumeRequest):
        key = str(task_id)
        async with app.state.guard:
            snapshot = await app.state.graph.aget_state(config(key))
            if not snapshot.values: raise HTTPException(404, '작업이 없습니다.')
            if snapshot.values['user_id'] != request.userId: raise HTTPException(403, '작업 요청자만 재개할 수 있습니다.')
            interrupted = any(t.interrupts for t in snapshot.tasks)
            if key in app.state.jobs or not interrupted or snapshot.values.get('status') in {'FAILED', 'DONE', 'REJECTED'}:
                raise HTTPException(409, '승인 대기 중인 작업만 재개할 수 있습니다.')
            if len(app.state.jobs) >= 8: raise HTTPException(503, '동시 실행 한도 초과')
            app.state.jobs[key] = asyncio.create_task(execute(key, Command(resume=request.model_dump())))
        return {'taskId': key, 'status': 'RUNNING'}

    # 개발·내부 상태 확인용. 공개 사용자 조회 API는 Spring에서 요청자 인가 후 제공한다.
    @app.get('/tasks/{task_id}', dependencies=[Depends(auth)])
    async def state(task_id: UUID):
        snapshot = await app.state.graph.aget_state(config(task_id))
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
