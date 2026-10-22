# AX Navigator AI — 프로젝트 공통 컨텍스트

> 이 문서는 팀원 각자가 AI 코딩 도구에 **가장 먼저 넣는 공통 기준 문서**다.
> 여기 적힌 계약(DB, API, MCP 도구, 이벤트, State)은 팀 합의 사항이므로 **AI가 임의로 바꾸지 않는다.**
> 바꿔야 할 이유가 생기면 코드를 고치기 전에 "계약 변경 제안"으로 먼저 알린다.

---

## 0. AI에게 주는 작업 규칙

1. 이 문서의 계약(§5~§10)과 다른 이름·필드·경로를 만들지 않는다. 없는 것이 필요하면 제안만 한다.
2. 지금 작업 중인 서비스 폴더 밖의 코드는 수정하지 않는다. 다른 서비스가 필요하면 mock으로 대체한다.
3. **업무 데이터는 Agent(FastAPI)·business-mcp에서 DB에 직접 접근하지 않고 Spring `/internal/**`로만 읽고 쓴다.** 예외: rag-mcp는 문서 검색을 위해 `ax`의 pgvector 색인만 읽고, indexer는 문서 소속 확인 및 색인 적재를 수행한다(§5·§9). Agent의 checkpointer는 별도 DB `agent`에 상태만 저장한다. 이 예외로 업무 데이터 변경이나 업무 계산을 우회하지 않는다.
4. **운영 업무 규칙(AX점수·ROI·포트폴리오 계산)은 Spring Boot에만** 둔다. Agent·MCP에 계산식을 복제하지 않는다. Agent와 화면은 Spring이 계산한 값을 그대로 인용한다. 데이터 패키지의 `examples/compute_ax.py`는 정답 파일 생성·검산 전용 오프라인 도구이며 운영 요청 처리에 사용하지 않는다.
5. AX점수·ROI·구축비·자동화율 숫자를 LLM이 만들지 않는다. 항상 `ai_solution_catalog`, `process_metrics`, `config/ax_score_policy_v1.json` 값으로 계산한다.
6. MVP다. §2의 "제외" 항목은 구현하지 않는다. 더 좋은 방법이 있어도 범위를 넓히지 않는다.
7. 비밀값(LLM 키, JWT 시크릿, 내부 토큰)은 코드에 쓰지 않고 `.env`로만 받는다.

---

## 1. 프로젝트 요약

- **이름**: AX Navigator AI
- **한 줄 소개**: 기업의 업무 데이터와 내부 문서를 분석해 AX(AI 전환) 성숙도를 진단하고, **AX점수(효과·실현 가능성)** 기반으로 예산 안에서 AI 도입 과제를 선정해 로드맵을 만들고, 사람이 승인하면 프로젝트로 등록하는 B2B AI Agent 플랫폼
- **고객**: AX를 추진하는 중견·중소기업의 DX/AX 전략 부서, AI 도입 컨설팅사
- **과정**: SKALA AI-Agent Capstone(+MCP)

### MVP 시나리오 (이것 하나를 끝까지 동작시킨다)
- 가상 기업: 직원 200명 B2B 제조기업 1곳 (사내 시스템을 직접 개발·운영하는 개발팀 보유)
- 대상 부서: **인사·기획·개발** 3개 (부서당 업무 3개, 총 9개)
- AX 예산: 연간 3억 원
- 사용자 요청 예시:
  > "현재 업무 데이터를 분석해서 AI 도입 효과가 높은 과제 3개를 선정하고, 예산 3억 원 내에서 최적의 AX 투자 로드맵을 만들어 줘."
- 흐름: 로그인 → 요청(202) → 진행 이벤트(SSE) → 성숙도·**AX점수 기준 과제 3개**·보조 지표(ROI·회수 기간·3년 순편익)·근거 문서 → **승인 카드** → 요청자 본인이 승인 → 로드맵·프로젝트 등록 → DONE

---

## 2. 범위

| 포함 | 제외 (구현하지 않음) |
|---|---|
| LangGraph StateGraph 1개, 역할별 Node 8개 | Agent별 독립 프로세스(진짜 Multi-Agent) |
| 성숙도 5개 영역 가중합 | GraphRAG |
| AX점수 = Impact·Feasibility 가중합 (§6) | TOPSIS 등 MCDA 알고리즘, 데이터 신뢰도의 점수 반영 |
| 포트폴리오: 후보 전수 조합 탐색 (예산·선행 과제 조건, AX점수 합 최대) | 최적화 라이브러리, 인력·기간 제약 |
| 보수·기준·낙관 3개 시나리오 ROI (**보조 지표**) | 몬테카를로 시뮬레이션, ROI 기준 선정 |
| 승인(HITL), 상태 저장·재개, 진행 이벤트 | 성과 모니터링 Agent, `get_project_kpis` |
| JWT 인증, 요청자 본인 승인 | OAuth, 역할별 권한(ADMIN/MEMBER), 별도 담당자 승인, 다중 기업 관리 화면 |
| (여유 시) RabbitMQ 작업 큐·재시도 | Kafka |

---

## 3. 기술 스택

| 계층 | 기술 |
|---|---|
| Frontend | React 19 + Vite + TypeScript + Tailwind CSS v4, nginx로 정적 서빙 |
| Backend | **Spring Boot 4.1.1, Java 21**, Spring Security 7(JWT), Spring Data JPA(Hibernate 7), `SseEmitter`, Jackson 3 |
| Agent | Python 3.11+, FastAPI, LangGraph 1.x, LangChain 1.x, LangSmith |
| MCP | FastMCP 4.1 (Server·Client), mcp 2.x, **Streamable HTTP** (`/mcp`) |
| DB | PostgreSQL 16 (업무 DB `ax`, checkpointer DB `agent`) |
| 벡터 저장·검색 | PostgreSQL 16 + pgvector 0.8.1 (`ax` DB의 RAG 전용 테이블, 별도 벡터 DB 서비스 없음) |
| LLM | OpenAI 등 (모델명은 `.env`로) |
| 배포 | docker compose (단일 호스트) |

---

## 4. 아키텍처

### 서비스 (docker compose)

| 서비스 | 기술 | 포트 | 공개 | 역할 |
|---|---|---|---|---|
| `frontend` | React 19 (Vite 빌드) + nginx | 80 | 공개 | 화면 |
| `backend` | Spring Boot | 8080 | 공개 | 인증, 작업 API(202), SSE 중계, 승인, 업무 규칙, `/internal/**` |
| `agent` | FastAPI | 8000 | 내부 | LangGraph + Harness, MCP Client |
| `business-mcp` | FastMCP | 9101 | 내부 | 업무 도구 → `/internal/**` 호출 |
| `rag-mcp` | FastMCP | 9102 | 내부 | 문서 검색 도구 → PostgreSQL pgvector, 원문 Resource |
| `postgres` | PostgreSQL 16 + pgvector 0.8.1 | 5432 | 내부 | 하나의 PostgreSQL 인스턴스에 `ax`(업무·작업·벡터 색인), `agent`(checkpointer) |
| `indexer` | rag-mcp 이미지 | - | - | 문서 색인 1회 실행 (`profiles: [tools]`) |

