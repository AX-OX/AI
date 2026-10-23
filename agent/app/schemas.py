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


class AssessmentAreaDraft(ContractModel):
    area: Literal["data_score", "infra_score", "automation_score", "ai_capability_score", "governance_score"]
    score: Score | None
    evidence_ids: list[str]
    summary: str = Field(min_length=1)
    missing_reason: str | None


class AssessmentDraft(ContractModel):
    areas: list[AssessmentAreaDraft] = Field(min_length=5, max_length=5)


class Recommendation(ContractModel):
    process_id: int
    solution_id: int
    reason: str = Field(min_length=1)
    document_ids: list[int] = Field(min_length=1)


class Narrative(ContractModel):
    summary: str = Field(min_length=1)
    recommendations: list[Recommendation] = Field(min_length=1, max_length=3)


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
    dependsOnProcessId: Annotated[int, Field(gt=0)] | None
    axScore: Score
    impactScore: Score
    feasibilityScore: Score
    savedHoursBase: float = Field(ge=0)
    apiOk: bool
    humanReviewRequired: bool
    dataConfidence: Literal["MEASURED", "SURVEY", "EXTRACTED", "ASSUMED"]
    warnings: list[str]
    firstYearTcoKrw: int = Field(gt=0)
    scenarios: RoiScenarios


class RunRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    companyId: int = Field(gt=0)
    userId: int = Field(gt=0)
    requestText: str = Field(min_length=1, max_length=4000)
    # false면 documentIds 문서에서 기업 데이터를 먼저 추출하고 사용자 확정을 기다린다.
    companyDataConfirmed: bool = True
    documentIds: list[Annotated[int, Field(gt=0)]] = Field(default_factory=list, max_length=20)

class ConfirmRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    userId: int = Field(gt=0)

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

class CandidateDraft(ContractModel):
    candidate_id: str
    reason: str = Field(min_length=1)
    evidence_ids: list[str]

class DiscoveryDraft(ContractModel):
    candidates: list[CandidateDraft] = Field(min_length=1,max_length=10)


SystemType = Literal["ERP", "CRM", "GROUPWARE", "HR", "ETC"]
AccessLevel = Literal["OPEN", "RESTRICTED", "NONE"]
WorkType = Literal["KNOWLEDGE_QA", "GUIDANCE", "DECISION_SUPPORT", "REPORT_AGGREGATION",
                   "RESEARCH_REPORT", "MEETING_SUMMARY", "TICKET_TRIAGE", "CODE_REVIEW", "DOC_AUTHORING", "OTHER"]


class CandidateRef(ContractModel):
    process_id: int = Field(gt=0)
    solution_id: int = Field(gt=0)


class SolutionCandidate(CandidateRef):
    work_type: WorkType
    depends_on: CandidateRef | None
    excluded_reason: str | None
    metrics_sufficient: bool


class CompanyExtract(ContractModel):
    industry: str | None
    employeeCount: Annotated[int, Field(gt=0)] | None


class DepartmentExtract(ContractModel):
    key: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=50)


class ProcessExtract(ContractModel):
    key: str = Field(min_length=1, max_length=50)
    departmentKey: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=100)
    workType: WorkType
    purpose: str | None
    steps: list[str]
    standardizationLevel: Annotated[float, Field(ge=0, le=1)] | None
    requiresApproval: bool
    exceptionRules: str | None
    sourceId: str | None


class MetricExtract(ContractModel):
    processKey: str = Field(min_length=1, max_length=50)
    monthlyCount: int = Field(ge=0)
    avgMinutes: float = Field(gt=0, le=999999)
    hourlyLaborCostKrw: int = Field(gt=0)
    errorRate: Annotated[float, Field(ge=0, le=1)] | None
    sourceId: str


class SystemExtract(ContractModel):
    key: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=100)
    type: SystemType
    apiAvailable: bool
    dataAccessLevel: AccessLevel
    cloudBased: bool
    processKeys: list[str]


class ExtractionDraft(ContractModel):
    """LLM 출력. sourceId는 제공된 문서 조각 ID만 쓴다. Agent가 {documentId, page}로 바꾼다."""
    company: CompanyExtract
    departments: list[DepartmentExtract] = Field(min_length=1, max_length=50)
    processes: list[ProcessExtract] = Field(min_length=1, max_length=200)
    metrics: list[MetricExtract] = Field(max_length=200)
    systems: list[SystemExtract] = Field(max_length=100)

from .models.state import AXState
