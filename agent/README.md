# AX Navigator Agent — 팀원 구조 통합본

AI 저장소의 팀원 `agent/` 뼈대(f83b3f1)를 기준으로 기존 v3 실행 노드를 연결했다. 팀원 AI·BE·FE 원본은 수정하지 않았다. 상세 변경과 최신 BE 검증 결과는 `../docs/TEAM_AGENT_ALIGNMENT.md`를 참고한다.

## 구조

```text
app/
  main.py                  # FastAPI·인증·라이프사이클
  runner.py                # 작업 시작·중복 방지·승인 재개·상태 콜백
  graph/
    builder.py             # 팀원 StateGraph 조립 인터페이스
    routing.py             # 팀원 분기·재탐색 규칙
    nodes/
      implemented.py       # 실제 collect~register 노드 팩토리
      approval.py          # 뼈대 승인 노드·그래프 단독 테스트
      stubs.py             # 뼈대 단독 테스트용 (서비스는 실제 노드 주입)
  models/                  # State·API 모델·이벤트 타입
  clients/
    spring.py              # Spring 상태·이벤트 HTTP 전송
    mcp.py                 # Business/RAG MCP 세션·도구 호출
  harness/                 # 팀원 마스킹·한도·재시도 부품
  contracts.py             # Spring 조회 DTO 정규화
  presentation.py          # 기존 FE 표시 DTO
```

기존 `from agent.app.graph import build_graph`·`from agent.app.clients import Gateway`는 호환 export로 유지한다. 실제 서비스는 `build_nodes(...)`로 만든 모든 노드를 `graph.builder.build_graph(checkpointer, nodes=...)`에 연결한다. 뼈대의 빈 노드만으로 서비스가 실행되지 않는다.

## 실행

프로젝트 루트(`Agent_Project`)에서:

```sh
uv sync --project agent --locked
uv run --project agent python scripts/chat_agent.py --mode mock
uv run --project agent python scripts/chat_agent.py
```

마지막 명령은 루트 `.env`의 실제 OpenAI 키를 사용하지만 데이터·검색·등록은 시연용이다. y/n 없이 가상 등록까지 진행한다. `/multi`로 여러 줄 질문을 입력한다.

실제 Spring·Business MCP·RAG MCP와 연결하려면 환경 변수 `AGENT_MODE=live`, `INTERNAL_TOKEN`, `AGENT_DATABASE_URL`, `SPRING_INTERNAL_URL`, `BUSINESS_MCP_URL`, `RAG_MCP_URL`, `OPENAI_API_KEY`, `LLM_MODEL`을 설정한다. Agent는 Spring과 같은 내부 토큰을 사용하며 Spring은 `AGENT_ENABLED=true`, `AGENT_BASE_URL`이 필요하다.

```sh
uv run --project agent uvicorn agent.app.main:app --port 8000 --workers 1 --http h11
```

**`--http h11`을 유지한다.** 최신 BE의 Java HttpClient가 보내는 h2c 업그레이드 요청에서 자동 선택된 httptools 처리는 요청 본문을 놓쳐 422를 반환하는 문제가 재현됐다. h11에서는 같은 BE 코드로 정상 수신됐다. Docker 기본 실행에도 적용했다.

루트 또는 현재 디렉터리의 `.env`를 읽으며 기존 환경 변수가 우선한다. 팀원 `POSTGRES_*` 설정도 지원하고, 명시한 `AGENT_DATABASE_URL`이 우선한다. 키는 출력하지 않는다.

## 테스트

```sh
uv run --project agent python -m pytest agent/tests tests -q
sh scripts/verify_pgvector.sh
```

첫 명령은 독립 Agent·계약·팀원 그래프/Harness 검사다. 실제 DB 설정이 없는 검사는 skip된다. 두 번째는 `.env`의 OpenAI API 키로 실제 문서 임베딩을 호출해 pgvector·MCP·체크포인터를 검증한다. 이 통합 검사의 Spring·LLM은 fixture이며, 최신 실제 Spring 전체 흐름 검증과 구분한다. 로컬 임베딩 라이브러리는 필요 없으며 RAG 서버는 OpenAI SDK를 사용한다.

실제 최신 BE와 승인·거절·DB 저장까지 확인한 결과는 `../.local/reports/team_aligned_e2e.json`, FE 채팅 상태·SSE 모듈 검사는 `../.local/reports/team_aligned_fe_store.json`에 로컬 생성되며 Git에서 제외한다. 검증에서 LLM은 MockReasoner를 사용했고, 실제 OpenAI 응답 품질이나 브라우저 클릭까지 검증한 것은 아니다.
