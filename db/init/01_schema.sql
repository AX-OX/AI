-- ============================================================
-- AX Navigator AI — MVP Schema (PostgreSQL 16)
-- 16 tables · 업무 DB(ax)
-- * 문서 chunk·임베딩은 같은 ax DB의 pgvector에 저장 (아래 RAG 확장 DDL에 별도 정의)
-- * LangGraph checkpointer는 별도 DB(agent)에 자동 생성
-- * ERD 도구 호환을 위해 PK는 BIGINT로 선언.
--   실제 생성 시 BIGINT → BIGINT GENERATED ALWAYS AS IDENTITY 로 변경
-- ============================================================


-- ------------------------------------------------------------
-- 1. 기업·업무 (Input)
-- ------------------------------------------------------------

CREATE TABLE companies (
    company_id          BIGINT GENERATED ALWAYS AS IDENTITY          NOT NULL,
    company_name        VARCHAR(100)    NOT NULL,   -- 기업명
    industry            VARCHAR(50),                -- 업종 (가입 후 문서 추출 확정 시 입력)
    employee_count      INTEGER,                    -- 직원 수 (가입 후 문서 추출 확정 시 입력)
    ax_budget_krw       BIGINT,                     -- 연간 AX 투자 예산(원). 계산에는 작업 예산(ai_tasks.budget_krw)을 쓴다
    created_at          TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_companies PRIMARY KEY (company_id)
);

CREATE TABLE departments (
    department_id       BIGINT GENERATED ALWAYS AS IDENTITY          NOT NULL,
    company_id          BIGINT          NOT NULL,
    department_name     VARCHAR(50)     NOT NULL,   -- 부서명
    manager_name        VARCHAR(50),                -- 담당자명
    manager_email       VARCHAR(100),               -- 담당자 이메일 (마스킹 대상)
    manager_phone       VARCHAR(20),                -- 담당자 연락처 (마스킹 대상)
    CONSTRAINT pk_departments PRIMARY KEY (department_id),
    CONSTRAINT fk_departments_company FOREIGN KEY (company_id) REFERENCES companies (company_id)
);

CREATE TABLE business_processes (
    process_id              BIGINT GENERATED ALWAYS AS IDENTITY          NOT NULL,
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
    metric_id               BIGINT GENERATED ALWAYS AS IDENTITY          NOT NULL,
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
    system_id           BIGINT GENERATED ALWAYS AS IDENTITY          NOT NULL,
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
    document_id         BIGINT GENERATED ALWAYS AS IDENTITY          NOT NULL,
    company_id          BIGINT          NOT NULL,
    process_id          BIGINT,                     -- 공통 문서면 NULL
    title               VARCHAR(200)    NOT NULL,   -- 문서명
    doc_type            VARCHAR(30)     NOT NULL,   -- MANUAL / POLICY / SYSTEM_SPEC / AI_STATUS / DATA_QUALITY / PROJECT_REPORT / UPLOADED
    file_uri            VARCHAR(500)    NOT NULL,   -- 원본 경로 (Resource docs://{document_id})
    access_level        VARCHAR(20)     NOT NULL,   -- PUBLIC / INTERNAL / CONFIDENTIAL (민감도 표시용, 검색 권한과 무관)
    version             VARCHAR(20)     NOT NULL DEFAULT 'v1',
    status              VARCHAR(20)     NOT NULL,   -- UPLOADED / INDEXED / FAILED
    content_type        VARCHAR(100),               -- 업로드 파일 MIME 타입
    file_size           BIGINT,                     -- 업로드 파일 크기(바이트)
    sha256              VARCHAR(64),                -- 업로드 파일 해시 (중복 업로드 확인)
    page_count          INTEGER,                    -- PDF 페이지 수
    created_at          TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_documents PRIMARY KEY (document_id),
    CONSTRAINT fk_documents_company FOREIGN KEY (company_id) REFERENCES companies (company_id),
    CONSTRAINT fk_documents_process FOREIGN KEY (process_id) REFERENCES business_processes (process_id)
);

CREATE TABLE document_pages (
    page_id             BIGINT GENERATED ALWAYS AS IDENTITY          NOT NULL,
    document_id         BIGINT          NOT NULL,
    page_no             INTEGER         NOT NULL,   -- 1부터 시작
    content             TEXT            NOT NULL,   -- AI가 추출한 페이지 텍스트 (마스킹 전 원문)
    CONSTRAINT pk_document_pages PRIMARY KEY (page_id),
    CONSTRAINT uq_document_pages UNIQUE (document_id, page_no),
    CONSTRAINT fk_pages_document FOREIGN KEY (document_id) REFERENCES documents (document_id)
);


-- ------------------------------------------------------------
-- 2. 기준 데이터 (ROI 가정값 — LLM이 만들지 않음)
-- ------------------------------------------------------------

CREATE TABLE ai_solution_catalog (
    solution_id                 BIGINT GENERATED ALWAYS AS IDENTITY          NOT NULL,
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
    user_id             BIGINT GENERATED ALWAYS AS IDENTITY          NOT NULL,
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
    budget_krw          BIGINT,                     -- 요청에서 추출한 예산(원). NULL이면 예산 제약 없이 계산
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

CREATE TABLE extraction_drafts (
    draft_id            BIGINT GENERATED ALWAYS AS IDENTITY          NOT NULL,
    company_id          BIGINT          NOT NULL,
    task_id             VARCHAR(36)     NOT NULL,
    document_ids        JSONB           NOT NULL,   -- 추출에 사용한 문서 ID 배열
    payload             JSONB           NOT NULL,   -- 부서·업무·지표·시스템 추출 결과 (항목별 출처 포함)
    status              VARCHAR(20)     NOT NULL,   -- DRAFT / CONFIRMED
    created_at          TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    confirmed_at        TIMESTAMP,
    CONSTRAINT pk_extraction_drafts PRIMARY KEY (draft_id),
    CONSTRAINT fk_drafts_company FOREIGN KEY (company_id) REFERENCES companies (company_id),
    CONSTRAINT fk_drafts_task    FOREIGN KEY (task_id)    REFERENCES ai_tasks (task_id)
);


-- ------------------------------------------------------------
-- 4. 분석·실행 (Output)
-- ------------------------------------------------------------

CREATE TABLE ax_assessments (
    assessment_id       BIGINT GENERATED ALWAYS AS IDENTITY          NOT NULL,
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
    roadmap_id          BIGINT GENERATED ALWAYS AS IDENTITY          NOT NULL,
    company_id          BIGINT          NOT NULL,
    task_id             VARCHAR(36)     NOT NULL,
    assessment_id       BIGINT,
    roadmap_name        VARCHAR(200)    NOT NULL,
    budget_limit_krw    BIGINT,                     -- 작업 예산 스냅샷. NULL이면 예산 제약 없음
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
    item_id                     BIGINT GENERATED ALWAYS AS IDENTITY          NOT NULL,
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
    project_id          BIGINT GENERATED ALWAYS AS IDENTITY          NOT NULL,
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
