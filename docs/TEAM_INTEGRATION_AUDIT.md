# BE · FE · Agent 연동 점검 결과

점검일: 2026-10-20. BE·FE 원본은 수정하지 않았다. 빌드·실행은 `/private/tmp/ax-team-audit`의 복사본에서 진행했다. 원본 211개 파일의 점검 전후 SHA-256이 일치한다.

## 결론

조회·AX 계산과 Agent 응답의 FE 렌더링은 검증했다. **전체 FE → Spring → Agent → 저장 → FE 완료 흐름은 아직 연결되지 않는다.** 실제 Spring에 작업·콜백·저장·문서 API가 없기 때문이다. 이 API를 Agent에서 대신 만들거나 성공한 것처럼 우회하지 않았다.

대상 경로:

- BE 실행 대상: `/Users/hong-yonghun/Documents/BE/BE/demo`. 바깥쪽 `BE/demo`는 별도 최소 프로젝트이므로 혼동하면 안 된다.
- FE: `/Users/hong-yonghun/Documents/FE` (React·Vite).
- Agent: `/Users/hong-yonghun/Documents/Agent_Project/agent`.

## 실제 확인한 범위

| 검사 | 결과 | 조건 |
|---|---|---|
| BE 테스트·bootJar | 통과, 테스트 40개 | 팀원의 Gradle 9.8.1·Boot 4.1.1·Java 21, 원본과 같은 설정 |
| FE 타입 검사·production build·lint | 통과 | 임시 복사본에서 npm ci, npm run build, npm run lint |
| FE API 모듈 → Vite 프록시 → 실제 Spring 로그인 | 통과 | 시드 사용자 602, JWT는 보고서에 기록하지 않음 |
| 같은 FE API 모듈의 작업 생성 | **404** | POST /api/ai/tasks 미구현 |
| Agent Gateway → 실제 Business MCP HTTP → 실제 Spring → PostgreSQL 조회 | 6개 모두 통과 | 기업·업무·지표·시스템·예산·솔루션 |
| 같은 경로의 ROI | 후보 8개 모두 v3 정답과 일치 | Pydantic 엄격 검증 포함 |
| 같은 경로의 포트폴리오 | 통과 | 507·508·509, 265.0점, 295,000,000원, 유효 조합 39개 |
| 수정한 Agent API 결과 → 기존 FE TurnView 렌더링 | 승인 대기·DONE 모두 통과 | 실제 FE 컴포넌트의 React SSR, Agent의 LLM·업무 도구는 mock |
| 승인 소유권·저장 전 차단·등록 DTO·TOKEN 이벤트 | Agent 테스트 통과 | 다른 사용자 승인 403, 승인 전 projects 빈 배열 |
| 실제 pgvector·MCP HTTP·PostgreSQL 체크포인터 | 기존 통합 검사 통과 | 이 검사의 Spring과 LLM은 명시적인 fixture |

로컬 DB는 기존 서비스와 분리한 PostgreSQL 17 + pgvector 0.8.1이다. 이번 점검에서 PostgreSQL 16이나 실제 OpenAI 호출, 브라우저 클릭을 검증했다고 주장하지 않는다. FE build의 500KB 청크 경고와 기존 Authlib deprecation warning은 별도 사항이다.

## Agent 측에 적용한 수정

1. `agent/app/contracts.py`: Spring camelCase 조회 DTO를 Agent 내부 snake_case로 변환한다. 업무별 `months[]`는 월별 원본을 유지하며 펼치고, 시스템의 `processes[]`는 연결 정보로 분리한다. 누락 월과 null 집계값을 보존하며 계산하지 않는다.
2. `agent/app/presentation.py`, `graph.py`: 기존 FE가 요구하는 `processName`, `departmentName`, `solutionName`, `solutionType`, `firstYearCostKrw`, `selected`, `budgetLimitKrw`, `evidence.documentId`, `projects[]`를 실제 도구 값과 조회 정보로 구성한다. 기존 `assessment`, `portfolio`, `registration`은 유지한다.
3. FE `priority`에는 호환용으로 도구의 `axScore`를 그대로 복사하고 `priorityBasis=AX_SCORE`를 명시한다. **이것은 예전 ROI 우선순위 식으로 계산한 값이 아니다. FE의 오래된 안내 문구는 별도로 변경해야 한다.**
4. FE용 `maturity`는 Spring이 `total_score`를 반환한 경우에만 제공한다. 총점이 없으면 원본 `assessment`를 보존하고 차트용 `maturity=null`을 반환한다. Agent에서 총점을 임의 계산하거나 0으로 대체하지 않는다.
5. `main.py`: 검증된 완성 설명을 승인 대기 전에 `TOKEN` 이벤트 한 건으로 전달한다. 기존 FE는 `result.answer`만 받아서는 설명을 표시하지 않으므로 필요하다. 실제 토큰 단위 스트리밍을 구현한 것은 아니다.
6. 등록 응답에 실제 반환된 프로젝트 ID와 요청했던 항목 ID·이름·부서를 포함한다. 완료 후 응답의 “승인 후 등록합니다” 문구를 완료 상태로 바꾼다. 기본 프로젝트 상태 REGISTERED는 생성 계약을 따른다.
7. 도구 종료 이벤트의 `label`을 제공한다. Spring 콜백이 HTTP 오류를 반환하면 상태와 경로를 오류에 표시한다.
8. 서비스의 요청자 승인·재개 계약은 유지한다. `chat_agent.py`만 mock/llm-demo에서 자동 승인한다.

