# OpenAI 임베딩 전환

현재 RAG의 문서 및 검색어 임베딩은 OpenAI Embeddings API를 사용한다.

- 모델: `text-embedding-3-small`
- 출력: API `dimensions=384` (모델 기본 차원과 다름). 기존 `vector(384)` 스키마 유지.
- 구성 식별자: `EMBEDDING_REVISION=openai-dim384-v1`. API의 고정 모델 스냅샷을 의미하지 않는다.
- 색인 버전: `RAG_INDEX_VERSION=ax-v3-openai-small-384-v1`
- 검색·색인 모두 동일한 모델·차원·코퍼스 해시를 사용한다.
- API 호출 전 이메일·전화번호를 마스킹한다. 문서 본문과 검색어는 OpenAI로 전송되며 API 사용료가 발생한다.

## 설정

프로젝트 루트 `.env`에 기존 `OPENAI_API_KEY`를 사용한다. RAG 스크립트도 루트 `.env`를 읽으며, 이미 주입한 환경변수가 우선한다. 키를 FE나 Git에 넣지 않는다.

```dotenv
OPENAI_API_KEY=<기존 키>
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_REVISION=openai-dim384-v1
RAG_INDEX_VERSION=ax-v3-openai-small-384-v1
RAG_DATABASE_URL=<검색 전용 PostgreSQL DSN>
RAG_INDEX_DATABASE_URL=<색인 전용 PostgreSQL DSN>
```

```sh
.venv/bin/python -m pip install -r rag-mcp/requirements.txt
# 문서 메타데이터가 이미 적재된 대상 DB에 새 버전의 벡터 생성
.venv/bin/python rag-mcp/index.py --if-needed
# 색인과 같은 설정으로 검색 서버 재시작
.venv/bin/python rag-mcp/server.py
```

Compose에서는 RAG·indexer를 재빌드한 후 `docker compose --profile tools run --rm indexer`로 재색인한다. Cloud Run의 서비스와 수동 색인 Job에도 OPENAI_API_KEY가 필요하다. 업무 테이블·기존 DB 볼륨을 초기화하지 않는다.

MiniLM과 OpenAI는 동일한 384차원이라도 다른 벡터 공간이다. 기존 버전은 삭제하지 않고 새 버전에 생성한다. 재색인 전 검색하면 버전 불일치 오류가 발생하는 것이 정상이다. 모델·코퍼스·차원이 일치하고 저장 벡터 검증이 통과하면 `--if-needed`는 API를 다시 호출하지 않는다.

문서 입력은 16개씩 처리한다. 빈 입력·응답 개수·순서·차원·유한성·비영 벡터를 검사하고 API 실패 시 트랜잭션을 롤백한다. 입력별 API 토큰 한도를 넘는 문서는 더 작은 청크로 나누어야 한다.

## 검증

```sh
# API 호출 없는 회귀 검사
.venv/bin/python -m pytest agent/tests tests -q
# 실제 OpenAI 임베딩 + 임시 PostgreSQL + MCP 연동 (API 호출/과금 포함)
sh scripts/verify_pgvector.sh
```

참고: https://developers.openai.com/api/reference/resources/embeddings/methods/create

## 이번 변경 검증 결과

- API 호출 없는 Agent·MCP 회귀 검사: 75 passed, 27 skipped.
- 실제 임시 PostgreSQL에서 Mock API/합성 벡터를 사용한 조건부 색인·롤백·동시실행·기존 버전 보존·MCP 검색 검사: 36 passed, 1 skipped. API 단위 검사는 두 실행에 중복 포함된다.
- 2026-10-22 사용자 전송·재색인 승인 후 실제 OpenAI API로 로컬 테스트 DB `127.0.0.1:55449/ax`에 청크 34개·384차원 저장 완료. 기존 MiniLM 버전은 벡터 해시 비교로 변경 없음 확인.
- 재실행은 API 없이 skipped 확인. 실제 검색어 3개에서 대상 근거가 상위 3개에 포함됨. 코드 리뷰 선행 문서 질의는 기술 문서 1위·코드 리뷰 2위이며, 사내 규정·장애 티켓 질의는 대상 업무가 1위다. 제한적인 검색 확인이며 전체 검색 품질 평가를 대신하지 않는다.
- 실행 중인 RAG MCP를 새 색인으로 전환하고 실제 MCP HTTP 검색 성공. BE·FE 코드와 GCP DB는 변경하지 않았다. `.env`의 RAG DSN은 이 로컬 테스트 DB를 가리키도록 설정했다.
- 상세 기록: `.local/reports/openai_embeddings_reindex.json` (Git 제외).
