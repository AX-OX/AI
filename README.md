# AX Navigator AI

FastAPI·LangGraph Agent, Business/RAG MCP, PostgreSQL·pgvector 데이터 패키지입니다. 팀원 Agent 뼈대에 실제 노드를 연결했고, Spring이 업무 데이터 조회·AX점수/ROI·포트폴리오 계산·승인·결과 저장을 담당합니다.

## 저장소 구조

```text
agent/                       # 기존 팀원 구조 + 실제 노드·MCP 연결·FastAPI
business-mcp/                # Spring 내부 API를 Agent 도구로 제공
rag-mcp/                     # PostgreSQL pgvector 문서 검색·색인
AX_Navigator_AI_MVP_v3/      # 현재 시연 데이터·정책·계산 정답·문서
db/                        # PostgreSQL 초기화 SQL·계정·ERD
scripts/                     # 로컬 채팅·데이터 fixture 생성·통합 검사
tests/                      # 공통 MCP 계약 검사
docs/                        # 실행·연동·데이터 재생성 문서
AX_NAVIGATOR_CONTEXT.md       # 공통 기준 문서
compose.yaml                 # PostgreSQL·MCP·Agent 구성 (Spring은 별도)
.env.example                 # 환경 변수 예시, 실제 .env는 Git 제외
```

`agent/`를 새 `AI/AI/` 폴더에 다시 감싸지 않고 기존 팀원 경로에 합칩니다. Agent는 루트의 v3 데이터와 MCP 서비스를 사용하므로 `agent/`만 업로드해서는 전체 실행에 필요한 파일이 갖춰지지 않습니다.

## 로컬 Agent 확인

프로젝트 루트에서:

```sh
uv sync --project agent --locked
# 키 없이 시연 데이터와 가상 등록으로 실행
uv run --project agent python scripts/chat_agent.py --mode mock
# 실제 OpenAI + 시연 도구: .env에 OPENAI_API_KEY, LLM_MODEL 설정
uv run --project agent python scripts/chat_agent.py
```

질문은 한 줄로 입력하거나 `/multi` → 여러 줄 질문 → `/send`를 사용합니다. `exit`로 종료합니다. CLI는 y/n 없이 가상 등록까지 진행하며 실제 DB에는 쓰지 않습니다.

## 실제 서비스 연결

`.env.example`을 참고해 `.env`를 설정합니다. 실제 키·비밀번호를 코드에 넣지 않습니다.

- `AGENT_MODE=live`: 실제 LLM·Business MCP·RAG MCP·PostgreSQL 체크포인터.
- `SPRING_INTERNAL_URL`: Spring의 `/internal` 주소.
- `BUSINESS_MCP_URL`, `RAG_MCP_URL`, `AGENT_DATABASE_URL`: Agent에서 접근 가능한 서비스 주소.
- `INTERNAL_TOKEN`: Spring·Agent·Business MCP에 동일하게 설정.
- Spring은 `AGENT_ENABLED=true`, `AGENT_BASE_URL`을 설정합니다.

```sh
uv run --project agent uvicorn agent.app.main:app --port 8000 --workers 1 --http h11
```

`--http h11`은 Java HttpClient의 h2c 업그레이드 요청과의 호환을 위해 필요합니다. Docker 명령에도 적용되어 있습니다. 실제 서비스는 FE → Spring 작업/승인 API → Agent 순서로 호출합니다. FE에 내부 토큰이나 OpenAI 키를 전달하지 않습니다.

`compose.yaml`은 PostgreSQL·MCP·Agent를 구성하며 팀원 Spring·FE는 포함하지 않습니다. 기존 DB 볼륨에 초기화 SQL을 다시 적용하거나 볼륨을 자동 삭제하지 않습니다.

## 고객사 PDF와 예산 (BE #21~#26 계약)