## BE 팀원이 구현해야 할 API — 실제 404 확인

아래 경로는 유효한 JWT 또는 내부 토큰으로 호출했으나 404였다. 엔티티·테이블이 존재하는 것과 컨트롤러·서비스가 구현된 것은 다르다.

| Method | 경로 | 필요한 역할 |
|---|---|---|
| POST | `/api/ai/tasks` | JWT 사용자로 ai_tasks 생성 → Agent `/tasks/{id}/run` 호출 → 202 |
| GET | `/api/ai/tasks/{taskId}` | 요청자 인가 후 상태·result·traceUrl 반환 |
| GET | `/api/ai/tasks/{taskId}/stream` | Bearer 인증 SSE·15초 heartbeat·재접속 처리 |
| POST | `/api/ai/tasks/{taskId}/approval` | 요청자 본인·대기 상태 검증, 결정 기록 후 Agent `/resume` 호출 |
| GET | `/api/docs/{documentId}` | 회사·접근 범위 검증 후 근거 원문 반환 |
| PATCH | `/internal/tasks/{taskId}` | Agent 상태·결과·오류·trace 갱신 |
| POST | `/internal/tasks/{taskId}/events` | Agent 이벤트 수신·SSE 중계 |
| POST | `/internal/assessments` | 영역 점수·문서 근거 저장, assessment_id·total_score 반환 |
| POST | `/internal/roadmaps` | 실제 승인 검증, 로드맵·항목 저장, roadmap_id·순서가 일치하는 item_ids 반환 |
| POST | `/internal/projects` | 프로젝트 저장·project_id 반환 |
| PATCH | `/internal/projects/{projectId}/status` | 프로젝트 상태 변경 |

실제 FastAPI 서비스는 실행 시작의 `PATCH /internal/tasks/{id}`에서 먼저 막힌다. 이 콜백만 로컬 캡처하고 RAG·LLM을 fixture로 둔 진단에서도, 실제 읽기 DTO 처리는 통과한 뒤 `/internal/assessments` 404에서 멈췄다. 이 진단을 전체 서비스 성공으로 해석하면 안 된다.

현재 Business MCP가 전달하는 요청 형식은 `business-mcp/server.py`에 있다. 최상위 저장 필드는 camelCase지만 `scores`, `evidence`, `items` 내부는 Agent의 snake_case 저장 계약이다. BE DTO를 구현할 때 이 중첩 필드까지 맞춰야 한다. 조회·계산 API는 이미 camelCase를 사용하며 계산 DTO는 현재 Agent와 일치한다. 쓰기는 `X-Idempotency-Key`에 대한 DB 트랜잭션 기반 중복 방지가 필요하다.

## FE 팀원에게 전달할 사항 — 소스는 수정하지 않음

- 로컬 `src/components/roadmap/CandidateTable.tsx`에는 `0.5 × ROI + 0.3 × 실현 가능성 + 0.2 × 절감액`이라는 예전 식이 있다. 최신 계약은 `Impact × 0.6 + Feasibility × 0.4`이며 포트폴리오는 AX점수 합 최대화다. `priority` 호환 필드를 받아 렌더링되어도 이 안내 문구는 잘못된 상태다.
- 로컬 `RoadmapSummary.tsx`는 ROI 중심 요약이다. 첨부 화면의 AX점수 합 중심 구성과 다르다. 현재 폴더가 팀원의 최신 커밋인지 확인해야 한다.
- `src/types/task.ts`는 오래된 임시 계약이다. Agent의 추가 `axScore`, `impactScore`, `threeYearNetKrw`, `portfolio`, `excluded`, `evaluationPolicy`, `humanReviewRequired` 등을 최신 계약으로 명시해야 한다.
- `MaturityCard`는 `totalScore.toFixed()`를 호출한다. 현재 Agent는 유효한 서버 총점이 없으면 카드 자체를 생략하도록 maturity를 제공하지 않는다. “집계 전” 표시가 필요하다면 FE에서 nullable 총점을 지원해야 한다.
- `RoadmapReport`의 상태 배지는 DONE이어도 turn.decision이 없으면 승인 대기로 표시한다. 재연결 후 DONE 결과만 복원되는 경우에는 서버 상태를 우선하는 처리가 필요하다.
- 프론트는 Spring 공개 API만 호출한다. 내부 토큰이나 OpenAI 키를 FE에 넣으면 안 된다. 실제 연결 시 `VITE_USE_MOCK=false`, 개발 프록시는 Spring 주소로 맞춘다.

## 보고서

- `reports/team_build_audit.json`: 원본 불변 확인·빌드·테스트 수.
- `reports/team_integration_audit.json`: 실제 Spring·Business MCP·계산값·404 결과.
- `reports/team_fe_api_audit.json`: 실제 FE API 모듈의 로그인·작업 생성 결과.
- `reports/team_fe_render_audit.json`: 실제 FE 컴포넌트의 Agent DTO 렌더링 결과.

수정한 Agent 테스트는 `.venv/bin/python -m pytest agent/tests tests -q`로 실행한다. 실제 pgvector와 체크포인터를 포함한 검사는 `sh scripts/verify_pgvector.sh`다. 후자의 Spring은 테스트 stub이므로 팀원 BE의 전체 구현 여부는 별도 보고서와 구분해야 한다.
