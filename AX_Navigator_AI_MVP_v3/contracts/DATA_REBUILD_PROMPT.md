# 데이터 패키지 v3 재작성 프롬프트 (데이터 담당용)

## 사용법
1. AI에게 아래 두 파일을 첨부한다.
   - `AX_Navigator_AI_MVP_NoRole.zip` (기존 데이터 패키지)
   - `AX_NAVIGATOR_CONTEXT.md` (수정된 공통 기준 문서)
2. 아래 "프롬프트" 블록 전체를 복사해서 보낸다.
3. 결과 zip을 받으면 맨 아래 "받은 뒤 확인할 것"으로 검수한다.

---

## 프롬프트

```
너는 AX Navigator AI 팀의 데이터 담당 보조다.
첨부한 AX_Navigator_AI_MVP_NoRole.zip(기존 데이터 패키지)을 첨부한 AX_NAVIGATOR_CONTEXT.md(공통 기준 문서, 이하 "기준 문서")에 맞춰
"AX_Navigator_AI_MVP_v3" 패키지로 다시 만들어라.

# 0. 원칙
- 기준 문서의 §5 DDL, §6 계산 규칙, §7 응답 형식이 계약이다. 이름·컬럼·수식을 바꾸지 마라.
  계약을 바꿔야 할 이유가 있으면 바꾸지 말고 CHANGELOG의 "계약 변경 제안"에 적어라.
- 모든 데이터는 가상 합성값이다. 실제 기업·인물·연락처를 쓰지 마라. 이메일은 *.example 도메인만.
- 수치는 반드시 스크립트로 계산하고, 손으로 쓴 숫자를 결과 파일에 넣지 마라.
- 기존 패키지의 폴더 구조, 파일 이름 규칙, 품질 수준(무결성 검증, README, CHANGELOG)을 유지하라.

# 1. 바뀐 점 (기존 패키지 → v3)
1) 대상 부서: 영업·구매·인사·고객지원 4개 → 인사·기획·개발 3개 (부서당 업무 3개, 총 9개)
2) 과제 선정 기준: "3년 순편익 합 최대" → "AX점수 합 최대" (기준 문서 §6). ROI·회수 기간·3년 순편익은 보조 지표.
3) 업무 스키마 (기준 문서 §5, 14개 테이블, FK 24개):
   - ai_solution_catalog에 target_process_id(NOT NULL), depends_on_solution_id 추가
   - roadmap_items에 ax_score, impact_score, feasibility_score, three_year_net_value_krw 추가
   - documents.access_level, ax_roadmaps.approved_by 유지 (approved_by = 요청자 본인)
   - 역할(role) 없음 유지
4) 정책 파일 config/ax_score_policy_v1.json 신규
5) 문서 벡터 저장은 PostgreSQL 16 + pgvector 0.8.1. 동일 ax DB에 rag_indexes·rag_document_chunks 2개 테이블(FK 3개)을 별도 SQL로 추가한다. 전체 ax는 16개 테이블·FK 27개이며, 별도 벡터 DB 서버는 배포하지 않는다. agent checkpointer DB는 이 수에 포함하지 않는다.

# 2. 시드 데이터 설계
ID 체계와 수량은 기준 문서 §5 "시드 데이터 범위"를 따른다.
- company 1: 직원 200명 B2B 제조기업, AX 예산 300,000,000원. 기존 회사명·업종 유지 가능.
- departments 101 인사, 102 기획, 103 개발. 담당자 이름·이메일·연락처(가상) 포함 → 마스킹 시연용.
- business_processes 201~209 (부서당 3). 기준 문서의 업무 예시를 출발점으로 하되 더 그럴듯하게 다듬어도 된다.
  각 업무에 purpose, process_steps(JSONB 배열 4~6단계), standardization_level, requires_approval, exception_rules를 채운다.
- process_metrics 27건: 업무별 2026-07, 08, 09 월 단위. 전부 data_source = ASSUMED.
  월별 수치는 약간씩 변동시키고, hourly_labor_cost_krw는 부서·직무에 맞게.
- it_systems 301~ (5~6개): 예) HRIS, 그룹웨어, 이슈 트래커, 코드 저장소, 사내 위키, ERP. api_available을 섞어라.
- process_systems 12~18건.
- ai_solution_catalog 501~509: 업무별 1개 (target_process_id로 연결). solution_type은 RAG / AI_AGENT / PREDICTION / CLASSIFICATION / RPA 중 업무에 맞게.
  구축비·운영비·자동화율·시간 절감률은 업무 규모에 맞는 합리적 가정값.
- users 601, 602: 기존 패키지 그대로 (역할 없음, 비밀번호 ChangeMe123!의 기존 BCrypt 해시 재사용).
- documents 401~408: 부서별 매뉴얼 3(인사·기획·개발), 보안·데이터 정책 1, IT 시스템 명세 1, AI 활용 현황 1, 데이터 품질 점검표 1, 과거 프로젝트 보고서 1.
  rag/docs/{document_id}.md 원문을 새로 쓰고, 매뉴얼의 절차·승인 규칙이 DB의 process_steps·requires_approval·exception_rules와 일치하게 한다.
  rag/pgvector_import.jsonl은 섹션 단위로 chunk를 다시 만들고 각 행을 {id, document, metadata}로 저장하라. metadata는 기준 문서 §9의 목록(document_id, title, doc_type, process_id, section, page, chunk_index, version, embedding_model, company_id, access_level)을 따른다.
  rag/doc_mapping.json의 문서별 related_process_ids 배열로 업무 연결을 명시하라. 부서 매뉴얼은 관련 업무 3개를 모두 넣고 공통 문서는 []로 표시한다. process_id는 대표 업무 또는 공통 문서의 null이다.
  임베딩은 indexer에서 실제 모델로 생성하고, JSONL에 가짜 벡터를 넣지 마라. 모델은 text-embedding-3-small, 구성 식별자 openai-dim384-v1, API dimensions=384 및 vector(384)를 기준으로 한다. OPENAI_API_KEY가 필요하며 모델 파일을 다운로드하지 않는다.

# 3. 시연이 되도록 데이터에 반드시 들어가야 할 상황
아래 조건을 모두 만족하도록 수치를 조정하라. 조정 과정은 스크립트로 확인하라.
1) 제외 업무 1개: 인사 업무 중 하나가 "사람에 대한 최종 판단·평가를 AI가 하게 되는 업무"(예: 인사평가 등급 산정).
   ax_score_policy_v1.json의 exclusions에 process_id와 사유를 넣는다.
2) 선행 과제 1쌍: depends_on_solution_id가 있는 솔루션 1개. 같은 부서 업무끼리가 자연스럽다.
3) API 판정 차이: requires_api = false인 솔루션이 API 없는 시스템만 쓰는 업무에 붙은 경우 1개 이상 (api_ok가 true가 되는 예).
   반대로 requires_api = true인데 업무에 API 시스템이 없어 api_ok = false인 경우도 1개 이상.
4) 사람 검토 업무가 최종 선정 3개 안에 1개 이상 포함 (requires_approval = true → humanReviewRequired 표시 시연).
5) 예산이 실제 제약이어야 한다: AX점수 상위 3개를 그대로 담으면 3억을 넘거나 선행 과제 조건을 깨서,
   전수 조합 탐색 결과가 "점수 상위 3개 단순 선택"과 달라야 한다.
6) 정답이 하나여야 한다: 최적 조합의 AX점수 합이 2등 조합보다 0.5 이상 높게.
7) 선정된 3개는 모두 기준 시나리오 payback_months가 36개월 이하, three_year_net_value가 양수.
   (1년 ROI는 음수여도 된다.)
8) LOW_STANDARDIZATION 경고(standardization_level < min_standardization_level)가 나는 후보 1개 이상 (선정 안 돼도 됨).

# 4. 설정 파일
- config/ax_score_policy_v1.json (신규): 기준 문서 §6 그대로
  { "version", "weights": {"impact":0.6,"feasibility":0.4}, "impact": {"normalization":"max_saved_hours_of_eligible_candidates"},
    "feasibility": {"standardization_multiplier":60,"api_ok_points":40}, "rounding": 1,
    "portfolio": {"max_items":3,"objective":"max_sum_ax_score","tie_breakers":["max_sum_three_year_net","min_total_first_year_tco"],
                  "constraints":["budget","unique_process","dependency_in_same_portfolio"]},
    "exclusions": [{"process_id":..., "reason":"..."}],
    "data_confidence": "display_only" }
- config/roi_policy_v1.json: 기존 식 유지 + payback_months, three_year_net_value 식 추가, "role":"auxiliary_indicator" 표기
- config/assessment_criteria_v1.json: 그대로

# 5. 계산 스크립트와 정답 파일
- examples/compute_ax.py를 새로 작성: seed(CSV 또는 SQLite)를 읽어 기준 문서 §6을 그대로 구현. 정답 생성·검산 전용이며 Agent·MCP의 운영 요청 계산에 사용하지 않는다.
  출력: 후보별 annual_hours, labor_cost, saved_hours, impact, feasibility, ax_score, api_ok, warnings, 3개 시나리오 보조 지표,
        제외 목록, 유효 조합 수, 최적 조합, 2등 조합과의 점수 차.
- eval/demo_expected_portfolio.json: compute_ax.py 출력으로 생성.
  { budget_limit_krw, selected_solution_ids, selected_process_ids, total_ax_score, total_first_year_tco_krw, remaining_budget_krw,
    evaluated_combinations, valid_combinations, runner_up: {solution_ids, total_ax_score}, greedy_top3_by_score, excluded,
    per_candidate: [ /* 기준 문서 §7 /internal/ax/roi 응답 형식 (camelCase) */ ] }
  → 이 파일이 백엔드 단위 테스트 정답이 된다.
- eval/benchmark_queries.json: 새 부서·업무에 맞게 B-01~B-07을 다시 작성.
  유지할 행동 유형: 지표 조회+근거, 문서 근거 검색, 제외 업무 자동 판단 요청 거부(DENY_AUTONOMOUS_FINAL_DECISION),
  예산 내 3개 선정(정답 = demo_expected_portfolio), 승인 없이 등록 요청(REQUIRE_REQUESTER_APPROVAL),
  개인정보 마스킹+인용(MASK_PERSONAL_DATA_AND_CITE), 없는 데이터 계산 요청(INSUFFICIENT_DATA).
- eval/reference_9_processes.json: 업무 9개별 후보/제외 판단과 근거 문서 (가상 전문가 레이블 표시).

# 6. 시드 SQL·fixture
- sql/00_schema_postgres16.sql: 기준 문서 §5의 업무 DDL(14개 테이블)을 단일 BIGINT PK만 BIGINT GENERATED ALWAYS AS IDENTITY로 바꾼 것 (ai_tasks.task_id, FK, 복합 PK 제외).
- sql/03_pgvector.sql: 기준 문서 §5 RAG 확장 DDL을 그대로 작성. CREATE EXTENSION IF NOT EXISTS vector 및 rag_indexes·rag_document_chunks 2개 테이블을 생성한다. 업무 DDL과 분리하고 rag_document_chunks.embedding은 vector(384), metadata는 JSONB, related_process_ids는 BIGINT[]로 둔다.
  ai_solution_catalog의 자기참조 FK 때문에 INSERT 순서에 주의.
- sql/01_seed_input_postgres.sql: 명시 ID는 OVERRIDING SYSTEM VALUE, 마지막에 setval.
- fixtures/02_demo_waiting_approval.sql: ai_tasks 1건(user_id 602, WAITING_APPROVAL) + ax_assessments 1건.
  ai_tasks.result JSON에 assessment, candidates(per_candidate와 같은 형식), portfolio(선정·제외·runner_up)를 넣는다.
- fixtures/03_demo_after_requester_approval.sql: ax_roadmaps 1건(approved_by = 602, APPROVED) + roadmap_items 3건 + ax_projects 3건.
  roadmap_items의 점수·보조 지표는 compute_ax.py 값과 정확히 같게. priority_order는 선행 과제 먼저, 그다음 AX점수 순.
- 이전 패키지의 sql/02_migrate_remove_user_roles.sql은 v3에 필요 없으면 제거하고 CHANGELOG에 적어라.
- examples/pgvector_ingest.py: RAG_INDEX_DATABASE_URL로 연결하고 rag/pgvector_import.jsonl·doc_mapping.json을 읽어 실제 임베딩을 생성한다. 문서 ID·회사 소속·metadata·384차원 유한 비영벡터를 검증한 후 동일 회사·버전의 색인을 트랜잭션으로 교체한다. rag_indexes에 모델·revision·코퍼스 해시·chunk 수를 기록한다. 비밀값은 환경 변수로만 받고 업무 테이블은 변경하지 않는다.
- RAG_DATABASE_URL은 검색 계정, RAG_INDEX_DATABASE_URL은 색인 쓰기 계정으로 분리한다. 접속 예시는 기준 문서 §12를 따른다. pgvector는 postgres:5432/ax로 접속하며 HTTP 벡터 서비스 주소는 두지 않는다.

# 7. 검증 (전부 실행하고 결과를 quality_checks.json에 기록)
- pgvector 확장이 설치된 PostgreSQL 16에서 sql/00 → sql/01 → sql/03_pgvector → fixtures/02 → fixtures/03 순으로 실행해 오류 0건을 확인한다. 이후 examples/pgvector_ingest.py를 실행한다. 실제 사용한 PostgreSQL·pgvector 버전을 기록한다. PostgreSQL을 쓸 수 없으면 업무 테이블만 SQLite 미리보기로 검증하고 pgvector 적재·검색은 미검증으로 명시한다. SQLite로 벡터 검색까지 통과했다고 기록하지 않는다.
- 업무 테이블 14개·FK 24개, RAG 테이블 2개·FK 3개, 전체 ax 16개·FK 27개를 각각 검증한다. 행 수(기준 문서 §5 범위)·FK 무결성도 검증한다. CSV는 업무 테이블 14개만 제공하며 RAG 테이블은 indexer가 채운다.
- §3의 8개 조건 각각 통과 여부.
- compute_ax.py 결과 = eval 정답 = fixture 03 값 일치.
- rag/docs 문서 ID·process_id가 DB documents와 일치, chunk 수.
- pgvector 적재 성공 시 JSONL 수 = rag_indexes.chunk_count = 해당 회사·버전 rag_document_chunks 행 수인지 확인한다. 임베딩 차원·모델·revision·코퍼스 해시, 회사·문서 유형·업무 필터, cosine 거리 오름차순(score는 작을수록 유사), 동일 버전 재적재 시 중복 없음, 색인 불일치 오류를 검증한다. OpenAI API 호출·DB 연결 등으로 실행하지 못한 항목은 사유와 함께 미검증으로 기록한다.

# 8. 결과물
AX_Navigator_AI_MVP_v3.zip
├── README.md               (구성, 실행 순서, 주의사항 — 기존 README 형식)
├── CHANGELOG_v3.md         (NoRole → v3 변경점, 계약 변경 제안이 있으면 별도 절)
├── quality_checks.json
├── config/   ax_score_policy_v1.json, roi_policy_v1.json, assessment_criteria_v1.json
├── sql/      00_schema_postgres16.sql, 01_seed_input_postgres.sql, 03_pgvector.sql
├── fixtures/ 02_demo_waiting_approval.sql, 03_demo_after_requester_approval.sql
├── csv/      14개 테이블 CSV (헤더 = DDL 컬럼)
├── rag/      docs/*.md, pgvector_import.jsonl, doc_mapping.json
├── eval/     demo_expected_portfolio.json, benchmark_queries.json, reference_9_processes.json
├── erd/      dbml, mmd, png (업무 14개 + RAG 2개 테이블을 구분해 표시)
└── examples/ compute_ax.py, run_postgres.sh, pgvector_ingest.py, validate_final.py

마지막 답변에는 (1) 선정 3개와 AX점수·총비용, (2) 2등 조합과 점수 차, (3) 단순 상위 3개 선택과 다른 이유,
(4) §3 조건 통과표, (5) 계약 변경 제안(있으면)만 짧게 정리하라.
```

