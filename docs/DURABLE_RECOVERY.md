# Durable AI Worker

## 변경

`AGENT_WORKER_ENABLED=true`이면 Agent가 Spring의 `/internal/agent-commands`에서
영속 명령을 가져온다. 기본값은 false이며 기존 push API 동작을 유지한다.
복구 모드에서 `/tasks/{id}/run|confirm|resume`와 문서 ingest push 요청은 409로 거부한다.
FE의 요청과 사용자 승인 API는 계속 Spring을 통한다.

- 실행 명령·사용자 결정·재시도 횟수·PDF 입력은 BE의 업무 DB에 저장한다.
- 기존 agent DB의 LangGraph 체크포인트를 사용한다. 별도 작업 큐 DB/Redis는 추가하지 않는다.
- 같은 `taskId`로 `durability='sync'` 실행을 재개한다. 이미 저장된 노드는 다시 실행하지 않는다.
  실행 중이던 노드의 재실행은 가능하며, BE 저장 API의 중복 반환 계약에 의존한다.
- 사용자 확인·승인 대기는 자동으로 넘어가지 않는다. 확인/승인 명령이 있을 때만
  `Command(resume=...)`를 적용한다. 이미 적용된 명령을 재수신하면 남은 노드/결과 전송만 처리한다.
- 작업별 PostgreSQL 세션 advisory lock으로 체크포인트 쓰기를 직렬화한다.
  체크포인트 연결 또는 BE 임대 갱신 실패 시 실행을 취소하고 인계를 기다린다.
- ContextVar에 명령 ID·임대 토큰을 넣어 작업 간 격리한다. Spring 콜백과 Business MCP를
  통해 BE 저장 요청까지 전달한다. BE가 토큰 검증과 업무 변경을 같은 트랜잭션에서 수행한다.
- 일시 네트워크/서버/속도 제한 오류는 재시도하고, 입력·정책·권한 오류는 종료한다.
  로그에는 명령 ID·시도 횟수·오류 타입만 남기며 payload·토큰·DSN을 출력하지 않는다.
- 종료 시 새 수령을 멈추고 기본 30초 동안 작업 종료를 기다린다. 남은 작업은 취소하고
  다음 Worker가 임대 만료 후 체크포인트에서 재개한다.

## v1 계약

모든 큐 요청: `X-Internal-Token`. 경로는 Spring의 `/internal` 기준이다.

| 요청 | 응답 |
| --- | --- |
| POST `/agent-commands/claim` `{}` | 200 명령 또는 204 |
| POST `/agent-commands/{id}/heartbeat` `{leaseToken}` | 204 |
| GET `/agent-commands/{id}/input`, `X-Command-Lease` | PDF 원본 |
| POST `/agent-commands/{id}/complete` `{leaseToken}` | 204 |
| POST `/agent-commands/{id}/fail` `{leaseToken,retryable}` | 204 |

명령: `schemaVersion=1`, `commandId`, `aggregateKey`, `taskId`/`documentId`,
`kind=RUN|CONFIRM|RESUME|INGEST`, `payload`, `leaseToken`, `attempt`, `leaseSeconds`, `superseded`.
payload는 기존 API의 camelCase 필드를 사용한다. 더 최신 사용자 결정이 있는
`superseded` 명령은 이전 알림을 재전송하지 않고 완료만 확인한다.

## 활성화와 운영

대응 BE PR의 `docs/DURABLE_AI_RECOVERY.md`가 마이그레이션·배포·롤백의 기준 문서다.
**이 PR에서 운영 DB 변경이나 플래그 활성화는 수행하지 않았다.**

1. 두 릴리스를 플래그 false로 배포한다.
2. 새 분석·업로드 접수를 잠시 멈추고 레거시 진행 중 작업과 PDF 색인을 비운다.
3. BE 업무 DB에 `001_commands.sql`을 적용하고 런타임 역할의 DML 권한을 확인한다.
4. BE의 `AX_RECOVERY_ENABLED=true`를 먼저 적용하고 AI의 `AGENT_WORKER_ENABLED=true`를 적용한다.
5. AI는 live 모드, 기존 `AGENT_DATABASE_URL`, BE와 같은 `INTERNAL_TOKEN`이 필요하다.
   세션 advisory lock을 쓰므로 DB 연결은 transaction-pooling 프록시를 거치지 않는다.
