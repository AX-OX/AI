# AX Navigator AI — 데이터 패키지 v3

인사·기획·개발 3개 부서, 업무 9개를 가진 직원 200명 가상 B2B 제조기업의 합성 데이터다. 모든 입력 업무 수치·솔루션 효과율·사례·성숙도 레이블은 가정이며 실제 측정 효과가 아니다. 산출 절감액은 인력 시간 환산 잠재 가치이고 확정 현금 절감이 아니다. 평가 관점을 참고했으며 수식과 가중치는 MVP 자체 설계다.

## 구성

- `contracts/`: 생성에 사용한 공통 컨텍스트·재생성 프롬프트 원본과 SHA-256.
- `sql/00_schema_postgres16.sql`: 업무 14개 테이블·FK 24개. 계약 DDL에서 단일 숫자 PK의 IDENTITY만 변경.
- `sql/01_seed_input_postgres.sql`: input·기준·사용자 시드. 분석·실행 출력은 비어 있다. 509를 508보다 먼저 INSERT하여 자기참조 FK를 만족시킨다. 시퀀스도 명시 ID 이후로 조정한다.
- `sql/03_pgvector.sql`: 같은 ax DB에 vector 확장과 RAG 테이블 2개·FK 3개 추가. 전체 16개 테이블·FK 27개. 별도 벡터 DB 서버 없음.
- `csv/`: 업무 테이블 14개 CSV. JSONB는 JSON 문자열, 불리언은 true/false, NULL은 빈 칸. 빈 출력 테이블도 헤더를 제공한다. RAG 테이블은 indexer가 채우며 CSV가 아니다.
- `fixtures/02_demo_waiting_approval.sql`: 요청자 602, 작업 1개 WAITING_APPROVAL, 평가 701. 후보·선정·runner_up 스냅샷.
- `fixtures/03_demo_after_requester_approval.sql`: 요청자 602의 가상 승인 후 로드맵 801, 항목 901~903, 프로젝트 10001~10003 등록 및 작업 DONE. 실제 승인을 대신하지 않는다.
- `config/`: AX점수, 보조 ROI, 기존과 동일한 성숙도 기준 JSON.
- `rag/docs/`: 문서 401~408 원문. `pgvector_import.jsonl`: 34개 섹션 청크. `doc_mapping.json`: 문서 소속·대표 업무·다중 업무 연결. Markdown의 page=0은 페이지 구분 없음이다.
- `eval/`: 계산 정답, B-01~B-07 평가 질의, 업무 9개 가상 전문가 레이블, 실제 PostgreSQL 검증 보고서.
- `erd/`: 업무/RAG 구분 DBML·Mermaid·PNG 및 관계 원본 JSON. 정확한 nullable/default/check/identity 계약은 SQL을 따른다.
- `examples/`: 검산·재생성·적재·검증 스크립트. 운영 Agent의 계산 모듈이 아니다.
- `ax_navigator_input_only.sqlite`, `ax_navigator_demo_approved.sqlite`: 업무 데이터 미리보기. pgvector 테이블은 포함하지 않는다.
- `quality_checks.json`: 실제 실행 결과 및 미검증 한계.

## 실행 순서

Python 3.11+ 및 vector 확장이 설치된 PostgreSQL 16을 준비한다. 예: `pgvector/pgvector:0.8.1-pg16`. 스크립트는 신규 DB에 한 번 실행하는 시드이며 기존 데이터의 migration이 아니다. 실제 로그인 사용자 두 명의 기존 BCrypt 해시를 보존했다. 로그인 ID는 `analyst1@gaon.example`, `analyst2@gaon.example`, 시연 비밀번호는 `ChangeMe123!`다. 역할 필드는 없다. 연락처는 마스킹 시연용 가상 문자열이다.

패키지 루트에서:

```bash
python examples/compute_ax.py                   # 계산 정답 출력
python examples/validate_final.py               # CSV·SQLite·문서·정답 검증, DB 연결 없음
# DATABASE_URL은 새 테스트 ax DB의 초기화 계정으로 환경에 설정
bash examples/run_postgres.sh                  # 업무 시드 + RAG DDL만
# 승인 전·후 상태까지 시연하려면 위 명령 대신:
# bash examples/run_postgres.sh --with-demo
```