### 처리 흐름
1. React → Spring `POST /api/ai/tasks` → **202 `{taskId}`** 즉시 반환
2. Spring → Agent `POST /tasks/{taskId}/run` (내부 HTTP, 여유 시 RabbitMQ)
3. Agent → LLM (Harness가 Instructions·Context를 붙여 호출)
4. Agent(MCP Client) → business-mcp / rag-mcp `tools/call`
5. business-mcp → Spring `/internal/**` (업무 데이터 조회·변경)
6. rag-mcp → PostgreSQL `ax`의 pgvector 색인 (근거 chunk 검색), 원문은 `docs://{document_id}` Resource. 업무 데이터·AX 계산은 계속 Spring을 통한다.
7. Agent → Spring `POST /internal/tasks/{taskId}/events` → Spring이 SSE로 React에 중계

### Trust Boundary
- 공개 포트는 frontend 80, backend 8080뿐.
- backend 8080이 공개라서 `/internal/**`도 외부에서 닿는다 → **`X-Internal-Token` 헤더가 없으면 403** (Spring Security 필터). agent·business-mcp만 이 토큰을 가진다.
- React(:80)가 Spring(:8080)을 직접 호출하므로 Spring에 CORS 허용(`CORS_ORIGIN`), `/stream` 포함. 요청 헤더 `Authorization`을 허용한다.

### 기동 순서 (순환 금지)
`postgres`(스키마·시드 적용) → `backend` → `business-mcp` → `agent` → `frontend`

RAG 준비 경로: `postgres`(문서 시드 포함) → `indexer`(최초 색인 완료) → `rag-mcp` → `agent`.
**backend는 agent에 `depends_on` 하지 않는다** (작업 요청 시점에만 호출).
`business-mcp`는 backend 준비 후, `indexer`는 PostgreSQL 준비 후 실행한다. `indexer`는 상시 서비스가 아닌 1회 실행 작업이다. PostgreSQL 이미지 예: `pgvector/pgvector:0.8.1-pg16`. DB 배포는 하나이며 backend·MCP·Agent 서비스는 별도로 실행한다.

---

## 5. DB 스키마 (확정)

- `ax`의 **업무 테이블은 14개, FK 24개**다. 아래 업무 DDL과 별도로 §5의 RAG 확장 DDL에서 `rag_indexes`, `rag_document_chunks` 2개 테이블·FK 3개를 추가한다. 전체 `ax`는 **16개 테이블, FK 27개**이며 `agent`의 checkpointer 테이블은 이 수에 포함하지 않는다.
- 실제 생성 시 `BIGINT` PK → `BIGINT GENERATED ALWAYS AS IDENTITY` (단, `ai_tasks.task_id`는 UUID 문자열).
- 상태·유형 허용값은 주석 참고, Spring에서 Enum으로 검증.
- 비율은 0~1, 금액은 KRW 정수, 시간은 분.

| 구분 | 테이블 |
|---|---|
| 기업·업무 (Input) | `companies`, `departments`, `business_processes`, `process_metrics`, `it_systems`, `process_systems`, `documents` |
| 기준 데이터 | `ai_solution_catalog` (ROI 가정값, LLM이 만들지 않음) |
| 플랫폼 | `users`, `ai_tasks` |
| 분석·실행 (Output) | `ax_assessments`, `ax_roadmaps`, `roadmap_items`, `ax_projects` |

후보 과제 전체와 시나리오별 ROI는 `ai_tasks.result`(JSONB) 스냅샷에, 승인된 과제의 핵심 수치만 `roadmap_items`에 저장한다.

