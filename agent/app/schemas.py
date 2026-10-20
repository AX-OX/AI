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

from .models.state import AXState
