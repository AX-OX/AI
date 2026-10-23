# AI 작업 가이드: 솔루션 카탈로그 업무 유형 템플릿 전환
2026년 10월 22일 · @Someone
배경과 목표
AI 리포(feat/be-change 이후)가 BE의 업무 유형 템플릿 카탈로그를 쓰도록 바꿔서, PDF로 확정한 새 회사도 솔루션 추천과 로드맵까지 받게 하는 작업이에요.
• BE는 솔루션 카탈로그를 특정 업무(target_process_id)에 묶인 구조에서 업무 유형(workType)별 템플릿으로 바꿨어요. 매칭은 Spring이 하고, 비용과 효과율은 템플릿 가정값(ASSUMED) 그대로예요.
• 템플릿 하나가 여러 업무에 붙을 수 있어서, 후보는 이제 solutionId가 아니라 (processId, solutionId) 쌍으로 구분해요.
• AI는 추출 단계에서 업무 유형을 붙이고, 후보를 Spring 후보 API에서 받아 쓰고, 후보와 선행 과제를 쌍 기준으로 다루면 돼요. 점수와 조합 계산은 지금처럼 Spring에 있어요.
확정된 BE 계약
BE 구현과 테스트는 끝났고, 아래 형식을 기준으로 작업하면 돼요. 시드 회사(회사 1) 계산 결과는 이전과 같아요.
업무 유형 enum (10개): KNOWLEDGE_QA, GUIDANCE, DECISION_SUPPORT, REPORT_AGGREGATION, RESEARCH_REPORT, MEETING_SUMMARY, TICKET_TRIAGE, CODE_REVIEW, DOC_AUTHORING, OTHER. OTHER와 유형이 없는 업무는 매칭하지 않아요.
유형
시드 업무
템플릿
KNOWLEDGE_QA
201 사내 규정 문의 응답
501 RAG
GUIDANCE
202 신규 입사자 온보딩 안내
502 AI_AGENT
DECISION_SUPPORT
203 인사평가 등급 산정
503 PREDICTION (정책 제외)
REPORT_AGGREGATION
204 주간 업무 보고 취합
504 RPA
RESEARCH_REPORT
205 시장·경쟁사 동향 리포트
505 AI_AGENT
MEETING_SUMMARY
206 회의록·액션 아이템 정리
506 AI_AGENT
TICKET_TRIAGE
207 장애 티켓 분류·배정
507 CLASSIFICATION
CODE_REVIEW
208 코드 리뷰 보조
508 RAG (509 선행)
DOC_AUTHORING
209 기술·API 문서 작성
509 AI_AGENT
API 변경
API
변경
GET /internal/companies/{id}/solution-candidates
신규. [{processId, solutionId, workType, dependsOn: {processId, solutionId} 또는 null, excludedReason, metricsSufficient}], solutionId·processId 오름차순
GET /internal/solutions
템플릿 전체. targetProcessId 삭제, workType 추가
GET /internal/companies/{id}/processes
항목마다 workType 추가 (null 가능)
POST /internal/ax/roi, 포트폴리오 selected[]
dependsOnProcessId 추가. 선행 후보 = (dependsOnProcessId, dependsOnSolutionId)
POST /internal/ax/roi 유형 불일치 400
hint expectedProcessId 대신 processWorkType, solutionWorkType
포트폴리오 runnerUp, greedyTop3
solutionIds 대신 candidates: [{processId, solutionId}]
POST /internal/extractions, 확정 API
processes[].workType 필수 (enum 밖이면 400)
후보 규칙
• 정책상 제외 업무도 후보 API에 나오고 excludedReason에 이유가 담겨요. ROI를 부르면 400 EXCLUDED_PROCESS예요.
• metricsSufficient=false인 후보는 ROI가 400 INSUFFICIENT_DATA예요. 포트폴리오에서는 warnings로 빠져요.
• 선행 템플릿은 같은 부서의 제외되지 않은 같은 유형 업무 중 processId가 가장 작은 업무에 붙어요. 붙일 업무가 없으면 그 쌍은 후보 API에 없어요.
• 포트폴리오와 로드맵은 같은 업무 중복만 막아요. 같은 템플릿을 서로 다른 업무에 함께 선정할 수 있어요.
작업 목록
아래 순서대로 진행하면 돼요. 경로는 AI 리포 기준이고, 추출만 독립적이고 나머지는 앞 단계에 의존해요.
1. 추출에 업무 유형 추가
    ◦ agent/app/schemas.py: ProcessExtract에 workType: Literal[...](enum 10개) 필수 필드를 추가해요.
    ◦ agent/prompts/extract.md: 유형별 한 줄 설명을 넣고, 문서만으로 애매하면 OTHER를 고르게 해요.
    ◦ agent/app/reasoning.py: MockReasoner.extract도 workType을 채워요.
    ◦ 완료 기준: 저장 payload의 모든 업무에 enum 값이 있고, 밖의 값은 structured output 단계에서 막혀요.
