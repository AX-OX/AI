# AX Navigator AI — Role-free MVP 데이터셋

**사용자 역할 없이 요청자 본인이 승인하도록 수정한 버전**. 첨부된 **PostgreSQL 16 DDL(총 14개 CREATE TABLE)**과 업로드한 기존 `ax_navigator.sqlite`를 기준으로 준비한 교육용 가상 데이터셋. 이 패키지는 실제 기업 자료를 포함하지 않습니다.

## 최종 스키마: 14개 테이블 (DDL과 일치)

- **Input 7**: `companies`, `departments`, `business_processes`, `process_metrics`, `it_systems`, `process_systems`, `documents`
- **ROI 기준 1**: `ai_solution_catalog` (가정치 고정, LLM 임의 수치 생성 금지)
- **플랫폼 2**: `users`, `ai_tasks`
- **Output 4**: `ax_assessments`, `ax_roadmaps`, `roadmap_items`, `ax_projects`
- **PostgreSQL에서 제외**: `document_chunks`는 `rag/chroma_import.jsonl`에 저장, 벡터 임베딩은 아직 생성되지 않음
- **JSONB로 관리**: `ax_opportunities`, `roi_scenarios` 분석 결과는 `ai_tasks.result`에 스냅샷 기록
- **별도 관리**: LangGraph Checkpointer DB (`agent`)

첨부 문구에는 15개라고 표기되어 있으나 실제 CREATE TABLE 문은 **14개**이므로 의도적으로 14개를 구현함.

## 데이터 수량 (Agent 실행 이전 초기 입력 DB)

| 테이블 | 건수 |
|---|---:|
| companies | 1 |
| departments | 4 |
| business_processes | 12 (부서당 3) |
| process_metrics | 36 (2026년 7~9월, 전부 ASSUMED) |
| it_systems | 6 |
| process_systems | 22 |
| documents | 10 |
| ai_solution_catalog | 11 |
| users | 2 (역할 구분 없는 가상 사용자) |
| ai_tasks 및 Output 4개 테이블 | 0 |
| Chroma 적재용 문서 chunk | 54 |

- 회사 직원 수: 200명, 연간 AX 예산: 300,000,000 KRW.
- 4개 부서의 업무 세부 절차 12개를 업무별로 구체화했으며, **업무 DB 처리절차 및 RAG 매뉴얼 4개** 내용을 맞췄음.
- 시스템·문서·업무는 식별자 기반 연결. 문서 chunk의 `document_id`, `access_level`, `process_id` 등 메타데이터 포함.
- 모든 업무 운영지표는 **실측이 아닌 가상 합성값**: `process_metrics.data_source = ASSUMED`.
- 원본 31개 테이블과 20개 업무 중 **12개 업무/3개월**만 MVP 분석범위로 추림. 나머지 개별 CRM·ERP 이벤트를 원본 DB와 동일하게 보존한 것은 아님.

## 가장 중요한 파일

- `ax_navigator_input.sqlite` : Agent 실행 전 입력 + 카탈로그 + 데모 사용자. Output/ai_tasks = 0.
- `ax_navigator_demo_approved.sqlite` : 승인 완료 **테스트 전용** 상태, 요청자 본인이 승인한 로드맵 1건과 프로젝트 3건 포함.
- `sql/00_schema_postgres16.sql` : 제공 DDL에 따라 PostgreSQL 16용으로 수정한 schema. BIGINT GENERATED ALWAYS AS IDENTITY 사용.
- `sql/01_seed_input_postgres.sql` : 초기 입력/카탈로그/사용자 데이터 시드, 명시적 PK는 `OVERRIDING SYSTEM VALUE`로 유지.
- `csv/*.csv` : 14개 테이블, DB 컬럼과 동일한 헤더. Output CSV는 초기 상태라 헤더만 존재.
- `rag/docs/*.md` : 회사 내부 합성 문서 10개. `rag/chroma_import.jsonl` : Chroma용 텍스트와 메타데이터 **54개**, 임베딩 없음.
- `eval/reference_12_processes.json` : 12개 업무 후보 추천 검증용 가상 전문가 레퍼런스.
- `config/assessment_criteria_v1.json` / `config/roi_policy_v1.json` : AX 점수와 ROI 계산 기준.
- `fixtures/02_demo_waiting_approval.sql` / `fixtures/03_demo_after_requester_approval.sql` : **테스트 시나리오 전용** 데이터.
- `erd/*.dbml`, `erd/*.mmd`, `erd/*.png` : 14개 테이블 ERD 및 수정 가능한 설계.
- `migration/legacy_to_v2_mapping.csv` : 기존 구조에서 최종 MVP로 매핑한 방식.
- `examples/validate_final.py` : 무결성/실행 데이터 검증.

