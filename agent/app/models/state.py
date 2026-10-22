from typing import Annotated, TypedDict
from langgraph.graph.message import add_messages

class AXState(TypedDict, total=False):
    task_id: str
    company_id: int
    user_id: int
    request: str
    company_data_confirmed: bool
    document_ids: list[int]
    extraction: dict
    messages: Annotated[list, add_messages]
    company: dict
    processes: list[dict]
    metrics: list[dict]
    systems: dict
    budget: dict
    budget_krw: int | None
    solutions: list[dict]
    evidence: list[dict]
    assessment_evidence: list[dict]
    business_evidence: list[dict]
    scope: dict
    excluded: list[dict]
    evaluation_policy: dict
    opportunities: list[dict]
    maturity: dict
    insufficient_data: list[str]
    candidates: list[dict]
    roi: list[dict]
    portfolio: dict
    roadmap: dict
    approval: dict | None
    retry_count: int
    errors: list[str]
    status: str
    registration: dict
    answer: str
