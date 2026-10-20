# 팀원 Agent 구조로 통합한 결과

2026-10-20. 작업 브랜치 `codex/team-agent-alignment`.

## 기준과 작업 위치

- 팀원 Agent 기준: AI 저장소의 `agent/`, Git f83b3f1. FastAPI·LangGraph·TaskRunner·Harness 뼈대이며 MCP·실제 노드는 빈 상태였다.
- 최신 BE 기준: BE 저장소, Git 4792ef0. 이전 점검 대상인 중첩 `/BE/BE`와 달리 작업·승인·SSE·저장 API가 구현되어 있다.
- FE 기준: FE 저장소의 기존 소스.
- 수정 위치: **Agent_Project 안에서만** Agent·Business MCP·테스트·실행 설정·문서를 수정했다. 위 세 팀원 원본은 보존했다.

이전 구현을 버리지 않고, 팀원 뼈대의 빈 노드 자리에 v3 데이터·MCP·LLM 로직을 연결했다. 기존 GitHub 업로드 브랜치는 유지하며, 이번 변경은 별도 로컬 브랜치에 있다. GitHub에 이번 변경을 자동 푸시하지 않았다.

## 구조를 맞춘 부분

| 팀원 구조 | 통합한 내용 |
|---|---|
| `graph/builder.py` | 팀원 build_graph(checkpointer, nodes=...) 인터페이스와 8개 노드 조립 유지 |
| `graph/routing.py` | collect 오류 종료, 후보 재탐색 최대 2회, 승인·거절 분기 유지 |
| `graph/nodes/implemented.py` | 실제 데이터 수집·문서 검색·성숙도 근거·후보·Spring 계산 검증·일정·등록 노드 주입 |
| `runner.py` | FastAPI에서 실행기를 분리하고 체크포인트·중복 방지·동시 실행 한도·승인 소유권·정리 처리 유지 |
| `models/` | State·API·이벤트 타입 분리. v3의 scope·budget·registration 등 상태 필드 유지 |
| `clients/spring.py` | 상태·이벤트 HTTP 클라이언트 분리, JSON Content-Type·내부 토큰·엄격한 오류 처리 |
| `clients/mcp.py` | 실제 FastMCP 세션과 Business/RAG 도구 호출 연결 |
| `harness/` | 팀원 부품을 반영하고 LoopGuard·도구 출력 제한·재시도 판정 연결 |
| `pyproject.toml`, `uv.lock` | 팀원 의존성 기준 + 실제 구현이 사용하는 FastMCP. Docker requirements도 uv.lock에서 export |

기존 import와 CLI는 호환 export로 유지했다. `app.main:app`과 `agent.app.main:app` 경로 모두 import를 확인했다. 실제 서비스는 빈 stubs가 아니라 모든 실제 노드를 주입한다.

유지·보완한 차이는 다음과 같다.

- 팀원 뼈대의 미인증 FastAPI 대신 내부 토큰·요청 검증을 유지한다.
- Spring 전송 오류를 로그만 남기고 성공 처리하지 않는다. 실패한 상태·경로를 표시한다.
- 팀원 뼈대의 로컬 성숙도 총점 함수는 운영 경로에 넣지 않았다. 현재 Spring이 총점을 계산·저장하며 Agent는 임의 수치를 만들지 않는다.
- develop의 팀원 그래프·Harness·체크포인터 테스트를 보존했다. 중복 복사본은 제거했고, API 테스트는 내부 토큰·UUID·실제 mock 노드 계약으로 갱신했다. 팀원 성숙도 계산 함수·기준표와 단위 테스트는 검증용으로 보존하되 운영 경로에서는 Spring 총점을 사용한다.

## 최신 BE에서 확인하고 수정한 계약

