from typing import Annotated, Any, Literal, TypedDict
from pydantic import BaseModel, Field, ConfigDict


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


Score = Annotated[float, Field(ge=0, le=100)]


class AssessmentEvidence(ContractModel):
    area: Literal["data_score", "infra_score", "automation_score", "ai_capability_score", "governance_score"]
    document_id: int
    section: str = Field(min_length=1)
    summary: str = Field(min_length=1)


class Assessment(ContractModel):
    scores: dict[str, Score]
    evidence: list[AssessmentEvidence]
    insufficient_data: list[str] = Field(default_factory=list)


class Recommendation(ContractModel):
    solution_id: int
    reason: str = Field(min_length=1)
    document_ids: list[int] = Field(min_length=1)


class Narrative(ContractModel):
    summary: str = Field(min_length=1)
    recommendations: list[Recommendation] = Field(min_length=3, max_length=3)


class RoiScenario(ContractModel):
    annualSavingKrw: int = Field(ge=0)
    roiPct: float
    paybackMonths: Annotated[float, Field(ge=0)] | None
    threeYearNetKrw: int


class RoiScenarios(ContractModel):
    low: RoiScenario
    base: RoiScenario
    high: RoiScenario


class RoiResult(ContractModel):
    processId: int = Field(gt=0)
    solutionId: int = Field(gt=0)
    dependsOnSolutionId: Annotated[int, Field(gt=0)] | None
    axScore: Score
    impactScore: Score
    feasibilityScore: Score
    savedHoursBase: float = Field(ge=0)
    apiOk: bool
    humanReviewRequired: bool
    dataConfidence: Literal["MEASURED", "SURVEY", "ASSUMED"]
    warnings: list[str]
    firstYearTcoKrw: int = Field(gt=0)
    scenarios: RoiScenarios

from langgraph.graph.message import add_messages

class RunRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    companyId: int = Field(gt=0)
    userId: int = Field(gt=0)
    requestText: str = Field(min_length=1, max_length=4000)

class ResumeRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    decision: Literal['APPROVE', 'REJECT']
    userId: int = Field(gt=0)
    reason: str | None = Field(default=None, max_length=2000)

class Candidate(BaseModel):
    process_id: int
    solution_id: int
    reason: str
    document_ids: list[int] = Field(min_length=1)

class Discovery(BaseModel):
    candidates: list[Candidate] = Field(max_length=10)

class AXState(TypedDict, total=False):
    task_id: str
    company_id: int
    user_id: int
    request: str
    messages: Annotated[list, add_messages]
    company: dict
    processes: list[dict]
    metrics: list[dict]
    systems: dict
    budget: dict
    solutions: list[dict]
    evidence: list[dict]
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
