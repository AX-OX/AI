# AX Navigator — v3 데이터 · MCP · Agent · FastAPI

현재 기준은 [공통 계약](AX_NAVIGATOR_CONTEXT.md)과 [v3 데이터 패키지](AX_Navigator_AI_MVP_v3/README.md)다. 인사·기획·개발 업무 9개를 분석하고 AX점수(Impact 60%, Feasibility 40%) 합으로 과제 3개를 선정한다. 기업 성숙도 5개 영역 평가도 별도로 수행하며 과제 선정 점수에는 넣지 않는다. 데이터 신뢰도는 표시만 한다.

이 저장소의 실행 범위는 데이터·MCP·Agent·FastAPI다. **업무 조회·저장·계산은 팀 Spring API에 위임한다.** `backend-evaluation/`은 이전 기준의 참고 코드로 보존했으며 compose와 검증 스크립트에서 실행하지 않는다. 새 Spring 구현으로 사용하면 안 된다.

## 연결 구조

```text
프론트 → 팀 Spring → Agent FastAPI → LangGraph
                         ├─ Business MCP → 팀 Spring 내부 API → PostgreSQL 업무 테이블
                         └─ RAG MCP → 같은 PostgreSQL의 pgvector 색인
```

Spring 공개 API는 로그인·작업 생성·조회·SSE·승인·원문 중계를 담당한다. Agent는 `/tasks/{taskId}/run`, `/resume`을 제공하고 진행 이벤트·결과를 Spring에 콜백한다. API 경로는 유지했으며 DTO를 v3로 맞췄다.

## 외부 서비스 없는 Agent 확인

```sh
AGENT_MODE=mock INTERNAL_TOKEN=local-dev-token .venv/bin/uvicorn agent.app.main:app --port 8000 --workers 1
```

mock은 v3 `eval/demo_expected_portfolio.json`의 계산 정답을 반환한다. Agent에 점수·ROI 수식이나 최적화 알고리즘을 복제하지 않았다. 검색은 lexical fixture이며 LLM도 mock이다. 회사 전체 또는 명시한 인사·기획·개발 부서 후보를 지원한다. 후보 부분집합 256개의 조합 결과는 scripts/build_demo_portfolios.py가 오프라인으로 생성한 정답이며 실행 시 JSON만 조회한다. 데이터가 바뀌면 이 fixture도 다시 생성해야 한다.

```sh
curl -X POST http://127.0.0.1:8000/tasks/11111111-1111-4111-8111-111111111111/run \
  -H 'X-Internal-Token: local-dev-token' -H 'Content-Type: application/json' \
  -d '{"companyId":1,"userId":602,"requestText":"예산 3억 원 내 AX 과제 3개를 선정해줘"}'
# 승인 대기 상태 확인
curl http://127.0.0.1:8000/tasks/11111111-1111-4111-8111-111111111111 \
  -H 'X-Internal-Token: local-dev-token'
# 요청자 승인 후 재개
curl -X POST http://127.0.0.1:8000/tasks/11111111-1111-4111-8111-111111111111/resume \
  -H 'X-Internal-Token: local-dev-token' -H 'Content-Type: application/json' \
  -d '{"decision":"APPROVE","userId":602}'
```

기대 결과는 507·508·509 선정, AX점수 합 265.0, 초년도 TCO 295,000,000원이다. 실행 순서는 선행 과제를 고려해 507 → 509 → 508이며 승인 전에는 로드맵·프로젝트를 생성하지 않는다. `save_assessment`는 승인 전 실행하는 분석 저장 도구다.

## 실제 OpenAI 입력·응답과 Agent Loop 확인

Spring 없이 실제 LLM을 쓰려면 `.env`에 OPENAI_API_KEY와 LLM_MODEL을 설정하고 실행한다.

```sh
.venv/bin/python scripts/chat_agent.py
```

실제 LLM + v3 도구 fixture인 `llm-demo` 모드다. 입력·노드 진행·도구 호출·한국어 응답·승인/거절을 확인할 수 있다. 기존 8000번 서버와 독립적으로 실행하고 API 사용량이 발생한다. 자세한 구분과 실행법은 [실제 LLM 데모 안내](docs/LLM_DEMO.md)에 있다.

## 실제 서비스 연결

```sh
cp .env.example .env
# 팀 Spring 주소·토큰·DB 계정·LLM 설정을 입력
# 새 PostgreSQL 볼륨에서 v3 업무 테이블과 RAG 테이블·DB 계정 생성
docker compose up -d postgres
docker compose --profile tools run --rm indexer
docker compose up -d business-mcp rag-mcp agent
```

기존 볼륨에는 init SQL이 자동 재실행되지 않는다. 기존 DB의 백업·migration 또는 새 v3 테스트 DB 선택은 배포 담당자와 수행하며 이 변경은 기존 DB를 삭제·초기화하지 않는다. Spring은 같은 업무 DB를 사용해야 한다. 같은 회사의 문서 ID라도 v3에서 내용이 바뀌므로 이전 색인을 재사용하지 않는다.

RAG MCP에는 `ax_rag_reader`, indexer에는 `ax_rag_indexer`를 사용한다. `db/init/04_rag_roles.sh`가 새 DB에 최소 권한을 설정한다. 검색 컨테이너에 쓰기 DSN을 전달하지 않는다. 업무와 벡터 DB 인스턴스는 하나이며 checkpointer는 별도 논리 DB `agent`를 쓴다.

Compose의 서비스 포트는 내부용이다. 팀 Spring 컨테이너를 같은 Docker 네트워크에 연결하거나 개발 환경에서 Agent 포트를 로컬로 매핑해야 Spring이 Agent를 호출할 수 있다. 호스트에서 직접 Python 서비스를 실행할 경우 접속 주소도 localhost 주소로 설정한다. `SPRING_INTERNAL_URL`은 팀 Spring 주소로 지정하며 별도 참고 Spring 모듈을 자동 기동하지 않는다.

live에서는 실제 팀 Spring·MCP·LLM과 PostgreSQL checkpointer가 필요하다. mock으로 만든 체크포인트를 live에서 재사용하지 말고 새 taskId로 실행한다. 현재 단일 worker·단일 인스턴스를 지원한다.

## 검증

```sh
.venv/bin/python -m pytest agent/tests tests -q
# 로컬 PostgreSQL pgvector 확장과 모델 캐시가 있으면:
./scripts/verify_pgvector.sh
```

두 번째 명령은 임시 PostgreSQL과 실제 Business/RAG MCP HTTP를 실행한다. FastAPI ASGI → MCP → 실제 pgvector 검색 및 PostgreSQL 체크포인트 재시작·승인 재개를 검증한다. Spring 응답과 LLM은 명시적 v3 fixture다. Java·Maven은 사용하지 않으며 기존 DB는 건드리지 않는다. 실제 팀 Spring·LLM 전체 연결을 통과했다는 의미는 아니다. 모델이 캐시에 없으면 `HF_HUB_OFFLINE=0 TRANSFORMERS_OFFLINE=0`으로 최초 다운로드가 필요하다.

상세 연결·DTO·검증 범위는 [Agent 구현 안내](docs/AGENT_IMPLEMENTATION.md), [pgvector·v3 전환 안내](docs/PGVECTOR_AND_OPPORTUNITY.md)에 있다. 통합 검증 결과는 `reports/agent_v3_demo.json`, 실제 검색은 `reports/pgvector_search_v3.json`에 기록한다. 데이터 패키지의 기존 ZIP과 계약 원본은 이번 서비스 코드 전환과 별도로 보존한다.
