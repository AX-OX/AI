"""Spring 내부 API와 선택적 영속 pull Worker를 제공한다."""
from contextlib import asynccontextmanager
import hmac
import os
from uuid import UUID

from fastapi import FastAPI, Depends, Header, HTTPException, UploadFile, File, Form, Response
from prometheus_client import CONTENT_TYPE_LATEST
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from .config import Settings
from .schemas import RunRequest, ResumeRequest, ConfirmRequest
from .clients import Gateway
from .mock import MockGateway
from .reasoning import Reasoner, MockReasoner
from .graph import build_graph, task_result
from .runner import TaskRunner, pending_kind
from .ingest import Ingestor, MAX_BYTES
from .worker import DurableWorker
from .conversation import Conversation, ChatRequest, ChatReply
from .telemetry import AgentMetrics, MetricsMiddleware



def create_app(settings=None, *, gateway=None, reasoner=None, checkpointer=None):
    settings = settings or Settings.from_env()
    metrics = AgentMetrics(settings)

    @asynccontextmanager
    async def lifespan(app):
        if not settings.internal_token: raise RuntimeError('INTERNAL_TOKEN 필수')
        if settings.mode not in {'live', 'mock', 'llm-demo'}: raise RuntimeError('AGENT_MODE는 live, mock, llm-demo 중 하나여야 합니다.')
        if settings.mode != 'mock' and (not settings.model or not os.getenv('OPENAI_API_KEY')):
            raise RuntimeError('live/llm-demo 모드는 LLM_MODEL과 OPENAI_API_KEY가 필요합니다.')
        app.state.gateway = gateway or (MockGateway(settings) if settings.mode in {'mock','llm-demo'} else Gateway(settings))
        app.state.gateway.metrics = metrics
        app.state.reasoner = reasoner or (MockReasoner(settings) if settings.mode == 'mock' else Reasoner(settings, observer=app.state.gateway.observe))
        app.state.reasoner.metrics = metrics
        app.state.conversation = Conversation(app.state.reasoner, mock=settings.mode == 'mock')
        async with _checkpoint(settings, checkpointer) as saver:
            app.state.graph = build_graph(app.state.gateway, app.state.reasoner, saver, settings)
            app.state.runner = TaskRunner(app.state.graph, app.state.gateway, settings)
            app.state.jobs = app.state.runner.jobs
            app.state.guard = app.state.runner.guard
            app.state.ingestor = Ingestor(app.state.gateway)
            worker = DurableWorker(settings, app.state.runner, app.state.gateway) if settings.worker_enabled else None
            if worker:
                await worker.start()
            try:
                metrics.ready.set(1)
                yield
            finally:
                metrics.ready.set(0)
                if worker:
                    await worker.close()
                await app.state.ingestor.close()
                await app.state.runner.close()

    app = FastAPI(title='AX Navigator Agent', lifespan=lifespan)
    app.state.metrics = metrics
    app.add_middleware(MetricsMiddleware, metrics=metrics)

    @app.get('/metrics', include_in_schema=False)
    async def prometheus_metrics(authorization: str | None = Header(default=None)):
        token = os.getenv('METRICS_TOKEN') or settings.internal_token
        if not token or not authorization or not hmac.compare_digest(authorization, f'Bearer {token}'):
            raise HTTPException(403, 'Metrics authentication required')
        return Response(metrics.render(), media_type=CONTENT_TYPE_LATEST)

    async def auth(x_internal_token: str | None = Header(default=None)):
        if not x_internal_token or not hmac.compare_digest(x_internal_token, settings.internal_token):
            raise HTTPException(403, '유효한 내부 토큰이 필요합니다.')

    @app.get('/health')
    async def health():
        return {'status': 'ok', 'mode': settings.mode, 'checkpoint': 'postgres' if settings.checkpoint_url else 'memory'}

    @app.get('/diagnostics/rag', dependencies=[Depends(auth)])
    async def rag_diagnostics():
        # /health is liveness only. This endpoint checks actual RAG DB/index access.
        if settings.mode != 'live':
            return {'status': 'not_checked', 'mode': settings.mode}
        return await app.state.gateway.check_rag()

    @app.post('/chat/messages', response_model=ChatReply, dependencies=[Depends(auth)])
    async def chat(request: ChatRequest):
        try:
            return await app.state.conversation.reply(request)
        except (TimeoutError, RuntimeError, ValueError):
            # Fail closed: a classification/model failure cannot create a task.
            raise HTTPException(503, '답변을 준비하지 못했어요. 잠시 후 다시 시도해 주세요. 새 분석은 시작하지 않았어요.') from None

    def legacy_only():
        if settings.worker_enabled:
            raise HTTPException(409, '작업 복구 모드에서는 Spring의 영속 실행 명령을 사용하세요.')

    @app.post('/tasks/{task_id}/run', status_code=202, dependencies=[Depends(auth)])
    async def run(task_id: UUID, request: RunRequest):
        legacy_only()
        return await app.state.runner.start(task_id, request)

    @app.post('/tasks/{task_id}/resume', status_code=202, dependencies=[Depends(auth)])
    async def resume(task_id: UUID, request: ResumeRequest):
        legacy_only()
        return await app.state.runner.resume(task_id, request)

    @app.post('/tasks/{task_id}/confirm', status_code=202, dependencies=[Depends(auth)])
    async def confirm(task_id: UUID, request: ConfirmRequest):
        legacy_only()
        return await app.state.runner.confirm(task_id, request)

    @app.post('/documents/{document_id}/ingest', status_code=202, dependencies=[Depends(auth)])
    async def ingest(document_id: int, companyId: int = Form(gt=0), fileName: str = Form(min_length=1, max_length=200),
                     contentType: str = Form(), file: UploadFile = File()):
        legacy_only()
        # Spring이 형식·크기를 먼저 검사한다. 여기서는 경계만 다시 확인하고 결과는 콜백으로 돌려준다.
        if contentType != 'application/pdf': raise HTTPException(400, 'PDF만 색인합니다.')
        data = await file.read(MAX_BYTES + 1)
        if not data or len(data) > MAX_BYTES: raise HTTPException(400, 'PDF는 1바이트 이상 20MB 이하여야 합니다.')
        try:
            if not app.state.ingestor.start(document_id, companyId, fileName, data):
                raise HTTPException(409, '이미 색인 중인 문서입니다.')
        except OverflowError:
            raise HTTPException(503, '동시 색인 한도 초과') from None
        return {'documentId': document_id, 'status': 'UPLOADED'}

    # 개발·내부 상태 확인용. 공개 사용자 조회 API는 Spring에서 요청자 인가 후 제공한다.
    @app.get('/tasks/{task_id}', dependencies=[Depends(auth)])
    async def state(task_id: UUID):
        snapshot = await app.state.graph.aget_state(TaskRunner._cfg(task_id))
        if not snapshot.values: raise HTTPException(404, '작업이 없습니다.')
        kind = pending_kind(snapshot)
        status = snapshot.values.get('status')
        if kind and status not in {'FAILED', 'DONE', 'REJECTED'}:
            status = 'WAITING_CONFIRMATION' if kind == 'CONFIRMATION' else 'WAITING_APPROVAL'
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