## PostgreSQL 16 실행 순서

```bash
export DATABASE_URL='postgresql://user:password@localhost:5432/ax'
./examples/run_postgres.sh

# 선택 사항: 가상의 AI 실행 결과가 있는 데모
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f fixtures/02_demo_waiting_approval.sql

# 요청자 본인 승인을 시뮬레이션할 때만 실행 (운영 서비스에서 그대로 호출 금지)
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f fixtures/03_demo_after_requester_approval.sql
```

로컬 미리보기 검증: `python examples/validate_final.py`.
Chroma 적재: `python examples/chroma_ingest.py` (chromadb/sentence-transformers 사전 설치, 임베딩 모델 사용 필요).

## 아키텍처 / 보안 원칙

- **Business MCP** → Spring `/internal/**` → PostgreSQL. Agent가 업무 DB에 직접 쓰지 않음.
- **RAG MCP** → Chroma. 역할 구분 기반 검색 필터 없이 `company_id` 범위와 개인정보 마스킹을 적용. `access_level`은 문서 민감도 표기용으로 유지.
- 승인 전에는 변경 도구 실행 금지. `ax_projects` 생성은 Spring이 현재 인증 사용자 ID와 `ai_tasks.user_id` 및 `ax_roadmaps.approved_by`의 일치, `APPROVED` 상태를 검증한 후 실행.
- `ai_tasks.result`는 생성 결과의 JSONB 스냅샷. 로드맵과 항목은 승인 후 business-mcp 도구 경유로 등록.
- ROI의 비용과 자동화 가정은 `ai_solution_catalog`에 명시되고, 추정 인건비 절감은 **현금 절감 확정값이 아님**.
- 가상 로그인 계정은 테스트용 BCrypt 해시만 포함. 실제 운영 시 계정 및 자격정보 교체 필요.
- PostgreSQL은 **이 환경에서 직접 실행하지 않았으며**, SQLite 무결성과 생성 시드 일치성을 검증함.

## 주의할 설계상의 선택

- `documents.process_id`는 단일 FK라 4개 부서 통합 매뉴얼의 모든 연관 업무를 DB에서 직접 표현하지 못함. Chroma 메타데이터/문서 내용에 3개 업무를 명시했고, 다대다 연결이 필요하면 다음 버전에서 `document_processes` 테이블을 권장.
- 로드맵 항목과 프로젝트는 승인된 데모에서만 생성됨. 데모 SQL은 실제 API 인증·요청자 일치 검증을 구현하지 않음.
- 문서의 `page_number = 0`은 Markdown 원문이므로 가상값. PDF 실제 페이지 번호가 아님.

## 사용자 역할 제거 변경 사항

- 기존 `users.role`을 DB·DDL·CSV·ERD에서 제거함.
- 두 가상 사용자는 일반 계정으로 유지. 아이디 601/602의 테스트 이메일은 `analyst1@gaon.example`, `analyst2@gaon.example`.
- 승인 완료 데모의 **요청자 ID = 승인자 ID = 602**. `approved_by` 자체는 승인 이력 추적에 필요하므로 유지.
- `allowed_roles` 필드는 모든 Chroma chunk에서 제거하고 기존 RAG 접근 필터 예시·평가 질문 변경.
- `documents.access_level`은 민감도 표시용이므로 유지. 인증·기업 격리·민감정보 마스킹은 별도 적용 필요.
- 기존 설치 DB라면 `sql/02_migrate_remove_user_roles.sql`로 컬럼 삭제.
- 새 DB라면 `sql/00_schema_postgres16.sql` → `sql/01_seed_input_postgres.sql` 실행.
- 승인 시연: `fixtures/02_demo_waiting_approval.sql` → `fixtures/03_demo_after_requester_approval.sql`.
- 상세 변경 사항: `ROLE_FREE_CHANGELOG.md`.