1. Business MCP 도구 입력은 snake_case를 유지하되, Spring 저장 요청의 중첩 객체도 camelCase로 변환한다. 성숙도 영역은 `data_score → data`, `ai_capability_score → aiCapability` 등으로 바꾼다. 반환 `assessmentId`, `roadmapId`, `itemIds`, `projectId`는 Agent 내부 이름으로 정규화한다.
2. 상태 콜백은 `traceUrl`, `errorMessage`를 사용한다. 이벤트 node를 비워 보내지 않는다.
3. Spring은 REJECT 승인 API에서 먼저 작업을 REJECTED로 만든다. Agent는 거절 재개 시 RUNNING 콜백을 보내지 않아 종료 상태 역행 409를 피한다.
4. Java HttpClient의 h2c 업그레이드 요청이 기본 httptools 처리에서 본문 누락·422를 일으켰다. Agent Uvicorn을 **`--http h11`**로 실행해 같은 BE 코드로 202를 확인했다. Docker 기본 명령과 README에 반영했다.
5. 근거 컨텍스트를 30개로 제한할 때 업무별 본문 절을 먼저 보존하여, 일반 문서 조각 때문에 특정 업무의 근거가 밀려 후보에서 빠지는 문제를 보완했다.

## 실제 연동 확인

최신 Spring 복사본, 실제 Agent·Business MCP·RAG MCP HTTP, 34개 문서 조각의 pgvector 검색, PostgreSQL 체크포인터를 연결했다. 기존 사용자 DB가 아닌 임시 PostgreSQL 17 / pgvector 0.8.1을 사용했다. **LLM만 MockReasoner였으며 실제 OpenAI 호출 검증이 아니다.**

- 시드 사용자 로그인 → Spring 작업 생성 → Agent 시작 202.
- 실제 SSE TOOL_START/END → TOKEN 설명 → APPROVAL_REQUIRED 수신.
- 후보 8개, 선택 507·508·509, AX점수 265.0, 예산 295,000,000원 확인.
- 사용자 승인 → Spring 승인 기록 → Agent 재개 → 로드맵 1개·프로젝트 3개 실제 DB 저장 → DONE.
- 사용자 거절 → REJECTED, 해당 작업의 로드맵 생성 0개 확인.
- 실제 FE chatStore·API·SSE 모듈도 원본과 같은 복사본에서 Vite 프록시로 위 경로에 연결했다. 설명·후보 8개·승인 DONE/프로젝트 3개·거절 REJECTED를 확인했다. Node의 브라우저 타이머 shim을 사용했으며 브라우저 클릭 검사는 아니다.

보고서(로컬 생성, Git 제외): `.local/reports/team_aligned_e2e.json`, `.local/reports/team_aligned_fe_store.json`, `.local/reports/team_aligned_summary.json`.

## 남은 표시·환경 사항

- 최신 BE의 성숙도 저장 응답은 `{assessmentId}`만 준다. DB에는 총점이 저장되지만 Agent가 그 총점을 읽는 응답은 없다. 따라서 현재 `assessment`는 제공하되 FE용 `maturity` 차트는 총점이 없으면 생략한다. BE 팀원이 응답에 `totalScore`를 추가하면 기존 MCP 변환과 Agent가 바로 사용한다.
- FE 소스의 후보 표에는 예전 ROI 우선순위 식이 남아 있다. 호환 필드 `priority`에는 AX점수를 복사했으나 문구가 자동으로 바뀌지는 않는다. FE 팀원이 최신 AX점수·Impact·Feasibility 타입·문구를 반영해야 한다.
- 로컬 CLI의 자동 승인은 시연 모드만 해당한다. 실제 서비스는 Spring의 사용자 승인 API를 거쳐야 저장된다.
- PostgreSQL 16, 실제 OpenAI 응답 품질, GCP 배포·브라우저 UI 클릭까지 검증한 것은 아니다.
- 실행 방법과 디렉터리 구조는 `agent/README.md`에 있다. Agent 전용 uv 환경에는 RAG 임베딩 라이브러리가 없으므로 전체 서버 통합 검사는 기존 `.venv`의 `scripts/verify_pgvector.sh`로 수행한다.
