import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import Settings
from app.models.events import EventType, TaskEvent

log = logging.getLogger(__name__)


class SpringClient:
    """Spring /internal/** 호출 (§7). 모든 요청에 X-Internal-Token을 붙인다."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self._client = client or httpx.AsyncClient(
            base_url=settings.spring_internal_url,
            headers={"X-Internal-Token": settings.internal_token},
            timeout=10,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def emit(
        self, task_id: str, type_: EventType, node: str | None = None, data: dict[str, Any] | None = None
    ) -> None:
        """POST /internal/tasks/{taskId}/events. 전송 실패가 작업을 죽이지 않게 로그만 남긴다."""
        event = TaskEvent(type=type_, taskId=task_id, ts=datetime.now(timezone.utc), node=node, data=data or {})
        try:
            r = await self._client.post(f"/tasks/{task_id}/events", content=event.model_dump_json())
            r.raise_for_status()
        except httpx.HTTPError as e:
            log.warning("event 전송 실패 task=%s type=%s: %s", task_id, type_, e)

    async def patch_task(self, task_id: str, **fields: Any) -> None:
        """PATCH /internal/tasks/{taskId}: status, result, errorMessage, traceUrl 등."""
        try:
            r = await self._client.patch(f"/tasks/{task_id}", json=fields)
            r.raise_for_status()
        except httpx.HTTPError as e:
            log.warning("task 갱신 실패 task=%s fields=%s: %s", task_id, list(fields), e)
