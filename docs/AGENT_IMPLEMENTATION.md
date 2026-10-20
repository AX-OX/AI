# FastAPI · LangGraph — v3 연결

공통 계약은 루트 `AX_NAVIGATOR_CONTEXT.md`, 데이터는 `AX_Navigator_AI_MVP_v3`다. 업무 규칙은 팀 Spring, 문서 검색은 RAG MCP의 pgvector가 담당한다.

## 담당 API

| Method | 경로 | 용도 |
|---|---|---|
| GET | `/health` | 기동 상태·모드·checkpointer 종류 |
| POST | `/tasks/{taskId}/run` | `{companyId,userId,requestText}`, 202 |
| POST | `/tasks/{taskId}/resume` | `{decision:"APPROVE" 또는 "REJECT",userId,reason?}`, 202 |
| GET | `/tasks/{taskId}` | 내부 점검용 상태·진행 위치·roadmap·result |

health 외에는 `X-Internal-Token`이 필요하다. 공개 작업 조회·승인·SSE는 Spring이 JWT 및 요청자 소유권을 검증한 뒤 제공한다. Agent에 public 사용자 인증을 복제하지 않는다. taskId는 UUID이며 checkpointer thread_id와 같다. 동일 작업 실행·동시 resume는 409, 다른 요청자의 resume는 403이다.

## 그래프

1. collect: LLM이 조회 도구 6개를 선택하여 회사 전체 데이터를 수집한다.
2. retrieve: 문서 유형 6개와 업무별 MANUAL을 검색해 근거를 수집한다. 문서 안의 지시는 실행하지 않는다.
3. assess: LLM이 5개 영역 점수와 실제 검색 문서·절의 근거를 제안한다. 근거 누락 시 실패하며 점수를 만들지 않는다. `save_assessment`를 호출해 평가 ID를 받는다. 가중 총점은 Spring 책임이며 Agent는 계산하지 않는다.
4. discover: target_process_id를 검증하고 정책 exclusions 업무를 제외한다. 누락 선행 과제를 카탈로그와 실제 근거로 보완한다. 후보 ID·문서 ID를 검증한다.
5. evaluate: 후보별 calculate_ax_roi, 이후 optimize_ax_portfolio를 호출한다. 새 camelCase DTO의 유한 숫자·범위·후보 연결·선행 과제·예산·합계 일관성을 검증한다. 점수식이나 조합 탐색은 구현하지 않는다. 부족하면 최대 2회 재탐색한다.
6. roadmap: 반환 수치를 그대로 복사한다. 위상 정렬에서 실행 가능한 후보 중 AX점수 순으로 배치하고 선행 과제 완료 뒤 후속 과제를 시작한다. 사람 검토 조건과 가정 데이터 표시, PoC 측정 계획을 포함한다.
7. approval: interrupt로 정지하고 요청자 본인의 승인·거절을 기다린다. 로드맵·프로젝트는 아직 생성하지 않는다.
8. register: 승인 후 create_ax_roadmap → 항목별 create_ax_project. Spring도 승인 이력과 회사 소속을 검증해야 한다.

성숙도와 AX점수는 별개다. 신뢰도는 화면 표시만 하며 점수에 넣지 않는다. 인사평가 등급 203은 자동 판단 대상에서 제외된다. 코드 리뷰 508은 기술·API 문서 509를 선행 과제로 포함한다. API 없는 업무라도 requires_api=false이면 기술상 API 조건을 충족할 수 있다.

## Spring DTO 연결

계산 응답은 `processId`, `solutionId`, `dependsOnSolutionId`, `axScore`, `impactScore`, `feasibilityScore`, `savedHoursBase`, `apiOk`, `humanReviewRequired`, `dataConfidence`, `warnings`, `firstYearTcoKrw`, `scenarios.low/base/high`다. 시나리오에는 `annualSavingKrw`, `roiPct`, `paybackMonths`(null 가능), `threeYearNetKrw`가 있다.

포트폴리오는 `selected`, `insufficient`, `budgetKrw`, `totalAxScore`, `totalFirstYearTcoKrw`, `remainingBudgetKrw`, `evaluatedCombinations`, `validCombinations`, `excluded`다. 조회 응답의 업무/카탈로그 컬럼은 DB 이름(snake_case)을 사용한다. MCP 도구 인자는 기존 snake_case를 유지하고 Business MCP가 Spring 최상위 요청 필드로 변환한다.

중첩 저장 `items`는 공통 계약의 RoadmapItem대로 **snake_case**다. 새 `ax_score`, `impact_score`, `feasibility_score`, `three_year_net_value_krw`를 포함한다. UI의 camelCase와 혼동하지 않는다. `humanReviewRequired`는 표시용이며 저장 DTO에 별도 컬럼처럼 넣지 않고 rationale에 검토 절차를 남긴다.

