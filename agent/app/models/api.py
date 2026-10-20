from enum import StrEnum
from ..schemas import RunRequest, ResumeRequest

class Decision(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