```sql
-- ============================================================
-- AX Navigator AI — MVP Schema (PostgreSQL 16)
-- 14 tables · 업무 DB(ax)
-- * 문서 chunk·임베딩은 같은 ax DB의 pgvector에 저장 (아래 RAG 확장 DDL에 별도 정의)
-- * LangGraph checkpointer는 별도 DB(agent)에 자동 생성
-- * ERD 도구 호환을 위해 PK는 BIGINT로 선언.
--   실제 생성 시 BIGINT → BIGINT GENERATED ALWAYS AS IDENTITY 로 변경
-- ============================================================


-- ------------------------------------------------------------
-- 1. 기업·업무 (Input)
-- ------------------------------------------------------------

CREATE TABLE companies (
    company_id          BIGINT          NOT NULL,
    company_name        VARCHAR(100)    NOT NULL,   -- 기업명
    industry            VARCHAR(50)     NOT NULL,   -- 업종
    employee_count      INTEGER         NOT NULL,   -- 직원 수
    ax_budget_krw       BIGINT          NOT NULL,   -- 연간 AX 투자 예산(원)
    created_at          TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_companies PRIMARY KEY (company_id)
);

CREATE TABLE departments (
    department_id       BIGINT          NOT NULL,
    company_id          BIGINT          NOT NULL,
    department_name     VARCHAR(50)     NOT NULL,   -- 부서명
    manager_name        VARCHAR(50),                -- 담당자명
    manager_email       VARCHAR(100),               -- 담당자 이메일 (마스킹 대상)
    manager_phone       VARCHAR(20),                -- 담당자 연락처 (마스킹 대상)
    CONSTRAINT pk_departments PRIMARY KEY (department_id),
    CONSTRAINT fk_departments_company FOREIGN KEY (company_id) REFERENCES companies (company_id)
);

CREATE TABLE business_processes (
    process_id              BIGINT          NOT NULL,
    department_id           BIGINT          NOT NULL,
    process_name            VARCHAR(100)    NOT NULL,   -- 업무명
    purpose                 TEXT,                       -- 업무 목적
    process_steps           JSONB,                      -- 처리 절차 ["견적 수신", "비교표 작성", ...]
    standardization_level   NUMERIC(3,2),               -- 표준화 수준 0~1
    requires_approval       BOOLEAN         NOT NULL DEFAULT FALSE,  -- 승인 필요 여부
    exception_rules         TEXT,                       -- 자동화 제외 단계·제한사항
    CONSTRAINT pk_business_processes PRIMARY KEY (process_id),
    CONSTRAINT fk_processes_department FOREIGN KEY (department_id) REFERENCES departments (department_id)
);

CREATE TABLE process_metrics (
    metric_id               BIGINT          NOT NULL,
    process_id              BIGINT          NOT NULL,
    period_start            DATE            NOT NULL,   -- 측정 시작일
    period_end              DATE            NOT NULL,   -- 측정 종료일
    processing_count        INTEGER         NOT NULL,   -- 기간 내 처리 건수
    avg_processing_minutes  NUMERIC(8,2)    NOT NULL,   -- 건당 평균 처리 시간(분)
    error_rate              NUMERIC(5,4),               -- 오류율 0~1
    hourly_labor_cost_krw   INTEGER         NOT NULL,   -- 시간당 인건비(원)
    data_source             VARCHAR(20)     NOT NULL,   -- MEASURED / SURVEY / ASSUMED
    CONSTRAINT pk_process_metrics PRIMARY KEY (metric_id),
    CONSTRAINT fk_metrics_process FOREIGN KEY (process_id) REFERENCES business_processes (process_id)
);

CREATE TABLE it_systems (
    system_id           BIGINT          NOT NULL,
    company_id          BIGINT          NOT NULL,
    system_name         VARCHAR(100)    NOT NULL,   -- 시스템명
    system_type         VARCHAR(30)     NOT NULL,   -- ERP / CRM / GROUPWARE / HR / ETC
    api_available       BOOLEAN         NOT NULL DEFAULT FALSE,  -- API 제공 여부
    data_access_level   VARCHAR(20)     NOT NULL,   -- OPEN / RESTRICTED / NONE
    cloud_based         BOOLEAN         NOT NULL DEFAULT FALSE,  -- 클라우드 여부
    CONSTRAINT pk_it_systems PRIMARY KEY (system_id),
    CONSTRAINT fk_systems_company FOREIGN KEY (company_id) REFERENCES companies (company_id)
);

CREATE TABLE process_systems (
    process_id          BIGINT          NOT NULL,
    system_id           BIGINT          NOT NULL,
    usage_purpose       VARCHAR(200),               -- 활용 목적
    CONSTRAINT pk_process_systems PRIMARY KEY (process_id, system_id),
    CONSTRAINT fk_ps_process FOREIGN KEY (process_id) REFERENCES business_processes (process_id),
    CONSTRAINT fk_ps_system  FOREIGN KEY (system_id)  REFERENCES it_systems (system_id)
);

CREATE TABLE documents (
    document_id         BIGINT          NOT NULL,
    company_id          BIGINT          NOT NULL,
    process_id          BIGINT,                     -- 공통 문서면 NULL
    title               VARCHAR(200)    NOT NULL,   -- 문서명
    doc_type            VARCHAR(30)     NOT NULL,   -- MANUAL / POLICY / SYSTEM_SPEC / AI_STATUS / DATA_QUALITY / PROJECT_REPORT
    file_uri            VARCHAR(500)    NOT NULL,   -- 원본 경로 (Resource docs://{document_id})
    access_level        VARCHAR(20)     NOT NULL,   -- PUBLIC / INTERNAL / CONFIDENTIAL (민감도 표시용, 검색 권한과 무관)
    version             VARCHAR(20)     NOT NULL DEFAULT 'v1',
    created_at          TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_documents PRIMARY KEY (document_id),
    CONSTRAINT fk_documents_company FOREIGN KEY (company_id) REFERENCES companies (company_id),
    CONSTRAINT fk_documents_process FOREIGN KEY (process_id) REFERENCES business_processes (process_id)
);


-- ------------------------------------------------------------
-- 2. 기준 데이터 (ROI 가정값 — LLM이 만들지 않음)
-- ------------------------------------------------------------

CREATE TABLE ai_solution_catalog (
    solution_id                 BIGINT          NOT NULL,
    target_process_id           BIGINT          NOT NULL,   -- 이 솔루션을 적용할 업무
    depends_on_solution_id      BIGINT,                     -- 선행 과제 (같은 포트폴리오에 함께 선정돼야 함)
    solution_type               VARCHAR(30)     NOT NULL,   -- RAG / AI_AGENT / PREDICTION / CLASSIFICATION / RPA
    solution_name               VARCHAR(100)    NOT NULL,
    description                 TEXT,
    base_build_cost_krw         BIGINT          NOT NULL,   -- 기준 구축비(원)
    monthly_run_cost_krw        BIGINT          NOT NULL,   -- 월 운영비(원)
    automation_rate_low         NUMERIC(3,2)    NOT NULL,   -- 자동화율 보수 0~1
    automation_rate_base        NUMERIC(3,2)    NOT NULL,   -- 자동화율 기준
    automation_rate_high        NUMERIC(3,2)    NOT NULL,   -- 자동화율 낙관
    time_reduction_rate_low     NUMERIC(3,2)    NOT NULL,   -- 시간 절감률 보수 0~1
    time_reduction_rate_base    NUMERIC(3,2)    NOT NULL,
    time_reduction_rate_high    NUMERIC(3,2)    NOT NULL,
    min_standardization_level   NUMERIC(3,2),               -- 적용 최소 표준화 수준
    requires_api                BOOLEAN         NOT NULL DEFAULT FALSE,  -- 시스템 API 필요 여부
    data_source                 VARCHAR(20)     NOT NULL DEFAULT 'ASSUMED',
    CONSTRAINT pk_ai_solution_catalog PRIMARY KEY (solution_id),
    CONSTRAINT fk_catalog_process    FOREIGN KEY (target_process_id)      REFERENCES business_processes (process_id),
    CONSTRAINT fk_catalog_depends_on FOREIGN KEY (depends_on_solution_id) REFERENCES ai_solution_catalog (solution_id)
);


-- ------------------------------------------------------------
-- 3. 플랫폼 운영
-- ------------------------------------------------------------

CREATE TABLE users (
    user_id             BIGINT          NOT NULL,
    company_id          BIGINT          NOT NULL,
    email               VARCHAR(100)    NOT NULL,   -- 로그인 ID
    password_hash       VARCHAR(200)    NOT NULL,   -- BCrypt
    user_name           VARCHAR(50)     NOT NULL,
    created_at          TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_users PRIMARY KEY (user_id),
    CONSTRAINT uq_users_email UNIQUE (email),
    CONSTRAINT fk_users_company FOREIGN KEY (company_id) REFERENCES companies (company_id)
);

CREATE TABLE ai_tasks (
    task_id             VARCHAR(36)     NOT NULL,   -- UUID = LangGraph thread_id
    user_id             BIGINT          NOT NULL,
    company_id          BIGINT          NOT NULL,
    request_text        TEXT            NOT NULL,   -- 사용자 요청
    status              VARCHAR(30)     NOT NULL,   -- QUEUED / RUNNING / WAITING_APPROVAL / DONE / FAILED / REJECTED
    result              JSONB,                      -- 성숙도·후보 과제·ROI 시나리오 스냅샷
    error_message       TEXT,
    trace_url           VARCHAR(500),               -- LangSmith trace 링크
    created_at          TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at        TIMESTAMP,
    CONSTRAINT pk_ai_tasks PRIMARY KEY (task_id),
    CONSTRAINT fk_tasks_user    FOREIGN KEY (user_id)    REFERENCES users (user_id),
    CONSTRAINT fk_tasks_company FOREIGN KEY (company_id) REFERENCES companies (company_id)
);


-- ------------------------------------------------------------
-- 4. 분석·실행 (Output)
-- ------------------------------------------------------------

CREATE TABLE ax_assessments (
    assessment_id       BIGINT          NOT NULL,
    company_id          BIGINT          NOT NULL,
    task_id             VARCHAR(36)     NOT NULL,
    data_score          NUMERIC(5,2)    NOT NULL,   -- 데이터 준비도 0~100
    infra_score         NUMERIC(5,2)    NOT NULL,   -- IT 인프라
    automation_score    NUMERIC(5,2)    NOT NULL,   -- 업무 자동화
    ai_capability_score NUMERIC(5,2)    NOT NULL,   -- AI 활용 역량
    governance_score    NUMERIC(5,2)    NOT NULL,   -- AI 거버넌스
    total_score         NUMERIC(5,2)    NOT NULL,   -- 가중합
    criteria_version    VARCHAR(20)     NOT NULL,   -- 평가 기준 설정 파일 버전
    evidence            JSONB,                      -- [{area, document_id, section, summary}]
    created_at          TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_ax_assessments PRIMARY KEY (assessment_id),
    CONSTRAINT fk_assessments_company FOREIGN KEY (company_id) REFERENCES companies (company_id),
    CONSTRAINT fk_assessments_task    FOREIGN KEY (task_id)    REFERENCES ai_tasks (task_id)
);

CREATE TABLE ax_roadmaps (
    roadmap_id          BIGINT          NOT NULL,
    company_id          BIGINT          NOT NULL,
    task_id             VARCHAR(36)     NOT NULL,
    assessment_id       BIGINT,
    roadmap_name        VARCHAR(200)    NOT NULL,
    budget_limit_krw    BIGINT          NOT NULL,   -- 생성 시점 예산 스냅샷
    total_allocated_krw BIGINT          NOT NULL,   -- 배정 합계
    approval_status     VARCHAR(20)     NOT NULL,   -- PENDING / APPROVED / REJECTED
    approved_by         BIGINT,                     -- 승인·거절한 사용자 = ai_tasks.user_id (요청자 본인)
    approved_at         TIMESTAMP,                  -- 요청자 승인·거절 시각
    rejection_reason    TEXT,
    created_at          TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_ax_roadmaps PRIMARY KEY (roadmap_id),
    CONSTRAINT fk_roadmaps_company    FOREIGN KEY (company_id)    REFERENCES companies (company_id),
    CONSTRAINT fk_roadmaps_task       FOREIGN KEY (task_id)       REFERENCES ai_tasks (task_id),
    CONSTRAINT fk_roadmaps_assessment FOREIGN KEY (assessment_id) REFERENCES ax_assessments (assessment_id),
    CONSTRAINT fk_roadmaps_approver   FOREIGN KEY (approved_by)   REFERENCES users (user_id)
);

CREATE TABLE roadmap_items (
    item_id                     BIGINT          NOT NULL,
    roadmap_id                  BIGINT          NOT NULL,
    process_id                  BIGINT          NOT NULL,   -- 자동화 대상 업무
    solution_id                 BIGINT          NOT NULL,   -- 적용 기술
    item_name                   VARCHAR(200)    NOT NULL,   -- 과제명
    priority_order              INTEGER         NOT NULL,   -- 우선순위
    phase                       VARCHAR(10)     NOT NULL,   -- SHORT / MID / LONG
    start_month                 INTEGER         NOT NULL,   -- 로드맵 기준 시작 월 (1~12)
    duration_months             INTEGER         NOT NULL,
    allocated_budget_krw        BIGINT          NOT NULL,   -- 배정 예산 (= 초년도 TCO)
    ax_score                    NUMERIC(5,1)    NOT NULL,   -- 선정 기준 AX점수 0~100 (§6)
    impact_score                NUMERIC(5,1)    NOT NULL,   -- Impact 0~100
    feasibility_score           NUMERIC(5,1)    NOT NULL,   -- Feasibility 0~100
    expected_annual_saving_krw  BIGINT          NOT NULL,   -- [보조] 기준 시나리오 연간 절감액
    roi_pct                     NUMERIC(7,2)    NOT NULL,   -- [보조] 기준 시나리오 1년 ROI
    payback_months              NUMERIC(5,1),               -- [보조] 투자 회수 기간
    three_year_net_value_krw    BIGINT          NOT NULL,   -- [보조] 기준 시나리오 3년 순편익
    rationale                   TEXT            NOT NULL,   -- 추천 근거
    evidence                    JSONB,                      -- [{document_id, section, summary}]
    CONSTRAINT pk_roadmap_items PRIMARY KEY (item_id),
    CONSTRAINT fk_items_roadmap  FOREIGN KEY (roadmap_id)  REFERENCES ax_roadmaps (roadmap_id),
    CONSTRAINT fk_items_process  FOREIGN KEY (process_id)  REFERENCES business_processes (process_id),
    CONSTRAINT fk_items_solution FOREIGN KEY (solution_id) REFERENCES ai_solution_catalog (solution_id)
);

CREATE TABLE ax_projects (
    project_id          BIGINT          NOT NULL,
    item_id             BIGINT          NOT NULL,   -- 1 로드맵 항목 : 1 프로젝트
    owner_department_id BIGINT          NOT NULL,   -- 담당 부서
    project_name        VARCHAR(200)    NOT NULL,
    project_status      VARCHAR(20)     NOT NULL,   -- REGISTERED / IN_PROGRESS / ON_HOLD / COMPLETED
    start_date          DATE,
    end_date            DATE,
    created_at          TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_ax_projects PRIMARY KEY (project_id),
    CONSTRAINT uq_projects_item UNIQUE (item_id),
    CONSTRAINT fk_projects_item       FOREIGN KEY (item_id)             REFERENCES roadmap_items (item_id),
    CONSTRAINT fk_projects_department FOREIGN KEY (owner_department_id) REFERENCES departments (department_id)
);
```

