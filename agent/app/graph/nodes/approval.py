from langgraph.types import interrupt

from ...models.api import Decision
from ...models.state import AXState


async def approval(state: AXState) -> dict:
    """로드맵 승인 대기. interrupt()로 멈추고 checkpointer에 상태를 저장한다.

    재개 값은 {decision, userId, reason}. 요청자 본인만 승인·거절할 수 있다.
    """
    roadmap = state.get("roadmap") or {}
    resume = interrupt(
        {
            "roadmap": roadmap,
            "items": roadmap.get("items", []),
            "totalAllocatedKrw": roadmap.get("totalAllocatedKrw"),
            "budgetKrw": roadmap.get("budgetKrw"),
        }
    )

    if resume["userId"] != state["user_id"]:
        raise PermissionError("작업 요청자 본인만 승인·거절할 수 있다")

    return {
        "approval": {
            "decision": Decision(resume["decision"]).value,
            "user_id": resume["userId"],
            "reason": resume.get("reason"),
        }
    }
