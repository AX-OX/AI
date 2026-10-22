# pgvector 및 v3 AX점수 전환

현재 실행 기준은 `AX_NAVIGATOR_CONTEXT.md`와 `AX_Navigator_AI_MVP_v3/config/`다. 이전 50/35/15 가중치·2,000시간 정규화·Confidence 가산 정책은 실행 경로에서 제거했다. 과거 제안·정책은 `.local/archive/`로 보관하며 업로드하지 않는다.

## 저장과 검색

PostgreSQL 한 인스턴스의 ax DB에 업무 14개 테이블·FK 24개와 RAG 2개 테이블·FK 3개를 저장한다. agent DB는 별도의 checkpointer 논리 DB다. 별도 벡터 DB 서버는 없다.

- `rag_indexes`: 회사·색인 버전별 모델, revision, 코퍼스 해시, 청크 수.
- `rag_document_chunks`: 문서 섹션, metadata JSONB, related_process_ids BIGINT[], embedding vector(384).
- 입력: `AX_Navigator_AI_MVP_v3/rag/pgvector_import.jsonl`, `{id,document,metadata}` 34행.
- 업무 매핑: 같은 rag/doc_mapping.json의 related_process_ids. 별도 document_processes.json은 더 이상 읽거나 Docker에 복사하지 않는다.
- 모델: text-embedding-3-small, revision openai-dim384-v1.
- 새 활성 버전: ax-v3-openai-small-384-v1. 코퍼스 해시는 파일명+NUL+바이트를 pgvector_import.jsonl, doc_mapping.json 순서로 SHA-256에 넣는다. 패키지 indexer와 서비스가 동일한 규칙을 쓴다.

적재 전 문서 metadata·회사 소속·비영 384차원 유한 벡터를 확인한다. 회사·색인 버전별 advisory lock과 단일 트랜잭션으로 교체한다. 실패 시 이전 색인이 유지된다. 검색 전 모델·revision·코퍼스 해시를 검사하고 다르면 재색인을 요구한다.

검색은 회사·버전 필수 제한, 문서 유형·업무 필터, embedding <=> query_vector 오름차순이다. score는 cosine 거리로 낮을수록 가깝다. 공통 문서는 related_process_ids=[]이며 업무 검색에도 포함한다. MVP는 정확 검색이며 ANN 인덱스는 없다.

검색 계정은 RAG SELECT와 문서 소속 확인용 documents 컬럼 SELECT만, 적재 계정은 추가로 RAG INSERT/UPDATE/DELETE를 받는다. 업무 테이블 쓰기는 허용하지 않는다. 새 DB 계정 설정은 db/init/04_rag_roles.sh다. 검색 컨테이너에 적재 DSN을 제공하지 않는다.

## 성숙도·업무 검색 분리

`get_assessment_evidence`는 성숙도 공통 문서 5종을 회사·활성 색인 범위에서 일괄 조회한다. 유사도 순위와 검색어 임베딩 없이 현재 코퍼스의 전체 19개 섹션을 확보한다. 업무는 요청 범위 내에서 `search_docs(top_k=5)`로 조회하고 해당 업무 섹션을 우선 사용한다. [단계별 검증](RAG_RETRIEVAL_IMPROVEMENT.md)을 참고한다.

## 계산과 책임

Spring이 기준 문서 §6의 AX점수·ROI·조합을 계산한다. Agent는 응답을 인용·검증하고 계산식을 두지 않는다. Confidence는 표시만, 성숙도는 별도 기업 진단이다. 데이터 패키지 examples/compute_ax.py는 오프라인 정답 생성용이다.

결과는 507·508·509, AX점수 합 265.0, 초년도 TCO 295,000,000원. 508은 선행 509를 포함하며 실제 로드맵 우선순위는 507 → 509 → 508이다. 203 최종 인사평가는 제외한다. 1년 ROI·회수 기간·3년 순편익은 보조 지표다. 합성 수치를 실제 효과로 표현하지 않는다.

## 전환과 검증

compose는 v3 corpus와 새 init SQL을 사용한다. 기존 볼륨에는 자동 적용되지 않으며 새 테스트 DB 또는 별도 검토한 migration이 필요하다. 자동 삭제·리셋은 수행하지 않았다. 내부 계산 API는 팀 Spring으로 연결한다.

`./scripts/verify_pgvector.sh`는 임시 DB, 실제 RAG/Business MCP HTTP, 고정 모델, FastAPI ASGI, PostgreSQL checkpoint 재시작·승인 재개를 검증한다. Spring은 테스트용 계약 fixture이고 LLM도 mock이다. .local/reports/agent_v3_demo.json에 이 범위를 명시한다. 목표 PostgreSQL 16과 로컬 검증 버전은 다를 수 있으므로 .local/reports/pgvector_search_v3.json의 실제 버전을 확인한다.