애플리케이션 통합 시 먼저 backend에 sql/00, sql/01, config/*.json, eval/demo_expected_portfolio.json을 전달한다. Spring은 새 camelCase 응답·AX점수 식·선행 과제 제약·새 roadmap_items 컬럼을 구현하고 이 정답 파일로 테스트해야 한다. Agent는 계산 결과를 그대로 인용하고 사용자 승인 전 저장 도구를 실행하지 않는다.

### pgvector 적재와 검색

초기화 계정으로 sql/03_pgvector.sql을 실행한 다음 별도의 검색/적재 계정을 만든다. 비밀번호는 환경에서 설정한다. 예시 권한(계정 이름은 배포에 맞게):

```sql
-- 계정 생성과 CONNECT 권한은 배포 환경에서 설정한다.
GRANT USAGE ON SCHEMA public TO ax_rag_reader, ax_rag_indexer;
GRANT SELECT ON rag_indexes, rag_document_chunks TO ax_rag_reader, ax_rag_indexer;
GRANT SELECT(document_id,company_id,process_id,title,doc_type,access_level,version)
  ON documents TO ax_rag_reader, ax_rag_indexer;
GRANT INSERT, UPDATE, DELETE ON rag_indexes, rag_document_chunks TO ax_rag_indexer;
-- 업무 테이블의 INSERT/UPDATE/DELETE 권한을 주지 않는다.
```

```bash
python -m pip install -r examples/requirements-pgvector.txt
# RAG_INDEX_DATABASE_URL: 적재 계정으로 postgres:5432/ax 접속
# RAG_DATABASE_URL: 검색 계정으로 postgres:5432/ax 접속
# RAG_INDEX_VERSION=ax-v3-pgvector-v1
# EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
# EMBEDDING_REVISION=e8f8c211226b894fcb81acc59f3b34ba3efd5f42
python examples/pgvector_ingest.py
```

모델 파일은 최초에 다운로드가 필요하며 캐시가 있으면 오프라인으로 실행할 수 있다. 실제 임베딩은 384차원이고 JSONL에는 벡터를 넣지 않는다. `PgVectorIndex.search()`는 검색 전용 계정으로 사용한다. `score`는 cosine 거리로 작을수록 유사하며 AX점수와 다르다. API는 업무와 원문 Resource를 분리한다. 검색은 company_id·index_version으로 제한하며 업무 필터는 related_process_ids와 공통 문서([])를 함께 검색한다. 원문 답변에는 개인정보 마스킹을 적용해야 한다.

코퍼스 해시는 파일 이름 + NUL + 파일 바이트를 `pgvector_import.jsonl`, `doc_mapping.json` 순서로 SHA-256에 넣는다. 적재·검색 양쪽이 같은 규칙을 사용한다. 실제 적재는 회사·버전 단위 트랜잭션이며 실패 시 기존 색인을 보존한다. 모델·revision·코퍼스 해시가 달라지면 재색인해야 한다. 정확 검색을 사용하며 ANN 인덱스는 없다.

**이 절은 패키지 생성 시점의 기록이다. 현재 저장소의 Agent·MCP·compose는 v3로 전환되었으며 최신 상태는 루트 README와 통합 안내를 따른다.** 기존 `rag-mcp/common.py`, `index.py`는 이전 JSONL 파일명·외부 업무 매핑을 사용한다. v3 전환 시 해당 로더를 `pgvector_import.jsonl` 및 doc_mapping의 related_process_ids로 맞추고, 활성 index_version·코퍼스 해시 규칙을 적재/검색 양쪽에 맞춰야 한다. compose의 CORPUS_DIR 마운트도 v3로 바꾼다. 기존 데이터 볼륨에는 init SQL이 자동 재적용되지 않으므로 검토된 migration 또는 새로운 테스트 DB를 사용한다. 이 패키지는 기존 실행 서비스·DB·NoRole 원본을 변경하지 않는다.

## 계산 정답

| 솔루션 | 업무 | AX점수 | 초년도 TCO | 기준 회수 기간 | 기준 3년 순편익 |
|---|---|---:|---:|---:|---:|
| 507 장애 티켓 분류·배정 보조 | 207 | 97.6 | 125,000,000원 | 12.0개월 | 214,252,595원 |
| 508 기술 문서 기반 코드 리뷰 보조 | 208 | 90.4 | 115,000,000원 | 11.3개월 | 212,328,706원 |
| 509 승인형 기술·API 문서 구축 | 209 | 77.0 | 55,000,000원 | 6.3개월 | 203,951,346원 |

AX점수 합 **265.0**, 비용 **295,000,000원**, 잔여 예산 **5,000,000원**. 후보 조합 56개 중 유효 39개.

2등 [504, 507, 509]은 261.3점으로 격차는 3.7점. 단순 상위 3개 [507, 508, 504]의 비용은 360,000,000원이며, 예산 초과와 선행 솔루션 509 누락으로 탈락한다.

선행 제약은 508 → 509(508을 고르면 509도 같은 조합에 포함)다. 로드맵은 사용 가능한 과제 중 AX점수 순으로 위상 정렬하므로 507, 509, 508 순서다. 509는 문서 승인·게시 후 종료하고 508은 4개월차에 시작한다. 508·509에는 사람 최종 검토·승인 단계가 있다. 로드맵 전체 등록 승인은 이 업무별 검토와 별개다.

제외 업무는 203 인사평가 등급 산정. 501은 API가 필요 없어 API 없는 시스템에서도 apiOk=true. 505는 API가 필요하지만 연결 시스템에 API가 없어 apiOk=false이고, 표준화 수준이 최소 수준보다 낮아 LOW_STANDARDIZATION 경고가 있다. 이 경고로 추가 감점하지 않는다.

### 반올림·평가 시점

- 기준일은 재현성을 위해 2026-10-01에 고정하며 최근 완료 3개월은 2026-07~09다. `compute_ax.py --as-of YYYY-MM-DD`로 변경할 수 있다. 없는 월을 보간·생성하지 않는다.
- Decimal ROUND_HALF_UP. 원 단위 금액은 각 식을 끝까지 계산한 뒤 반올림한다. 가중 인건비·절감 시간을 중간에 반올림하지 않는다.
- AX점수는 원래 Impact·Feasibility로 계산 후 소수 1자리로 반올림하며 포트폴리오는 반환된 AX점수의 합을 최대화한다. Impact·Feasibility는 표시용 1자리, savedHoursBase는 2자리, ROI는 2자리, 회수 기간은 1자리다.
- 동점이면 기준 시나리오 3년 순편익 합 최대, 다음은 초년도 TCO 합 최소. 데이터 신뢰도 ASSUMED는 표시만 하고 점수에 넣지 않는다.
- 후보 전체(제외 업무 제외)로 Impact 정규화하며 Agent가 넘긴 일부 후보만으로 재정규화하지 않는다.
- 성숙도 영역별 점수는 문서 근거가 붙은 가상 전문가 입력이다. 전체 점수는 원본 assessment_criteria_v1.json 가중치로 계산한다. 과제 선정에는 사용하지 않는다.

## 검증·재생성

```bash
python examples/rebuild_dataset.py             # 모든 합성 입력·SQL·fixture·평가·SQLite·ERD 원본 재생성
python examples/write_package_docs.py          # 계산 결과를 읽어 README·변경 이력 생성
python examples/render_erd.py                  # PNG 생성, Pillow 필요
python examples/validate_final.py --write      # 오프라인 결과만 기록
# 실제 DB 통합 검증은 반드시 새 임시 DB에서 setup superuser로 수행:
# DATABASE_URL 설정 후 python examples/validate_postgres.py
# python examples/validate_final.py --postgres-report eval/postgres_validation.json --write
```

실제 통합 검증은 PostgreSQL **17.10** + pgvector **0.8.1**에서 완료했다. PostgreSQL 16은 로컬에 없어 목표 버전 16 자체의 실행은 미검증이다. 16개 테이블·27개 FK, SQL fixture와 SQLite/eval 일치, 실제 모델 임베딩·필터 검색·재적재·오류 롤백·최소 권한을 검증했다. `eval/postgres_validation.json`과 `quality_checks.json`이 상세 근거다. 검증 DB는 임시 생성 후 삭제했으며 패키지에 모델 바이너리나 DB 자격증명은 넣지 않았다.

`validate_postgres.py`는 신규 DB와 테스트 역할 이름을 전제로 하므로 실행 후 테스트 DB·역할을 삭제한다. 정상 운영 계정으로 실행하지 않는다. 오프라인 검증만 수행했으면 PostgreSQL 통과로 기록하지 않는다.
