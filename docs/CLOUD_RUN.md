# Cloud Run 통합 패키징

기존 Agent·Business MCP·RAG MCP 코드를 그대로 루트 Dockerfile로 패키징한다.
한 이미지·한 컨테이너에서 기존 Python 서버 세 개를 실행한다. 프로세스 관리자 패키지는 추가하지 않는다.

```text
Spring → Cloud Run axox-agent:8000 → FastAPI Agent
                                    ├─ 127.0.0.1:9101/mcp → Business MCP → Spring /internal
                                    └─ 127.0.0.1:9102/mcp → RAG MCP → Cloud SQL axox
Agent 체크포인터 ─────────────────────────────────────────→ Cloud SQL agent
```

시작 스크립트는 MCP 두 개의 기존 `/mcp` HTTP 응답을 확인한 뒤 Agent를 실행한다.
하나라도 종료되면 나머지를 종료하고 실패 코드로 컨테이너를 끝낸다.
SIGTERM은 세 프로세스에 전달하고 최대 7초 후 남은 프로세스를 강제 종료한다.
Agent는 기존 `--workers 1 --http h11`을 사용하고 `PORT`만 환경에서 읽는다.
상태 확인은 기존 Agent `GET /health`를 사용한다. 이 응답은 DB·검색·LLM의 정상 연결을 보장하지 않는다.
컨테이너 시작 시 DB 생성·시드 적용·색인은 수행하지 않는다.

## 빌드와 로컬 실행

```sh
docker build --platform linux/amd64 -t axox-agent:local .
# DB·LLM 없이 세 서버 기동과 Agent의 기존 mock 흐름 확인
docker run --rm -p 127.0.0.1:18000:8000 \
  -e AGENT_MODE=mock -e INTERNAL_TOKEN=local-test-only axox-agent:local
curl http://127.0.0.1:18000/health
```

실제 연결 검증에는 별도로 제공한 환경변수와 네트워크가 필요하다. mock 모드는 MCP 대신
기존 MockGateway를 사용한다. MCP 프로토콜 연결과 live 검색 성공은 구분해서 확인한다.
회귀 검사는 기존 `agent/.venv/bin/python -m pytest agent/tests tests -q`를 사용한다.

Dockerfile은 기존 세 requirements 파일을 함께 설치하고 `pip check`를 실행한다.
PyTorch는 기존 버전의 CPU wheel을 사용한다. 기존 384차원 임베딩 모델과 고정 revision은
빌드 시 공개 모델 저장소에서 다운로드한다. 실행 시에는 이미지의 캐시를 오프라인으로 사용한다.
모델을 바꾸려면 이미지 재빌드와 문서 메타데이터·색인 버전 검토가 필요하다.
`.dockerignore`와 명시적 COPY로 `.env`, 로컬 가상환경, Git 및 자격증명 파일을 제외한다.

## Cloud Run 콘솔 설정

| 항목 | 값 |
|---|---|
| 프로젝트 / 리전 | `my-project-axox` / `asia-northeast1` |
| 신규 서비스 | `axox-agent` |
| 소스 빌드 | 저장소 루트 컨텍스트, `/Dockerfile` |
| 배포 브랜치 / 정규식 | `main` / `^main$` (`develop`은 개발용) |
| 컨테이너 포트 | `8000` |
| 명령·인수 재정의 | 비워둠: 이미지의 시작 스크립트 사용 |
| 실행 환경 | 2세대 |
| 시작 리소스 제안 | CPU 2 / 메모리 4 GiB, 부하 측정 후 조정 |
| CPU / 결제 | 인스턴스 기반, 요청 밖에서도 CPU 할당 |
| 최소 / 최대 인스턴스 | 초기 1 / 1, 아래 복구 한계 확인 |
| HTTP 동시 요청 수 | 초기 8, Agent 내부 작업 한도와 별개 |
| 시작 프로브 | HTTP `/health`, 포트 8000, 주기 2초·최대 120회 |
| 서비스 계정 | AI 전용 런타임 서비스 계정 지정 |
| Cloud SQL 연결 | 기존 인스턴스의 전체 연결 이름을 직접 입력 |