- **예산**: 질문에 적힌 금액(예: "예산 3억 원 내에서")만 예산으로 쓴다. collect가 추출해 `PATCH /internal/tasks/{id}` `budgetKrw`로 저장하고 `optimize_ax_portfolio`에 `budget_krw`로 넘긴다. 없으면 예산 제약 없이 선정하고 응답의 `budgetKrw`, `remainingBudgetKrw`는 null이다. 회사 `ax_budget_krw`는 계산에 쓰지 않는다.
- **PDF 색인**: Spring이 `POST /documents/{id}/ingest`(multipart `companyId`, `fileName`, `contentType`, `file`)로 PDF를 보낸다. Agent가 페이지 텍스트를 뽑아(최대 100페이지) rag-mcp `index_document`로 회사 업로드 색인에 저장하고, `PATCH /internal/documents/{id}`로 `INDEXED`(pages 포함) 또는 `FAILED`를 돌려준다. 원본 PDF는 저장하지 않는다.
- **기업 데이터 추출과 확정**: run 요청의 `companyDataConfirmed`가 false면 extract 노드가 `documentIds` 문서에서 부서, 업무, 지표, 시스템을 추출해 `save_extraction`(`POST /internal/extractions`)으로 저장하고 `CONFIRMATION_REQUIRED` 이벤트를 보낸 뒤 멈춘다. 사용자가 Spring에서 확정하면 Spring이 `POST /tasks/{id}/confirm` `{userId}`로 재개하고 collect부터 진행한다. 지표는 문서에 숫자로 적힌 것만 추출한다.
- **성숙도만으로 종료**: 확정한 업무를 대상으로 하는 솔루션이 카탈로그에 없으면 discover에서 성숙도 진단 결과로 DONE을 보낸다(로드맵 없음).
- **RAG 회사 범위**: `search_docs`, `get_assessment_evidence`, `get_document_chunks`는 `company_id`로 검색한다. 업로드 문서는 `RAG_UPLOAD_INDEX_VERSION`(기본 `<RAG_INDEX_VERSION>-uploads`)에 저장되어 시드 재색인이 지우지 않는다. rag-mcp 서비스에 `RAG_INDEX_DATABASE_URL`(색인 계정)이 있어야 업로드 색인이 된다.

## OpenAI 문서 임베딩

문서·검색어 모두 `text-embedding-3-small` API를 사용한다. pgvector는 기존 `vector(384)`를 유지하고 API에 `dimensions=384`를 지정한다. 로컬 모델 다운로드는 필요 없다. 기존 MiniLM 벡터는 재사용할 수 없으며 [전환·재색인 안내](docs/OPENAI_EMBEDDINGS.md)를 따른다.

## 검사

```sh
uv run --project agent python -m pytest agent/tests tests -q
# 실제 OpenAI 임베딩 호출 포함 (.env의 OPENAI_API_KEY 필요)
sh scripts/verify_pgvector.sh
```

통합 검사 스크립트는 임시 PostgreSQL·실제 MCP/pgvector/체크포인터를 사용하고 Spring·LLM은 fixture입니다. 최신 실제 Spring과 FE 채팅 모듈로도 승인·실제 저장·거절을 확인했습니다. 자세한 검증 범위와 미완료 표시 사항은 [통합 안내](docs/TEAM_AGENT_ALIGNMENT.md)를 참고하세요.

## 문서와 로컬 보관

- [Agent 구조·실행](agent/README.md)
- [팀원 코드 통합·BE/FE 계약](docs/TEAM_AGENT_ALIGNMENT.md)
- [최신 BE·FE 연동 점검](docs/LATEST_INTEGRATION_CHECK.md)
- [실제 LLM 시연](docs/LLM_DEMO.md)
- [pgvector 저장·검색](docs/PGVECTOR_AND_OPPORTUNITY.md)
- [RAG 검색·근거 ID 개선 및 단계별 검증](docs/RAG_RETRIEVAL_IMPROVEMENT.md)
- [데이터 재생성 요구사항](docs/DATA_REBUILD_PROMPT.md)
- [GitHub 업로드 범위](docs/REPOSITORY_LAYOUT.md)

이전 패키지·참고 코드·중복 산출물은 `.local/archive/`, 실행 보고서는 `.local/reports/`에 로컬 보관하며 업로드하지 않습니다. 현재 v3 패키지의 SQLite 파일은 mock 실행이 읽는 시연 입력이므로 유지합니다.

### 업무 유형 템플릿 카탈로그

업무 유형 `workType` 추출과 Spring 후보 API를 사용한다. 후보·선행·설명은 `(processId, solutionId)` 쌍으로 구분하며, 템플릿 조회는 이름·조건 설명용으로 유지한다. 새 회사는 확정한 지표가 있는 유효 후보 1~3개를 추천하고, 유효 후보가 없으면 성숙도 진단만 완료한다. 계산·최적화는 Spring이 수행한다.

- [작업 계약](docs/CATALOG_TEMPLATE_TASK.md)
- [구현·실제 BE/FE 연동 검증과 남은 범위](docs/CATALOG_TEMPLATE_IMPLEMENTATION.md)

새 후보 API를 제공하는 BE 버전과 함께 배포해야 한다. 현재 FE에 업로드·추출 확정 화면이 없으므로 새 회사 전체 경로는 API로 검증했다.

### 선택 기능: Tavily 외부 참고 자료

`TAVILY_API_KEY`를 설정하면 live 모드에서 선정 과제의 외부 참고 자료를 Tavily MCP로 검색해 기존 답변 끝에 표시합니다. 키가 없거나 검색이 실패해도 기본 분석을 유지하며 AX점수·ROI에는 반영하지 않습니다. [설정·제약·검증](docs/TAVILY_MCP.md)을 참고하세요.
