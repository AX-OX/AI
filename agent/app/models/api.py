from enum import StrEnum

from pydantic import BaseModel


class RunRequest(BaseModel):
    companyId: int
    userId: int
    requestText: str


class Decision(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class ResumeRequest(BaseModel):
    decision: Decision
    userId: int
    reason: str | None = None
