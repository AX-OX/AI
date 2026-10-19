from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


class AXState(TypedDict):
    """§10 State. 계약이므로 필드를 임의로 바꾸지 않는다."""

    task_id: str  # = thread_id
    company_id: int
    user_id: int  # 작업 요청자 (승인 가능한 유일한 사용자)
    request: str
    messages: Annotated[list, add_messages]
    company: dict
    processes: list[dict]
    metrics: list[dict]
    systems: list[dict]
    evidence: list[dict]  # {document_id, title, section, content}
    maturity: dict  # 영역별 점수·근거, total_score, assessment_id
    insufficient_data: list[str]
    candidates: list[dict]  # {process_id, solution_id, reason}
    roi: list[dict]  # calculate_ax_roi 결과
    portfolio: dict  # optimize_ax_portfolio 결과
    roadmap: dict  # 로드맵 초안 (항목·근거)
    approval: dict | None  # {decision, user_id, reason}
    retry_count: int  # discover 재시도 횟수
    errors: list[str]