6. 컨테이너 종료 유예는 `AGENT_WORKER_DRAIN_SECONDS`보다 길게 설정한다. 기본 30초이면 45초 이상을 사용한다.
7. 분석·승인·PDF 경로와 BE의 큐 집계를 확인한 뒤 접수를 재개한다.

| 환경변수 | 기본값 |
| --- | --- |
| `AGENT_WORKER_ENABLED` | false |
| `AGENT_WORKER_CONCURRENCY` | 1 (1~8) |
| `AGENT_WORKER_POLL_SECONDS` | 2 |
| `AGENT_WORKER_DRAIN_SECONDS` | 30 |

기존 Agent·Business/RAG MCP 컨테이너 구성을 그대로 사용한다. Worker는 Agent 프로세스의
별도 비동기 실행 루프로 동작하며 새 서비스 포트를 노출하지 않는다.

PDF 원본은 복구 모드에서 BE DB에 임시 저장하고 완료·영구 실패 시 입력 행을 삭제한다.
기본 24시간 만료 후 정리하며, WAL·DB 백업 사본은 기존 보관 정책을 따른다.
RAG 재색인은 기존 문서별 교체 저장을 사용한다. 장애 시 동일 원본의 임베딩 호출이 반복될 수 있다.

## 검증

```sh
uv sync --project agent --locked
uv run --project agent python -m pytest agent/tests tests -q
# 전용 테스트 PostgreSQL DSN을 AGENT_TEST_PG_DSN에 설정하면 실제 DB·SIGKILL 테스트도 실행한다.
```

`test_worker_postgres_recovery.py`는 수집 노드가 저장된 후 다음 노드에서 실제 프로세스를
SIGKILL한다. 새 Worker·새 PostgresSaver로 이어서 처리하며 수집 재실행 금지,
승인 대기 보존, 승인 결과 재전송 시 등록 중복 없음, 체크포인트 잠금 인계를 확인한다.
GitHub Actions에도 PostgreSQL 기반 검증을 추가했다.

`test_spring_recovery_contract.py`는 별도 일회용 로컬 환경을 위한 opt-in 테스트다.
matching BE를 시드 DB와 `AX_RECOVERY_ENABLED=true`로 실행하고 Business MCP를 연결한 뒤
다음 환경변수를 설정한다. 운영 URL로 실행할 수 없도록 loopback만 허용한다.

- `RECOVERY_TEST_BE_URL`: 로컬 BE 주소.
- `RECOVERY_TEST_BE_DSN`: 해당 일회용 업무 DB의 PostgreSQL DSN.
- `RECOVERY_TEST_INTERNAL_TOKEN`: 로컬 BE/MCP와 같은 테스트 토큰.
- `RECOVERY_TEST_BUSINESS_MCP_URL`: 로컬 Business MCP 주소.
- `AGENT_TEST_PG_DSN`: 일회용 체크포인트 DB.

실제 Spring·Business MCP에 저장 응답 유실을 주입해 평가·로드맵·프로젝트 중복 방지와
PDF 입력 삭제를 확인한다. 이 테스트의 LLM·RAG 검색/색인은 fixture이고 외부 API를 호출하지 않는다.

## 한계

무중단 HTTP 연결이나 VM/DB 고가용성을 보장하지 않는다. SSE는 기존 재연결·작업 조회로
상태를 회복하며 중간 이벤트 전체 재생은 없다. 실행 중 노드와 외부 API 호출은 반복될 수 있다.
기존에 중단된 레거시 작업을 자동으로 큐에 이관하지 않는다. 그래프·체크포인트 형식을 바꾸는
배포는 별도 호환성 검토가 필요하다. 플래그를 끄기 전에도 큐와 실행 중 작업을 먼저 비운다.