---

## 받은 뒤 확인할 것

| 확인 | 방법 |
|---|---|
| 스키마가 기준 문서와 같은지 | `sql/00_schema_postgres16.sql`의 업무 테이블 14·FK 24 및 `sql/03_pgvector.sql`의 RAG 테이블 2·FK 3이 §5와 같은지 (합계 16·27) |
| 정답이 재현되는지 | `python examples/compute_ax.py` 결과가 `eval/demo_expected_portfolio.json`과 같은지 |
| 시연 조건 8개 | `quality_checks.json`에 전부 통과로 기록됐는지 |
| fixture 값 일치 | fixture 03의 `roadmap_items` 점수·금액이 eval 정답과 같은지 |
| 문서 일관성 | 인사 매뉴얼의 승인 규칙과 DB `requires_approval`, 제외 업무 사유가 서로 맞는지 |
| 벡터 색인 | `rag/pgvector_import.jsonl`·매핑·실제 pgvector 행 수가 같고, 회사·업무 필터 및 cosine 거리 검색이 검증됐는지. 실행 못했으면 미검증 사유 확인 |

검수가 끝나면 백엔드에 `sql/00`, `sql/01`, `config/*.json`, `eval/demo_expected_portfolio.json`을 넘겨 주세요. 백엔드 단위 테스트가 이 정답 파일을 그대로 씁니다. 데이터·MCP 담당자는 추가로 `sql/03_pgvector.sql`, `rag/`, `examples/pgvector_ingest.py`를 사용해 같은 PostgreSQL의 RAG 색인을 준비합니다.