2 CPU / 4 GiB는 세 Python 프로세스와 CPU 임베딩 모델을 고려한 출발값이며 처리량을 보장하는 측정값은 아니다.
MCP는 컨테이너의 `127.0.0.1`에만 바인딩한다. 별도 Cloud Run 서비스나 외부 URL이 필요하지 않다.
기존 Spring 서비스 `axox`와 Cloud SQL 인스턴스는 이 저장소 배포로 재생성하거나 변경하지 않는다.

| 일반 환경변수 | 값 |
|---|---|
| `AGENT_MODE` | `live` |
| `LLM_MODEL` | 팀에서 사용하는 실제 모델 ID, 직접 지정 |
| `BUSINESS_MCP_URL` | `http://127.0.0.1:9101/mcp` (이미지 기본값) |
| `RAG_MCP_URL` | `http://127.0.0.1:9102/mcp` (이미지 기본값) |
| `SPRING_INTERNAL_URL` | `https://axox-853402721456.asia-northeast1.run.app/internal` (이미지 기본값) |
| `AGENT_COMPANY_ID` / `RAG_COMPANY_ID` | 기본 `1`, 기존 시연 문서의 회사 범위 |
| `RAG_INDEX_VERSION` | 기본 `ax-v3-pgvector-v1` |

Secret Manager의 **숫자 버전**을 환경변수로 참조한다. 실제 값은 이미지·Git·배포 문서에 기록하지 않는다.

| 비밀 환경변수 | 내용 |
|---|---|
| `INTERNAL_TOKEN` | 기존 Spring과 같은 내부 토큰 |
| `OPENAI_API_KEY` | LLM 호출 키 |
| `RAG_DATABASE_URL` | `axox` DB 읽기 전용 DSN |
| `AGENT_DATABASE_URL` | `agent` DB 전용 DSN |

`RAG_INDEX_DATABASE_URL`은 서비스에 설정하지 않고 별도 수동 색인 작업에만 주입한다.
`JWT_SECRET`, `SPRING_DATASOURCE_URL` 등 Spring 전용 설정은 필요하지 않다.
Agent의 기존 시작 검증은 내부 토큰, 모드, LLM 모델·키, live 체크포인터 연결을 검사한다.
MCP/DB 연결 실패는 해당 도구 실행 시 드러나므로 `/health` 성공만으로 연동 완료로 판단하지 않는다.

## 서로 다른 프로젝트의 Cloud SQL 연결

Cloud SQL 인스턴스의 **실제 리전과 인스턴스 ID는 아직 제공되지 않았다.**
아래 `INSTANCE_REGION`, `INSTANCE_ID`는 확인한 값으로 바꾼다. Cloud Run 리전으로 추측하지 않는다.

1. 두 프로젝트 모두 Cloud SQL Admin API 활성화 여부를 확인한다.
2. AI 런타임 서비스 계정에 **`axox-db-trial` 프로젝트의 `roles/cloudsql.client`**를 부여한다.
3. AI 서비스의 Cloud SQL 연결에 `axox-db-trial:INSTANCE_REGION:INSTANCE_ID`를 추가한다.
4. 사용 중인 Secret 각각에 AI 서비스 계정의 `roles/secretmanager.secretAccessor`를 부여한다.
5. Unix socket 경로 `/cloudsql/axox-db-trial:INSTANCE_REGION:INSTANCE_ID`를 DSN에 사용한다.

Unix socket용 psycopg 연결 문자열 예시(비밀값은 Secret Manager에 저장):

