from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class EventType(StrEnum):
    TOKEN = "TOKEN"
    TOOL_START = "TOOL_START"
    TOOL_END = "TOOL_END"
    CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    DONE = "DONE"
    FAILED = "FAILED"


class TaskStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    DONE = "DONE"
    FAILED = "FAILED"
    REJECTED = "REJECTED"


class TaskEvent(BaseModel):
    """§8 SSE 이벤트 (Spring /internal/tasks/{taskId}/events 로 전송)."""

    type: EventType
    taskId: str
    ts: datetime
    node: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
