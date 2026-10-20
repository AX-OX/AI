"""§10 Graph의 분기·반복 규칙. 순수 함수로 두어 단독 테스트한다."""

from typing import Literal

from app.models.api import Decision
from app.models.state import AXState

MAX_DISCOVER_RETRIES = 2
# retry_count = 지금까지 수행한 discover 재탐색 횟수.
# 재탐색으로 돌아온 discover가 +1 한다 (evaluate가 올리지 않는다).


def after_collect(state: AXState) -> Literal["retrieve", "__end__"]:
    # 회사 ID 오류 등 복구 불가 오류 → FAILED
    return "__end__" if state.get("errors") else "retrieve"


def after_evaluate(state: AXState) -> Literal["discover", "roadmap"]:
    insufficient = (state.get("portfolio") or {}).get("insufficient", False)
    if insufficient and state.get("retry_count", 0) < MAX_DISCOVER_RETRIES:
        return "discover"
    return "roadmap"


def after_approval(state: AXState) -> Literal["register", "__end__"]:
    decision = (state.get("approval") or {}).get("decision")
    return "register" if decision == Decision.APPROVE else "__end__"
