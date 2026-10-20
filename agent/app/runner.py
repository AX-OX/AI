import asyncio
import logging

from app.clients.spring import SpringClient
from app.config import Settings
from app.models.api import Decision, ResumeRequest, RunRequest
from app.models.events import EventType, TaskStatus

log = logging.getLogger(__name__)


class TaskConflict(Exception):
    """같은 taskId가 이미 실행/존재."""


class TaskNotResumable(Exception):
    """승인 대기 상태가 아니거나 없는 taskId."""


class TaskForbidden(Exception):
    """작업 요청자가 아닌 사용자의 재개 시도."""


class TaskRunner:
    def __init__(self, graph, spring: SpringClient, settings: Settings):
        self.graph = graph
        self.spring = spring
        self.settings = settings
        self._running: set[str] = set()
        self._tasks: set[asyncio.Task] = set()

    @staticmethod
    def _cfg(task_id: str) -> dict:
        return {"configurable": {"thread_id": task_id}}  # thread_id = taskId

    def _spawn(self, coro) -> None:
        t = asyncio.create_task(coro)
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)

    async def start(self, task_id: str, req: RunRequest) -> None:
        snap = await self.graph.aget_state(self._cfg(task_id))
        if task_id in self._running or snap.values:
            raise TaskConflict(task_id)
        self._running.add(task_id)
        initial = {
            "task_id": task_id,
            "company_id": req.companyId,
            "user_id": req.userId,
            "request": req.requestText,
            "messages": [],
            "errors": [],
            "retry_count": 0,
        }
        self._spawn(self._execute(task_id, initial))

    async def resume(self, task_id: str, req: ResumeRequest) -> None:
        from langgraph.types import Command

        snap = await self.graph.aget_state(self._cfg(task_id))
        if task_id in self._running or snap.next != ("approval",):
            raise TaskNotResumable(task_id)
        if snap.values.get("user_id") != req.userId:
            raise TaskForbidden(task_id)
        self._running.add(task_id)
        value = Command(resume={"decision": req.decision.value, "userId": req.userId, "reason": req.reason})
        self._spawn(self._execute(task_id, value))

    async def _execute(self, task_id: str, graph_input) -> None:
        try:
            await self.spring.patch_task(task_id, status=TaskStatus.RUNNING.value)
            async with asyncio.timeout(self.settings.task_timeout_seconds):
                await self.graph.ainvoke(graph_input, self._cfg(task_id))
            await self._finish(task_id)
        except Exception as e:  # noqa: BLE001 - 어떤 실패든 FAILED로 마감
            log.exception("task 실패 %s", task_id)
            await self.spring.patch_task(task_id, status=TaskStatus.FAILED.value, errorMessage=str(e))
            await self.spring.emit(task_id, EventType.FAILED, data={"message": str(e)})
        finally:
            self._running.discard(task_id)

    async def _finish(self, task_id: str) -> None:
        snap = await self.graph.aget_state(self._cfg(task_id))
        values = snap.values

        if snap.next == ("approval",):  # interrupt()로 멈춤
            payload = snap.tasks[0].interrupts[0].value
            await self.spring.patch_task(task_id, status=TaskStatus.WAITING_APPROVAL.value)
            await self.spring.emit(task_id, EventType.APPROVAL_REQUIRED, node="approval", data=payload)
        elif values.get("errors"):
            message = "; ".join(values["errors"])
            await self.spring.patch_task(task_id, status=TaskStatus.FAILED.value, errorMessage=message)
            await self.spring.emit(task_id, EventType.FAILED, data={"message": message})
        elif (values.get("approval") or {}).get("decision") == Decision.REJECT:
            await self.spring.patch_task(task_id, status=TaskStatus.REJECTED.value)
            await self.spring.emit(task_id, EventType.DONE, data={"result": {"rejected": True}})
        else:
            # 🔴 result 구조는 팀 합의 전 (성숙도·후보 과제·시나리오별 ROI)
            result = {
                "maturity": values.get("maturity"),
                "portfolio": values.get("portfolio"),
                "roadmap": values.get("roadmap"),
            }
            await self.spring.patch_task(task_id, status=TaskStatus.DONE.value, result=result)
            await self.spring.emit(task_id, EventType.DONE, data={"result": result})