### RAG 확장 DDL (`sql/03_pgvector.sql`)

다음은 위 14개 업무 테이블을 생성한 뒤 같은 `ax` DB에 적용한다. 기존 코드의 `db/init/03_pgvector.sql`과 같은 구조다. 단일 PostgreSQL 인스턴스에 업무 데이터와 벡터를 저장하며 `agent` DB는 checkpointer 전용이다.

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS rag_indexes (
    company_id BIGINT NOT NULL REFERENCES companies(company_id),
    index_version TEXT NOT NULL,
    embedding_model TEXT NOT NULL,
    embedding_revision TEXT NOT NULL,
    corpus_hash TEXT NOT NULL,
    chunk_count INTEGER NOT NULL CHECK (chunk_count > 0),
    indexed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (company_id, index_version)
);
CREATE TABLE IF NOT EXISTS rag_document_chunks (
    company_id BIGINT NOT NULL,
    index_version TEXT NOT NULL,
    chunk_id TEXT NOT NULL,
    document_id BIGINT NOT NULL REFERENCES documents(document_id),
    title TEXT NOT NULL,
    doc_type TEXT NOT NULL,
    section TEXT NOT NULL,
    page INTEGER NOT NULL,
    chunk_index INTEGER NOT NULL,
    related_process_ids BIGINT[] NOT NULL,
    content TEXT NOT NULL,
    metadata JSONB NOT NULL,
    embedding vector(384) NOT NULL,
    PRIMARY KEY (company_id, index_version, chunk_id),
    FOREIGN KEY (company_id, index_version) REFERENCES rag_indexes(company_id, index_version)
);
-- MVP는 정확 cosine 검색을 사용한다. 대규모화 전 ANN과 필터 recall을 별도 검증한다.
CREATE INDEX IF NOT EXISTS rag_chunks_scope ON rag_document_chunks(company_id, index_version, document_id);
```

- 업무 테이블 14개·FK 24개 + RAG 테이블 2개·FK 3개 = `ax` 전체 16개·FK 27개.
- `rag_indexes`는 회사·색인 버전별 모델·revision·코퍼스 해시·적재 건수를 기록한다. `rag_document_chunks`는 청크·메타데이터·384차원 임베딩과 다중 업무 연결을 저장한다.
- `company_id`와 `document_id`가 같은 회사인지 indexer가 적재 전 검증하고, 검색에서도 `documents`와 회사 ID를 함께 JOIN해 확인한다. RAG 계정에는 업무 테이블 쓰기 권한을 주지 않는다.
- 확장 설치는 DB 초기화 계정이 수행한다. 검색 계정은 RAG 테이블 SELECT 및 소속 확인용 `documents` 컬럼 SELECT만, 적재 계정은 이에 더해 RAG 테이블 INSERT/UPDATE/DELETE만 받는다. 계정 생성·GRANT는 배포 초기화에서 처리하며 비밀번호를 시드 SQL에 넣지 않는다.

### 시드 데이터 범위
| 데이터 | 수량 |
|---|---|
| 기업 | 1 (`company_id` 1) |
| 부서 | 3 (인사·기획·개발, `department_id` 101~103, 담당자 이메일·연락처 포함 → 마스킹 시연) |
| 업무 프로세스 | 9 (부서당 3, `process_id` 201~209) |
| 업무 지표 | 27 (업무별 최근 3개월 2026-07~09, 전부 `data_source = ASSUMED`) |
| IT 시스템 | 5~6 (`system_id` 301~, 예: HRIS, 그룹웨어, 이슈 트래커, 코드 저장소, 사내 위키, ERP. API 제공 여부 섞기) |
| 업무-시스템 연결 | 12~18 |
| 솔루션 카탈로그 | 업무별 1개 (`solution_id` 501~509), 선행 과제 1쌍 |
| 사용자 | 2 (`user_id` 601·602, 역할 없음, 시연 비밀번호 `ChangeMe123!` BCrypt) |
| 문서 | 8 (`document_id` 401~): 부서별 매뉴얼 3, 보안·데이터 정책 1, IT 시스템 명세 1, AI 활용 현황 1, 데이터 품질 점검표 1, 과거 프로젝트 보고서 1 |

업무 프로세스 예시 (이름·수치는 **예시**, 확정값은 데이터 패키지):

| 부서 | 업무 | 비고 |
|---|---|---|
| 인사 | 사내 규정 문의 응답 | RAG 후보 |
| 인사 | 신규 입사자 온보딩 안내 | |
| 인사 | 인사평가 등급 산정 | **제외 업무** 예시 — 사람에 대한 최종 판단을 AI가 하면 안 됨 |
| 기획 | 주간 업무 보고 취합 | |
| 기획 | 시장·경쟁사 동향 리포트 작성 | |
| 기획 | 회의록 작성·액션 아이템 정리 | |
| 개발 | 장애 티켓 분류·배정 | |
| 개발 | 코드 리뷰 보조 | `requires_approval = true` (사람 최종 검토) |
| 개발 | 기술·API 문서 작성 | |

ID 체계: 평가 701~, 로드맵 801~, 로드맵 항목 901~, 프로젝트 10001~.
문서 내용(절차·승인 규칙)은 DB 시드와 충돌하지 않게 작성한다.

---

## 6. 계산 규칙 (Spring Boot에만 구현)

설정 파일 (데이터 패키지 `config/`, Spring이 읽음): `ax_score_policy_v1.json`(AX점수·선정 규칙), `roi_policy_v1.json`(보조 지표), `assessment_criteria_v1.json`(성숙도).
**과제 선정은 AX점수로 하고, ROI는 화면 표시용 보조 지표다.**

### 공통 기초값 (업무별)
```
recent       = 업무의 최근 3개 완료 월 process_metrics
monthly_hours_m = processing_count_m × avg_processing_minutes_m / 60
annual_hours = Σ monthly_hours_m × 4                                  # 3개월 합 × 4 = 연환산
labor_cost   = Σ(monthly_hours_m × hourly_labor_cost_krw_m) / Σ monthly_hours_m   # 시간 가중 평균
api_ok       = 솔루션 requires_api = false  OR  업무 연결 시스템 중 api_available = true 가 하나 이상
data_confidence = 업무 지표 data_source 중 가장 낮은 등급 (MEASURED > SURVEY > ASSUMED)  # 표시만
```

### AX점수 (선정 기준)
```
saved_hours  = annual_hours × automation_rate_base × time_reduction_rate_base
Impact       = saved_hours / max(saved_hours of 모든 선정 가능 후보) × 100     # 0~100
Feasibility  = standardization_level × 60 + (api_ok ? 40 : 0)                  # 0~100
AX점수       = Impact × 0.6 + Feasibility × 0.4                                # 소수 첫째 자리 반올림
```
- 정규화 기준(`max`)은 Agent가 넘긴 후보가 아니라 **해당 기업의 선정 가능 후보 전체**다. 같은 데이터면 항상 같은 점수가 나온다.
- `data_confidence`는 점수에 넣지 않고 화면에 "가정 데이터 기반" 배지로 표시한다.
- `standardization_level < min_standardization_level`이면 `warnings`에 `LOW_STANDARDIZATION`을 넣는다 (점수 변화 없음).

### 선정 가능 후보·제외·주의
- 후보 = `ai_solution_catalog`에서 `target_process_id`가 해당 기업 업무인 것.
- **제외**: `ax_score_policy_v1.json`의 `exclusions`에 있는 업무 (사람에 대한 최종 판단·평가를 AI가 하게 되는 업무). 결과에 `excluded: [{processId, reason}]`로 표시.
- **유지 + 표시**: `requires_approval = true` 업무는 감점·제외하지 않고 `humanReviewRequired: true`로 표시, 로드맵에 사람 검토 단계를 넣는다.

### 포트폴리오 (`POST /internal/ax/portfolio`)
- 크기 `max_items`(기본 3) 조합을 전수 탐색
- 제약: Σ `first_year_tco` ≤ `budget_krw` / 같은 `process_id` 중복 금지 / `depends_on_solution_id`가 있는 후보는 선행 솔루션이 같은 조합에 있어야 함
- 목표: **Σ AX점수 최대**. 동점이면 Σ 3년 순편익이 큰 것, 그래도 같으면 총비용이 작은 것
- 조건을 만족하는 조합이 없으면 `insufficient: true` → Agent가 `discover`로 재탐색

### 보조 지표 (`POST /internal/ax/roi`, 시나리오 s ∈ {low, base, high})
```
saved_hours_s    = annual_hours × automation_rate_s × time_reduction_rate_s
annual_saving_s  = saved_hours_s × labor_cost                    # 인력 시간 환산 가치, 확정 현금 절감 아님
annual_run_cost  = monthly_run_cost_krw × 12
first_year_tco   = base_build_cost_krw + annual_run_cost
roi_pct_s        = (annual_saving_s − first_year_tco) / first_year_tco × 100
payback_months_s = 12 × base_build_cost_krw / (annual_saving_s − annual_run_cost)   # 분모 ≤ 0 이면 null
three_year_net_s = 3 × annual_saving_s − base_build_cost_krw − 36 × monthly_run_cost_krw
```
- 1년 ROI는 구축비 때문에 음수가 흔하다. 화면은 AX점수를 주 지표로, 회수 기간·3년 순편익을 먼저, 1년 ROI를 마지막에 보여준다.
- 금액은 계산을 끝까지 `BigDecimal`로 하고 마지막에 원 단위 반올림한다.

### 성숙도 (`assessment_criteria_v1.json`, 버전 관리)
| 영역 | 가중치 |
|---|---|
| 데이터 준비도 | 0.25 |
| IT 인프라 | 0.20 |
| 업무 자동화 | 0.20 |
| AI 활용 역량 | 0.20 |
| AI 거버넌스 | 0.15 |
- LLM은 기준표에 따라 영역별 0~100 점수와 **근거(문서·데이터)**를 낸다. 근거 없는 영역은 점수를 내지 않고 `insufficient_data`에 넣는다.
- `total_score`(가중합)는 코드로 계산한다.
- 성숙도(기업 단위)와 AX점수(과제 단위)는 별개다. 성숙도는 과제 선정에 쓰지 않는다.

### 출처 표기
평가 관점(효과·실현 가능성·데이터 신뢰도)은 컨설팅사 AI 도입 평가 관점을 참고했고, **수식과 가중치는 MVP용 자체 설계**다. 수식에 특정 회사 이름을 붙이지 않는다.

---

## 7. Spring 내부 API (`/internal/**`, `X-Internal-Token` 필수)

| Method | Path | 용도 | 호출자 |
|---|---|---|---|
| GET | `/internal/companies/{companyId}` | 기업 + 부서 목록 | business-mcp |
| GET | `/internal/companies/{companyId}/processes?departmentId=` | 업무 프로세스 | business-mcp |
| GET | `/internal/companies/{companyId}/metrics?departmentId=` | 업무별 최근 3개월 지표 | business-mcp |
| GET | `/internal/companies/{companyId}/systems` | IT 시스템 + 업무 연결 | business-mcp |
| GET | `/internal/companies/{companyId}/budget` | AX 예산 | business-mcp |
| GET | `/internal/solutions` | 솔루션 카탈로그 | business-mcp |
| POST | `/internal/ax/roi` | 후보 1개의 AX점수 + 보조 지표(3개 시나리오) | business-mcp |
| POST | `/internal/ax/portfolio` | 예산 내 AX점수 합 최대 조합 | business-mcp |
| POST | `/internal/assessments` | 성숙도 저장 | business-mcp |
| POST | `/internal/roadmaps` | 로드맵 + 항목 생성 | business-mcp |
| POST | `/internal/projects` | 프로젝트 등록 | business-mcp |
| PATCH | `/internal/projects/{projectId}/status` | 프로젝트 상태 변경 | business-mcp |
| POST | `/internal/tasks/{taskId}/events` | 진행 이벤트 수신 → SSE 중계 | agent |
| PATCH | `/internal/tasks/{taskId}` | 상태·결과·trace_url 갱신 | agent |

`/internal/ax/roi` 요청 `{ "processId": 201, "solutionId": 501 }` → 응답:
```json
{
  "processId": 201, "solutionId": 501, "dependsOnSolutionId": null,
  "axScore": 0.0, "impactScore": 0.0, "feasibilityScore": 0.0,
  "savedHoursBase": 0.0, "apiOk": true, "humanReviewRequired": false,
  "dataConfidence": "ASSUMED", "warnings": [],
  "firstYearTcoKrw": 0,
  "scenarios": {
    "low":  { "annualSavingKrw": 0, "roiPct": 0, "paybackMonths": 0, "threeYearNetKrw": 0 },
    "base": { "annualSavingKrw": 0, "roiPct": 0, "paybackMonths": 0, "threeYearNetKrw": 0 },
    "high": { "annualSavingKrw": 0, "roiPct": 0, "paybackMonths": 0, "threeYearNetKrw": 0 }
  }
}
```
`/internal/ax/portfolio` 요청 `{ "companyId": 1, "candidates": [{ "processId": 201, "solutionId": 501 }], "maxItems": 3 }` → 응답:
```json
{
  "insufficient": false, "budgetKrw": 300000000,
  "selected": [ /* /internal/ax/roi 응답과 같은 형식 */ ],
  "totalAxScore": 0, "totalFirstYearTcoKrw": 0, "remainingBudgetKrw": 0,
  "evaluatedCombinations": 0, "validCombinations": 0,
  "excluded": [{ "processId": 203, "reason": "사람에 대한 최종 평가를 AI가 결정" }]
}
```
(숫자는 형식 예시다. 실제 값은 데이터 패키지 `eval/demo_expected_portfolio.json`이 정답이다.)

오류 응답 형식 (공통):
```json
{ "code": "NOT_FOUND", "message": "부서 99는 없다", "hint": { "validIds": [1, 2, 3, 4] } }
```

---

## 8. 공개 API · SSE 이벤트 (React ↔ Spring)

| Method | Path | 설명 | 응답 |
|---|---|---|---|
| POST | `/api/auth/signup` | 회원가입 `{ email, password, name }` | **201** `{ userId }` |
| POST | `/api/auth/login` | 로그인 | `{ accessToken, user: {userId, name, companyId} }` |
| POST | `/api/ai/tasks` | 작업 생성 `{ requestText }` | **202** `{ taskId }` |
| GET | `/api/ai/tasks/{taskId}` | 상태·결과 (**작업 요청자 본인만**) | `{ taskId, status, result, traceUrl }` |
| GET | `/api/ai/tasks/{taskId}/stream` | 진행 이벤트 (**작업 요청자 본인만**) | `text/event-stream` |
| POST | `/api/ai/tasks/{taskId}/approval` | 승인·거절 `{ decision: "APPROVE"\|"REJECT", reason }` (**작업 요청자 본인만**) | 202 |
| GET | `/api/ai/tasks?mine=true` | 내 작업 이력 | 목록 |
| GET | `/api/docs/{documentId}` | 근거 원문 (Spring이 rag-mcp Resource 중계 또는 파일 서빙) | 문서 |

### 인증
- 회원가입: MVP는 기업이 1곳이므로 `companyId`는 서버가 기본 기업으로 지정한다. 비밀번호는 8자 이상·영문과 숫자 포함(서버도 검증), BCrypt로 저장. 이메일 중복이면 **409** `{ "code": "DUPLICATE_EMAIL", ... }`, 입력값 오류는 **400** `{ "code": "VALIDATION_ERROR", ... }` (§7 공통 오류 형식). 가입 후 자동 로그인하지 않는다(프론트가 로그인 화면으로 이동).
- `/api/auth/signup`, `/api/auth/login`을 뺀 모든 `/api/**`는 `Authorization: Bearer {accessToken}` 헤더로 인증한다. **SSE(`/stream`)도 같다.**
- 토큰을 URL 쿼리(`?token=`)에 넣지 않는다 (접속 로그·브라우저 기록에 남음). 프론트는 `EventSource` 대신 `fetch` 스트리밍으로 SSE를 읽어 헤더를 보낸다.
- 작업 조회·스트림·승인은 `ai_tasks.user_id`가 토큰의 사용자와 같을 때만 허용한다. 다르면 403.

### SSE 연결 규칙
- 서버는 15초마다 heartbeat 주석(`: ping`)을 보낸다. 프론트는 45초간 아무것도 못 받으면 연결이 죽었다고 보고 재연결한다.
- 이벤트에 `id:`를 붙이면 재연결 시 `Last-Event-ID` 헤더로 돌려받는다 (선택). 프론트는 재연결 직후 `GET /api/ai/tasks/{taskId}`로 상태를 다시 맞춘다.
- `DONE`·`FAILED` 이후 서버는 스트림을 닫는다.
- Spring Security 7: SSE 비동기 디스패치가 막히지 않게 `DispatcherType.ASYNC`, `ERROR`를 허용한다.
- nginx 경유 시 `proxy_buffering off` 또는 응답 헤더 `X-Accel-Buffering: no`.

### 이벤트 형식 (SSE `data:` 한 줄 JSON)
```json
{ "type": "TOOL_START", "taskId": "uuid", "ts": "2026-10-20T10:00:00+09:00", "node": "collect", "data": { "tool": "business_get_business_processes", "label": "업무 프로세스 조회 중" } }
```

| type | 언제 | data | 화면 |
|---|---|---|---|
| `TOKEN` | 답변 생성 중 | `{ text }` | 답변 영역에 이어 붙임 |
| `TOOL_START` / `TOOL_END` | 도구 실행 전후 | `{ tool, label, ok }` | 진행 표시 |
| `APPROVAL_REQUIRED` | approval Node에서 멈춤 | `{ roadmap, items[], totalAllocatedKrw, budgetKrw }` (items에 `axScore`, `impactScore`, `feasibilityScore`, 보조 지표, `humanReviewRequired`) | 승인 카드 |
| `DONE` | 완료 | `{ result }` | 결과 표시, 스트림 종료 |
| `FAILED` | 실패 | `{ message, traceUrl }` | 오류 표시, 스트림 종료 |

### 작업 상태 (`ai_tasks.status`)
`QUEUED → RUNNING → WAITING_APPROVAL → RUNNING → DONE`
거절 시 `REJECTED`, 실패 시 `FAILED`.

---

## 9. MCP 도구 명세

공통 규칙
- docstring에 **무엇을 받아 무엇을 돌려주는지, 단위, 인자를 어디서 얻는지** 적는다 (모델은 docstring만 보고 도구를 고른다).
- 실패는 `ToolError`로, 메시지에 **재시도에 필요한 정보**(유효 ID 목록 등)를 넣는다.
- 변경 도구는 `annotations={"destructiveHint": True}` 표시 → Agent가 승인 전 interrupt.
- Agent는 두 서버를 `mcpServers` 설정으로 연결하므로 도구 이름 앞에 `business_`, `rag_` 접두어가 붙는다.

### business-mcp (:9101)

| 도구 | 인자 | 반환 | 종류 |
|---|---|---|---|
| `get_company_profile` | `company_id: int` | 기업 정보, 부서 목록(`department_id`, 이름) | 조회 |
| `get_business_processes` | `company_id: int, department_id: int \| None` | 업무 목록 (절차, 표준화 수준, 승인 필요 여부, 예외 규칙) | 조회 |
| `get_operational_metrics` | `company_id: int, department_id: int \| None` | 업무별 월평균 처리량·건당 분·오류율·시간당 인건비·`data_source` | 조회 |
| `get_system_inventory` | `company_id: int` | 시스템 목록(API 제공·접근 수준) + 업무 연결 | 조회 |
| `get_project_budget` | `company_id: int` | 연간 AX 예산(원) | 조회 |
| `get_solution_catalog` | 없음 | 솔루션별 대상 업무(`target_process_id`), 선행 과제, 비용·자동화율·적용 조건 | 조회 |
| `calculate_ax_roi` | `process_id: int, solution_id: int` | AX점수·Impact·Feasibility + 보조 지표(3개 시나리오 ROI·회수 기간·3년 순편익) (§7 응답 형식) | 계산 |
| `optimize_ax_portfolio` | `company_id: int, candidates: list[{process_id, solution_id}], max_items: int = 3` | AX점수 합 최대 조합, 총비용, 제외 업무, `insufficient` | 계산 |
| `save_assessment` | `task_id: str, scores: {...}, criteria_version: str, evidence: list` | `assessment_id` | 저장 (승인 불필요) |
| `create_ax_roadmap` | `task_id: str, company_id: int, assessment_id: int, roadmap_name: str, items: list[RoadmapItem]` | `roadmap_id`, `item_id` 목록 | **변경 · 승인 필요** |
| `create_ax_project` | `item_id: int, owner_department_id: int, project_name: str` | `project_id` | **변경 · 승인 필요** |
| `update_project_status` | `project_id: int, status: str` | 변경 결과 | **변경 · 승인 필요** |

`RoadmapItem` = `roadmap_items` 컬럼과 동일 (`process_id, solution_id, item_name, priority_order, phase, start_month, duration_months, allocated_budget_krw, ax_score, impact_score, feasibility_score, expected_annual_saving_krw, roi_pct, payback_months, three_year_net_value_krw, rationale, evidence`). 점수·금액은 `optimize_ax_portfolio` 결과 값을 그대로 넣고, Spring은 저장 시 재계산 값과 다르면 400을 돌려준다.

### rag-mcp (:9102)

| 종류 | 이름 | 설명 |
|---|---|---|
| Tool | `search_docs(query: str, doc_type: str \| None, process_id: int \| None, top_k: int = 5)` | pgvector cosine 거리 검색. 반환: `[{document_id, title, doc_type, section, page, content, score}]` |
| Tool | `get_assessment_evidence()` | 활성 회사·색인 버전의 정책·시스템·AI 현황·데이터 품질·프로젝트 보고서 전체 섹션 조회. 임베딩 호출 없음. 200개 초과 시 부분 반환 없이 오류 |
| Resource | `docs://{document_id}` | 문서 원문 (근거 패널용) — **Capstone 필수 조건** |

Agent는 성숙도 평가용 공통 근거와 업무별 의미 검색 결과를 분리한다. 성숙도는 제공된 근거 ID를 선택하고 코드가 원본 문서·절로 복원한다. 후보 역시 카탈로그 ID로 선택하고 업무·솔루션 ID는 코드에서 복원한다. Spring 저장 DTO와 정량 계산 책임은 유지한다. LLM 입력은 완전한 JSON으로 구성하며 초과 시 필요한 근거를 몰래 자르지 않고 명시적으로 실패한다.

pgvector 청크 metadata(JSONB): `document_id, title, doc_type, process_id, section, page, chunk_index, version, embedding_model, company_id, access_level`.

- 적재 원본: `rag/pgvector_import.jsonl`. 각 행은 `{id, document, metadata}`이며, 벡터는 파일에 가짜 값으로 넣지 않고 indexer가 원문에서 생성한다. `rag/doc_mapping.json`의 각 문서에 `related_process_ids` 배열을 둔다. 부서 매뉴얼처럼 여러 업무를 다루면 모두 넣고, 공통 문서는 빈 배열로 표시한다. `documents.process_id`·metadata의 `process_id`는 대표 업무 또는 공통 문서의 `null`이며, 검색 필터는 `related_process_ids`를 사용한다.
- 모델 기본값: `text-embedding-3-small`, revision `openai-dim384-v1`, 차원 **384**. OpenAI Embeddings API에 dimensions=384를 지정하며 적재와 질의에 같은 모델·차원을 사용한다. revision은 OpenAI 모델의 고정 스냅샷이 아니라 내부 구성 식별자다. 모델 변경 시 재색인이 필요하고, 차원 변경 시 벡터 컬럼도 변경한다.
- `rag_document_chunks.embedding <=> query_vector`로 정확 검색한다. `score`는 **cosine 거리(작을수록 유사)**이며 유사도나 AX점수가 아니다. `company_id`·`index_version`을 반드시 제한하고 `doc_type`·`related_process_ids` 필터를 적용한다. 공통 문서(빈 배열)는 업무 필터에서도 검색한다. MVP에서는 ANN 인덱스를 만들지 않는다.
- indexer는 `documents`의 문서 ID·회사 소속과 파일 metadata를 검증하고, 동일 회사·버전의 색인을 **단일 트랜잭션으로 교체**한다. `rag_indexes`에 모델·revision·코퍼스 해시·chunk 수를 기록한다. rag-mcp는 활성 버전·모델·revision·코퍼스 해시가 다르거나 색인이 없으면 재색인이 필요하다는 오류를 반환한다.
- rag-mcp는 검색 전용 DB 계정, indexer는 색인 쓰기 전용 DB 계정을 사용한다. 두 계정은 업무 테이블을 변경하지 않는다. 문서 소속 확인에는 `documents`의 필요한 컬럼만 조회한다. `access_level`은 기존 계약대로 민감도 표시용이며 개인정보 마스킹은 유지한다.

---

## 10. Agent 설계 (LangGraph)

### State
```python
class AXState(TypedDict):
    task_id: str                 # = thread_id
    company_id: int
    user_id: int                 # 작업 요청자 (승인 가능한 유일한 사용자)
    request: str
    messages: Annotated[list, add_messages]
    company: dict
    processes: list[dict]
    metrics: list[dict]
    systems: list[dict]
    evidence: list[dict]         # {document_id, title, section, content}
    maturity: dict               # 영역별 점수·근거, total_score, assessment_id
    insufficient_data: list[str]
    candidates: list[dict]       # {process_id, solution_id, reason}
    roi: list[dict]              # calculate_ax_roi 결과 (AX점수 + 보조 지표)
    portfolio: dict              # optimize_ax_portfolio 결과
    roadmap: dict                # 로드맵 초안 (항목·근거)
    approval: dict | None        # {decision, user_id, reason}
    retry_count: int             # discover 재시도 횟수
    errors: list[str]
```

### Graph

| Node | 하는 일 | 다음 |
|---|---|---|
| `collect` | **LLM이 business-mcp 조회 도구를 스스로 골라 호출** (ReAct, 최대 8턴) | 회사 ID 오류 → `FAILED` / 정상 → `retrieve` |
| `retrieve` | rag-mcp `search_docs`로 매뉴얼·시스템 명세·정책·AI 현황·데이터 품질 문서 검색 | 근거 0건 → 검색어 바꿔 1회 재시도 → `assess` |
| `assess` | 기준표로 5개 영역 점수 + 근거, `save_assessment` | `discover` |
| `discover` | 카탈로그의 `target_process_id`로 업무별 후보 생성, 제외 업무·이전 실패 후보 제외, 후보마다 근거 문서 연결 | `evaluate` |
| `evaluate` | 후보별 `calculate_ax_roi` → `optimize_ax_portfolio` | `insufficient` & `retry_count < 2` → `discover` / 아니면 `roadmap` |
| `roadmap` | 우선순위 = AX점수 순, 선행 과제 먼저 배치. PoC 성공 기준, 과제별 근거 문서. **선정 이유는 AX점수(Impact·Feasibility)로 설명**하고 ROI는 보조로 언급, 사람 검토 단계 표시 | `approval` |
| `approval` | `interrupt()`로 멈춤, `APPROVAL_REQUIRED` 이벤트, 상태는 checkpointer에 저장 | 승인 → `register` / 거절 → `END`(REJECTED) |
| `register` | `create_ax_roadmap` → 항목별 `create_ax_project` | `END`(DONE) |

- 재개: Spring이 Agent `POST /tasks/{taskId}/resume {decision, userId, reason}` 호출 → 같은 `thread_id`로 `Command(resume=...)`.
- checkpointer: `PostgresSaver` (DB `agent`).

### Agent 서버 API (내부)
| Method | Path | Body |
|---|---|---|
| POST | `/tasks/{taskId}/run` | `{ companyId, userId, requestText }` → 즉시 202, 백그라운드 실행 |
| POST | `/tasks/{taskId}/resume` | `{ decision, userId, reason }` → 202 |
| GET | `/health` | - |

---

## 11. Harness 구현 기준 (평가 20점)

| 구성 요소 | 위치 | 기준 |
|---|---|---|
| Instructions | `agent/prompts/*.md` | Node별 프롬프트 분리 (역할, 도구 규칙, 금지 사항, 출력 형식) |
| Tools | MCP Client → LangChain 도구 변환부 | 도구 결과 2,000자 자르기, 오류는 ToolMessage로 모델에 전달 |
| Agent Loop | StateGraph | 최대 8턴, 작업 120초, 같은 도구 3회 |
| Context | 메시지 정리·RAG 주입 | top-k chunk만, 지표는 요약본만 주입 |
| State·Memory | checkpointer | `thread_id = taskId`, 승인 대기 후 재개 |
| Guardrails | approval Node, 도구 결과 후처리 | destructive 도구 interrupt, 이메일·전화번호 마스킹, 승인·조회는 작업 요청자 본인만 |
| Recovery | LLM 호출·MCP 호출 | 429/503 2회 재시도 → 대체 모델(`LLM_FALLBACK_MODEL`) → FAILED |
| Observability | LangSmith | 작업마다 trace, `ai_tasks.trace_url` 저장 |

---

## 12. 저장소 구조

```
ax-navigator/
├── docker-compose.yml
├── docker-compose.override.yml   # 개발용: 내부 서비스 포트 노출
├── .env.example
├── contracts/                    # 이 문서, OpenAPI, 이벤트 스키마 (주인만 수정)
├── db/
│   ├── init/                     # 00_databases.sql(ax, agent 생성), 01_schema.sql
│   └── seed/                     # 02_seed.sql
├── docs-corpus/                  # 가상 사내 문서 원본 (.md)
├── backend/                      # Spring Boot
├── agent/
│   ├── app/                      # FastAPI, graph, nodes, harness
│   ├── prompts/
│   └── config/maturity_criteria.yaml
├── business-mcp/
├── rag-mcp/                      # server.py, index.py
├── frontend/                     # React 19 + Vite + TypeScript + Tailwind CSS v4
└── docs/                         # 아키텍처, ISO 25010 매핑, 발표자료
```

### 환경 변수 (`.env`)
```
OPENAI_API_KEY=
LLM_MODEL=
LLM_FALLBACK_MODEL=
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_REVISION=openai-dim384-v1
RAG_DATABASE_URL=postgresql://<검색계정>:<비밀번호>@postgres:5432/ax
RAG_INDEX_DATABASE_URL=postgresql://<색인계정>:<비밀번호>@postgres:5432/ax
RAG_INDEX_VERSION=ax-v3-openai-small-384-v1
RAG_COMPANY_ID=1
CORPUS_DIR=/data/rag
LANGSMITH_API_KEY=
LANGSMITH_PROJECT=ax-navigator
JWT_SECRET=
INTERNAL_TOKEN=
POSTGRES_USER=ax
POSTGRES_PASSWORD=
CORS_ORIGIN=http://localhost
```
서비스 간 주소는 compose 서비스 이름 사용: `http://backend:8080/internal`, `http://business-mcp:9101/mcp`, `http://rag-mcp:9102/mcp`, `http://agent:8000`. pgvector는 HTTP 서비스가 아니라 `postgres:5432/ax`에 PostgreSQL 드라이버로 접속한다. `RAG_DATABASE_URL`은 rag-mcp에만, `RAG_INDEX_DATABASE_URL`은 indexer에만 주입하고 실제 비밀번호는 `.env`에서 제공한다.

---

## 13. 평가 체크리스트

- [ ] 변경 도구 destructiveHint + 승인 전 interrupt
- [ ] ToolError 메시지에 재시도 정보
- [ ] rag-mcp Resource 1개 이상, 근거 패널에서 원문 표시
- [ ] `thread_id = taskId`로 저장·재개
- [ ] 진행 이벤트 SSE 표시 (TOKEN, TOOL_START/END, APPROVAL_REQUIRED, DONE/FAILED)
- [ ] 모델이 도구를 스스로 선택하고 근거와 함께 답함
- [ ] 선정 과제·AX점수가 `eval/demo_expected_portfolio.json`과 일치 (Spring 단위 테스트)
- [ ] 화면: AX점수 주 지표, 보조 지표(회수 기간·3년 순편익·1년 ROI), "가정 데이터 기반" 배지, 제외 업무 사유 표시
- [ ] Graph에 분기(데이터 오류·승인)와 반복(재탐색) 존재
- [ ] Harness 8요소 각각 코드 위치 설명 가능
- [ ] 로그인 + 본인 작업만 조회·승인
- [ ] 장애 시연: MCP 서버 중지 → 재시도 후 FAILED + trace / 없는 부서 질의 → ToolError → 모델 재호출
- [ ] LangSmith trace 화면
- [ ] 아키텍처 문서: 구성도, 배포도, ISO/IEC 25010 품질 특성 ↔ 아키텍처 결정 매핑

---

## 14. 시작 프롬프트 (복사해서 사용)

```
첨부한 AX_NAVIGATOR_CONTEXT.md가 우리 팀 공통 기준 문서다.
§0 작업 규칙을 지키고, 계약(DB·API·MCP 도구·이벤트·State)은 바꾸지 않는다.
이번에 내가 작업할 범위는 [작업 범위]다. 다른 서비스는 계약대로 mock을 만들어 대체한다.
먼저 구현 순서를 제안하고, 그다음 첫 번째 단계 코드를 작성해 줘.
```