```text
postgresql://ax_rag_reader:URL_ENCODED_PASSWORD@/axox?host=/cloudsql/axox-db-trial:INSTANCE_REGION:INSTANCE_ID&connect_timeout=10
postgresql://ax_agent:URL_ENCODED_PASSWORD@/agent?host=/cloudsql/axox-db-trial:INSTANCE_REGION:INSTANCE_ID&connect_timeout=10
```

암호의 특수문자는 URI 인코딩해야 한다. DSN에 `jdbc:`나 `postgresql+psycopg:`를 붙이지 않는다.
libpq 키워드 형식(`dbname=agent user=ax_agent password='...' host=/cloudsql/... connect_timeout=10`)도 지원한다.
IAM의 Cloud SQL Client 권한은 연결용이며 PostgreSQL 테이블 접근 권한을 대신하지 않는다.
공개 IP가 없는 private-only 인스턴스라면 같은 네트워크로 접근할 VPC 구성이 별도로 필요하다.
기존 Spring의 Java Connector 연결 성공만으로 Python Unix socket 접근까지 구성됐다고 볼 수 없다.

근거: [Cloud Run에서 Cloud SQL 연결](https://docs.cloud.google.com/sql/docs/postgres/connect-run),
[Secret Manager 주입](https://docs.cloud.google.com/run/docs/configuring/services/secrets).

## PostgreSQL 계정과 권한 — 관리자 실행용 안내

아래 명령은 **준비 방법이며 이 작업에서는 실행하지 않았다.** 기존 스키마·테이블·시드를 다시 적용하지 않는다.
권한을 부여하기 전 같은 이름의 계정이 이미 있으면 역할 상속·기존 권한을 확인한다.
기존 계정의 과도한 권한이나 PUBLIC에 부여된 권한은 아래 GRANT만으로 제거되지 않는다.

`axox` DB의 최소 권한(계정이 없을 때만 `CREATE ROLE` 실행, 비밀번호는 psql `\password` 또는 관리 절차로 설정):

```sql
CREATE ROLE ax_rag_reader LOGIN NOINHERIT;
CREATE ROLE ax_rag_indexer LOGIN NOINHERIT;
GRANT CONNECT ON DATABASE axox TO ax_rag_reader, ax_rag_indexer;
GRANT USAGE ON SCHEMA public TO ax_rag_reader, ax_rag_indexer;
GRANT SELECT ON public.rag_indexes, public.rag_document_chunks TO ax_rag_reader, ax_rag_indexer;
GRANT SELECT (document_id, company_id, process_id, title, doc_type, access_level, version)
    ON public.documents TO ax_rag_reader, ax_rag_indexer;
GRANT INSERT, UPDATE, DELETE ON public.rag_indexes, public.rag_document_chunks TO ax_rag_indexer;
```

실제 `pgvector_client.py`의 JOIN·소속 확인·DELETE·UPSERT에 필요한 권한이다.
기존 RAG 테이블에는 시퀀스가 없어 시퀀스 권한은 필요하지 않다.
업무 테이블 쓰기·스키마 CREATE·TRUNCATE·DROP 권한은 RAG 계정에 부여하지 않는다.
기존 `vector 0.8.5`와 RAG 테이블을 사용하며 확장을 재설치하지 않는다.

체크포인터는 관리자 권한으로 `postgres` DB에 연결해 존재 여부부터 확인한다:

```sql
SELECT datname FROM pg_database WHERE datname = 'agent';
SELECT rolname FROM pg_roles WHERE rolname = 'ax_agent';
-- 역할이 없을 때만 실행. 비밀번호는 별도로 설정한다.
CREATE ROLE ax_agent LOGIN NOINHERIT;
```

psql에서 아래 조건부 생성은 트랜잭션 밖에서 실행한다. 기존 `agent` DB는 유지한다:

```sql
SELECT 'CREATE DATABASE agent'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'agent') \gexec
GRANT CONNECT ON DATABASE agent TO ax_agent;
\connect agent
GRANT USAGE, CREATE ON SCHEMA public TO ax_agent;
```

`AsyncPostgresSaver.setup()`이 기존 코드대로 체크포인트 테이블 4개와 인덱스를 생성·마이그레이션한다.
따라서 최초 실행·업그레이드에는 public 스키마 CREATE와 해당 체크포인트 테이블의 소유권이 필요하다.
신규 테이블은 접속 계정 `ax_agent` 소유가 된다. 기존 테이블이 다른 계정 소유라면 관리자가 먼저
소유권·마이그레이션 방법을 검토해야 한다. 단순 SELECT/INSERT 권한만으로 setup은 충분하지 않다.
`ax_agent`에는 `axox` 업무 테이블 권한을 부여하지 않는다. DSN의 DB 이름을 반드시 `agent`로 구분한다.

## Spring 호출과 IAM 인증

현재 BE `demo/src/main/java/com/axnavigator/agent/AgentClient.java`를 읽어서 확인했다.
`POST /tasks/{taskId}/run`, `/resume`에 JSON과 `X-Internal-Token`을 보내고 202를 기대한다.
AI의 기존 계약은 그대로 유지된다. BE 소스는 수정하지 않았다.

Spring 저장소에서 설정할 값은 `AGENT_ENABLED=true`, `AGENT_BASE_URL=<AI 서비스 기본 URL>`이다.
Cloud Run IAM 인증 필수 서비스는 `X-Internal-Token`에 더해 Google ID 토큰과 호출 계정의
`roles/run.invoker`가 필요하다. Spring에서는 수신 서비스 기본 URL을 audience로 사용한 ID 토큰을
`Authorization: Bearer ...` 또는 `X-Serverless-Authorization: Bearer ...`로 추가해야 한다.
현재 Spring 클라이언트에는 이 처리가 없다. 앱 내부 토큰과 IAM 인증은 각각 별도다.

기존 Spring이 IAM 보호 상태라면 AI → Spring 요청에도 같은 처리가 필요하다.
현재 `business-mcp/spring_client.py`와 `agent/app/clients/spring.py`에는 Google ID 토큰 발급 기능이 없다.
이번 최소 패키징 작업에서는 추가하지 않았다. 두 방향의 IAM 정책을 배포 전에 결정해야 한다.
앱 토큰만 사용하는 기존 계약을 유지하려면 Cloud Run 플랫폼에서 해당 HTTP 호출을 허용하는 구성이 필요하다.

근거: [Cloud Run 서비스 간 인증](https://docs.cloud.google.com/run/docs/authenticating/service-to-service).

## 최초 색인 — 기존 index.py를 명시적으로 실행

청크 34개는 이미 JSONL에 있다. 다시 청킹하지 않는다.
색인 전에 관리자가 **읽기 전용으로** 기존 `documents`의 401~408 메타데이터를
`rag/doc_mapping.json`의 회사·대표 업무·제목·유형·접근 수준·버전과 대조해야 한다:

```sql
SELECT document_id, company_id, process_id, title, doc_type, access_level, version
FROM public.documents WHERE document_id BETWEEN 401 AND 408 ORDER BY document_id;
```

회사 ID 1의 문서 8개가 일치해야 한다. 누락·불일치가 있으면 중단하고 기존 데이터 관리 담당자에게 확인한다.
기존 indexer도 RAG 데이터를 변경하기 전에 소속·메타데이터를 검증한다.
이미 존재하는 업무 DB에 시드 전체를 재실행하거나 임의 문서 행을 추가하지 않는다.

별도 Cloud Run Job에 서비스와 같은 이미지를 지정하되 아래와 같이 설정한다:

- 명령 재정의: `python`
- 인수: `rag-mcp/index.py`
- 태스크 수 1, 병렬성 1, 초기 자동 재시도 0, 제한 시간 600초
- Cloud SQL 연결과 색인 전용 서비스 계정·Secret 접근 권한 설정
- 환경: 이미지 기본 corpus·모델·revision·색인 버전 유지, `RAG_INDEX_DATABASE_URL`만 색인 계정 DSN으로 주입
- Agent·Spring·OpenAI 비밀값은 Job에 불필요

이 작업은 해당 회사·색인 버전의 기존 청크를 트랜잭션으로 교체한다.
서비스 배포마다 자동 실행하지 않는다. **명시적 승인 후 별도 실행할 데이터 쓰기 작업**이다.
실행 후 관리자는 `rag_indexes.chunk_count=34`, 실제 청크 수 34, 벡터 차원 384와 모델·revision·검색 결과를 확인한다.

## 백그라운드 실행과 남은 배포 조건

기존 Agent는 202 응답 후 `asyncio.create_task()`로 분석한다. 요청 기반 CPU 할당에서는
응답 후 작업 진행을 보장할 수 없으므로 인스턴스 기반 CPU와 최소 인스턴스 1을 사용한다.
최소 인스턴스도 재시작·장애·배포 교체를 막지 못한다. 설정만으로 완전한 작업 복구는 해결되지 않는다.

- 체크포인터로 승인 대기 작업은 재시작 후 기존 `/resume`으로 재개할 수 있다.
- 분석 도중 종료된 작업은 자동 재예약되지 않는다. 같은 ID의 `/run`은 기존 상태 때문에 409가 된다.
- 실행 중 작업 목록·중복 방지 락은 프로세스 메모리다. 최대 인스턴스 1도 배포 중 리비전 중첩까지 막지는 못한다.
- 운영 수준의 자동 복구에는 내구성 있는 작업 큐·분산 락·멱등 저장을 별도 설계해야 한다.
  이번 패키징에 새 큐·재실행 API·복구 계층은 추가하지 않는다.

근거: [CPU·백그라운드 실행](https://docs.cloud.google.com/run/docs/configuring/billing-settings),
[SIGTERM·컨테이너 실행 계약](https://docs.cloud.google.com/run/docs/container-contract).

배포 전에 필요한 확인: 실제 Cloud SQL 연결 이름·네트워크, `agent` DB와 계정 소유권,
읽기/색인 계정 권한, Secret 숫자 버전, 두 방향 IAM 정책, LLM 모델 ID,
문서 메타데이터 일치, 별도 최초 색인, 분석 중 재시작 처리 방침.
이 저장소 수정 과정에서는 GCP 배포·비밀값 조회·실제 DB 변경을 수행하지 않았다.

## 로컬 검증 결과 (2026-10-21)

- 루트 Dockerfile의 `linux/amd64` 빌드 성공, 이미지 내 `pip check` 통과.
- Agent `0.0.0.0:8000`, MCP `127.0.0.1:9101/9102` 바인딩과 `/health` 200 확인.
- 실제 localhost MCP ping·도구 목록·RAG 원문 `docs://401` 조회 성공.
- 기존 Agent Gateway → Business MCP → 로컬 Spring fixture 호출 성공.
- 기존 mock API로 202 → 승인 대기 → 승인 → DONE 및 가상 프로젝트 3개 확인.
- 이미지의 실제 CPU 임베딩 모델로 청크 34개를 384차원으로 변환. DB 저장은 실행하지 않음.
- 세 서버를 각각 강제 종료했을 때 컨테이너 exit 1 확인.
- `PORT=18080`의 정상 응답과 SIGTERM 후 exit 0 확인.
- 기존 live 검증에서 내부 토큰·LLM 키/모델·체크포인터 DSN 누락 시 기동 거부 확인.
- 기존 테스트 60개 통과, 외부 DB 설정이 필요한 5개는 건너뜀.

Cloud SQL 연결·실제 Spring·실제 LLM·Cloud Run 배포 동작은 검증하지 않았다.
검증용 코드는 `/private/tmp`에서만 사용했으며 저장소의 기존 애플리케이션·테스트는 변경하지 않았다.
