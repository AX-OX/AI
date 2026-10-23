"""§10 Graph의 분기·반복 규칙. 순수 함수로 두어 단독 테스트한다."""

from typing import Literal

from ..models.api import Decision
from ..models.state import AXState

MAX_DISCOVER_RETRIES = 2
# retry_count = 지금까지 수행한 discover 재탐색 횟수.
# 재탐색으로 돌아온 discover가 +1 한다 (evaluate가 올리지 않는다).


def at_start(state: AXState) -> Literal["extract", "collect"]:
    # 기업 데이터가 확정되지 않은 회사는 업로드 문서에서 먼저 추출하고 사용자 확정을 기다린다.
    return "collect" if state.get("company_data_confirmed", True) else "extract"


def after_discover(state: AXState) -> Literal["evaluate", "__end__"]:
    # 대상 솔루션이 없어 discover가 성숙도 진단으로 작업을 끝낸 경우(status=DONE)만 종료한다.
    return "__end__" if state.get("status") == "DONE" else "evaluate"


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