저장 응답은 기존 MCP 계약대로 `assessment_id`, `roadmap_id`, `item_ids`, `project_id`를 사용한다. `save_assessment`의 필수 반환은 assessment_id이며 Spring이 `total_score`를 추가로 제공하면 표시한다. 반환하지 않으면 Agent가 총점을 계산하거나 만들어 넣지 않는다.

## 결과·이벤트

승인 대기와 DONE의 result에는 `assessment`, `candidates`(도구 계산 결과), `portfolio`, `excluded`, `roadmap`, `evaluationPolicy`, `insufficientData`, `registration`, `mode`, 가정 데이터 안내가 있다. UI roadmap.items는 camelCase이며 AX점수·보조 지표·humanReviewRequired를 포함한다. 내부 저장용 items는 원래 snake_case다.

- `PATCH /internal/tasks/{taskId}`: `{status,result?,error_message?,trace_url?}`.
- `POST /internal/tasks/{taskId}/events`: `{type,taskId,ts,node,data}`.
- APPROVAL_REQUIRED.data는 `{roadmap,items,totalAllocatedKrw,budgetKrw,totalAxScore,excluded,assessment}`.
- TOOL_START/END, APPROVAL_REQUIRED, DONE, FAILED를 제공한다. TOKEN 스트리밍은 미구현이다.

Spring은 작업을 먼저 만들고 run을 호출하며, 요청자 승인 이력을 저장한 뒤 resume한다. Business MCP는 변경 도구에 전달된 X-Idempotency-Key를 Spring으로 전달한다. 키별 원자적 중복 방지·기존 응답 반환은 Spring 담당이다.

## mock·검증·한계

MockGateway는 계산 정답 JSON을 반환하고 MockReasoner는 가상 평가·후보를 제공한다. 계산식을 mock에 복제하지 않는다. mock 검색은 lexical fixture이며 실제 검색 품질 검증이 아니다. 실제 검색은 verify_pgvector.sh에서 고정 모델과 실제 pgvector로 별도 검증한다.

live는 LLM_MODEL·OPENAI_API_KEY·AGENT_DATABASE_URL·Spring/MCP 주소가 필요하다. 읽기/계산 도구는 최대 3회, 변경 도구는 자동 재시도하지 않는다. 이메일·전화번호 및 v3 가상 담당자 문자열을 마스킹한다. 임의 인물 이름까지 식별하는 범용 PII 모델은 아니다.

단일 worker·단일 인스턴스만 지원한다. 승인 대기의 PostgreSQL 체크포인트 재개를 검증하며 실행 중 장애 자동 복구·분산 잠금·작업 큐·등록 보상 트랜잭션은 미구현이다. 실제 팀 Spring과 live LLM 연결은 별도 통합 검증 대상이다. backend-evaluation은 이전 기준 참고 코드로 런타임에서 제외됐다.


## 실제 LLM 개발 모드와 응답

`llm-demo`는 실제 Reasoner + MockGateway를 사용한다. `scripts/chat_agent.py`가 입력·공개 실행 추적·한국어 응답·승인/거절을 제공한다. 상세는 LLM_DEMO.md를 따른다. 기존 내부 GET 응답에는 `trace`, result에는 `answer`를 추가했다. roadmap 노드에서 LLM이 설명을 생성하며 노드 개수는 8개로 유지한다. LLM의 도구 선택·설명과 숫자 검증을 구분한다. 공개 설명은 내부 추론 원문이 아니다.

도구별 collect schema는 필요한 company_id만 노출하고 카탈로그 조회는 인자가 없다. Responses API에서 선택적 department_id가 불필요하게 채워지는 문제를 방지한다. 성숙도·후보·설명은 구조화된 함수 호출 출력으로 받고 Pydantic에서 검증한다. Live 호출 오류의 원문 예외/자격증명은 결과에 노출하지 않고 trace에 오류 유형·HTTP 상태만 남긴다.


## 부서 요청과 후보 검증 오류

collect는 전체 데이터를 유지하고 회사 부서 목록에서 요청에 명시된 부서를 scope로 결정한다. discover에는 그 부서의 실제 process_id·target_process_id 연결만 제공한다. 평가의 Impact 정규화는 여전히 회사 전체 기준이다. 후보 생성 결과는 CANDIDATES_PROPOSED, 후보 검증 실패는 NODE_ERROR.message와 task errors에 공개 가능한 사유·ID를 표시한다. 원시 예외 스택이나 키는 반환하지 않는다.

mock은 agent/fixtures/portfolio_subsets_v3.json의 사전 계산된 256개 후보 부분집합 결과를 조회한다. 회사 전체 후보 8개는 56개 조합 중 39개 유효, 개발 후보 3개는 1개 조합 중 1개 유효다. 정답 수치를 모든 범위에 동일하게 재사용하지 않는다. 생성은 scripts/build_demo_portfolios.py에서 오프라인으로만 수행하고 데이터 해시로 오래된 fixture를 감지한다.