2. 후보 API 읽기 도구
    ◦ business-mcp/server.py: get_solution_candidates(company_id) 도구를 추가해요(GET /companies/{id}/solution-candidates). get_solution_catalog 설명의 target_process_id는 work_type으로 고쳐요.
    ◦ agent/app/clients/mcp.py(읽기 도구 목록), agent/app/reasoning.py(collect 도구 호출·스키마, 70·82·207행 근처), scripts/spring_contract_stub.py, scripts/agent_console.py에 새 도구를 넣어요.
    ◦ implemented.py collect: 결과를 새 state 필드(예: solution_candidates)에 담고 models/state.py에 추가해요. solutions는 템플릿 정보(이름, 유형, 설명)용으로 남겨요. 중첩 객체 dependsOn까지 snake_case로 정규화되는지 확인해요.
3. discover를 후보 쌍 기준으로
    ◦ implemented.py discover, candidate_refs.py, contexts.py(solution_fields), prompts/discover.md, MockReasoner.discover에서 target_process_id를 모두 없애요.
    ◦ 선택지는 Spring 후보 중 요청 범위 안이고 excludedReason이 null이며 metricsSufficient=true인 쌍이에요. 선택지 id는 쌍을 담아요(예: S501P201).
    ◦ 선택지가 하나도 없으면 지금처럼 성숙도 진단만 하고 DONE으로 끝내요. 지표 부족 때문이면 답변에 "지표를 입력하면 추천할 수 있다"는 안내를 넣어요.
    ◦ 중복 판단은 쌍 기준이에요. 선행 과제는 후보의 dependsOn 쌍으로 채우고, 그 쌍이 선택지에 없으면 오류예요.
    ◦ 근거 문서: 시드 회사는 지금처럼 MANUAL 문서의 업무 번호 매칭을 쓰고, 새 회사는 업로드 문서(UPLOADED) 조각 중에서 LLM이 1개 이상 고르게 해요.
4. evaluate
    ◦ schemas.py RoiResult에 dependsOnProcessId를 추가해요. validate_roi는 선행 쌍을 템플릿이 아니라 Spring 후보의 dependsOn과 비교해요.
    ◦ ROI 조회, 선정 결과 비교, 선행 누락 검사를 전부 (processId, solutionId) 키로 바꿔요.
    ◦ 선정 개수: 지금은 selected가 정확히 3개여야 해요. 새 회사는 후보가 1~2개일 수 있으니 max_items = min(3, 후보 수)로 보내고 그 개수를 검사해요. 후보가 1개라도 있으면 진단만 하고 끝내지 않고 추천해요. 새 회사는 업무 수가 적어서 3개를 고집하면 추천을 거의 받지 못하기 때문이에요. 답변에는 "추천 가능한 과제가 N개뿐"이라고 알려요.
5. roadmap, respond
    ◦ roadmap의 선행 일정(scheduled), 근거 조회(reasons), humanReviewBySolution 키를 쌍 기준으로 바꿔요(예: "201:501"). 근거 문구의 "선행 솔루션 509"는 선행 업무 이름으로 바꿔요.
    ◦ respond의 recommendations에 process_id를 함께 넣어요.
6. mock 데이터와 스키마 사본
    ◦ AX_Navigator_AI_MVP_v3/csv/의 ai_solution_catalog.csv, business_processes.csv를 BE demo/src/test/resources/ax/seed/의 같은 파일로 맞춰요(work_type 컬럼).
    ◦ agent/app/mock.py: get_solution_candidates를 BE와 같은 규칙으로 돌려주고, mock ROI·포트폴리오 응답에 dependsOnProcessId와 candidates 필드를 넣어요.
    ◦ AI 리포 db/init/01_schema.sql, 02_seed.sql을 BE db/init/00_schema_postgres16.sql, 01_seed_input_postgres.sql 최신본으로 복사해요.
