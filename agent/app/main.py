from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from app.clients.spring import SpringClient
from app.config import Settings, get_settings
from app.graph.builder import build_graph
from app.models.api import ResumeRequest, RunRequest
from app.runner import TaskConflict, TaskForbidden, TaskNotResumable, TaskRunner


def create_app(runner: TaskRunner | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if runner is not None:  # 테스트: 주입된 runner 사용
            app.state.runner = runner
            yield
            return

        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        settings: Settings = get_settings()
        spring = SpringClient(settings)
        async with AsyncPostgresSaver.from_conn_string(settings.checkpointer_dsn) as saver:
            await saver.setup()
            app.state.runner = TaskRunner(build_graph(saver), spring, settings)
            yield
        await spring.aclose()

    app = FastAPI(title="AX Navigator Agent", lifespan=lifespan)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.post("/tasks/{task_id}/run", status_code=202)
    async def run(task_id: str, body: RunRequest):
        try:
            await app.state.runner.start(task_id, body)
        except TaskConflict:
            raise HTTPException(409, f"task {task_id}는 이미 실행 중이거나 존재한다")
        return {"taskId": task_id}

    @app.post("/tasks/{task_id}/resume", status_code=202)
    async def resume(task_id: str, body: ResumeRequest):
        try:
            await app.state.runner.resume(task_id, body)
        except TaskNotResumable:
            raise HTTPException(409, f"task {task_id}는 승인 대기 상태가 아니다")
        except TaskForbidden:
            raise HTTPException(403, "작업 요청자 본인만 승인·거절할 수 있다")
        return {"taskId": task_id}

    return app


app = create_app()