테스트와 검증 기준
기존 테스트(132개 통과, 29개 건너뜀)가 그대로 통과하고, 아래 새 테스트가 추가되면 완료예요.
uv run --project agent python -m pytest agent/tests tests -q
[ ] 시드 회귀: mock 시드 회사 포트폴리오가 이전과 같아요. 예산 3억 기준 선정 [507, 508, 509], AX점수 합 265.0, 초년도 비용 합 2억 9,500만 원이고, 508의 선행은 (209, 509)예요.
[ ] 새 회사 추천: 확정한 새 회사(업무 유형 KNOWLEDGE_QA 1개, 지표 있음)가 후보 (새 업무, 501)로 ROI, 포트폴리오(max_items=1), 승인 대기까지 가요.
[ ] 같은 템플릿 두 업무: 같은 유형 업무 2개가 모두 후보가 되고 중복 오류 없이 함께 선정돼요.
[ ] 진단만 종료: 모든 업무가 OTHER이거나 후보가 전부 metricsSufficient=false면 ROI를 부르지 않고 성숙도 진단만으로 DONE이에요.
[ ] 잘못된 후보 차단: LLM이 Spring 후보에 없는 쌍을 내면 거부돼요(지금의 target_process_id 불일치 테스트를 이 내용으로 바꿔요).
[ ] 추출: 저장 payload의 업무마다 workType이 있고, enum 밖의 값은 거부돼요.
실제 BE와 연결한 확인은 BE 브랜치를 로컬에서 띄우고 GET /internal/companies/1/solution-candidates 응답이 위 계약과 같은지 보면 돼요.
AI 코딩 에이전트에 붙여 넣을 프롬프트
이 문서를 Markdown으로 내보내 AI 리포에 docs/CATALOG_TEMPLATE_TASK.md로 두고, 아래 프롬프트를 Claude Code 같은 에이전트에 붙여 넣으면 돼요.
너는 AX Navigator AI 리포(FastAPI + LangGraph Agent, business-mcp, rag-mcp)에서 작업한다.
작업 명세는 docs/CATALOG_TEMPLATE_TASK.md다. 먼저 전부 읽고, "작업 목록" 1~6을 순서대로 구현한 뒤 "테스트와 검증 기준"을 모두 만족시켜라.

규칙
- BE 계약("확정된 BE 계약")은 바꾸지 않는다. 맞지 않는 곳이 있으면 구현하지 말고 멈춰서 알려라.
- AX점수, ROI, 조합 계산은 Spring에만 있다. Agent는 Spring 값을 검증만 하고 다시 계산하지 않는다.
- 후보는 항상 (process_id, solution_id) 쌍으로 다룬다. solution_id만으로 후보를 찾거나 중복을 판단하는 코드가 남아 있으면 안 된다.
- LLM은 Spring이 준 후보 쌍과 근거 조각 id 중에서만 고른다(지금의 Literal 기반 grounding을 유지).
- 주변 코드의 스타일, 주석 밀도, 이름 규칙을 따른다.
- .env는 읽거나 출력하지 않는다. 커밋과 브랜치 생성은 하지 않는다.
- 끝나면 uv run --project agent python -m pytest agent/tests tests -q 결과와 바꾼 파일 목록, 확인하지 못한 것을 보고한다.
배포와 주의사항
• 같은 날 배포: /solutions 응답과 추출 payload 형식이 바뀌어서 BE와 AI를 함께 배포해야 해요. 한쪽만 올라가면 수집 단계나 draft 저장에서 실패해요.
• DB 먼저: BE는 기동할 때 스키마를 검사해서, Cloud SQL에 마이그레이션 SQL을 먼저 실행해야 해요. BE 담당자가 SQL을 갖고 있어요.
• 이미 확정한 회사: 이번 배포 전에 PDF로 확정한 회사는 업무 유형이 비어 있어서 매칭되지 않고 성숙도 진단만 받아요. 재확정 기능은 아직 없어요.
• 지표 입력은 FE 몹: 새 회사 PDF에는 건수, 시간, 인건비가 다 적혀 있지 않은 경우가 많아요. 확정 화면에서 업무 유형 수정과 지표 입력(USER_INPUT)을 받아야 추천이 나와요.
• 이번 범위 밖: 회사 규모에 따른 비용 조정, LLM이 새 솔루션을 만드는 것, 스캔본 PDF OCR은 하지 않아요.
• 아직 확인 안 된 것: 한글 실제 PDF의 텍스트 추출과 Spring, Agent, MCP를 함께 띄운 전체 흐름은 이 작업 뒤에 한 번 돌려 봐야 해요.