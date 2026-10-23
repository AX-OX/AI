# 업무 유형 템플릿 전환 구현·연동 검증

2026-10-22. AI 작업 브랜치 `agent-enhancement`에서 구현했다. BE·FE 원본 소스는 수정하지 않았다. 운영/GCP 배포와 운영 DB 변경은 하지 않았다.

## 기준 버전과 범위

- BE: `origin/feat/catalog` **ccd6720be5872579011da48c303c9558bbc56bf5**의 Git archive 복사본. 로컬 BE develop은 2277f92 그대로다. 후보 API가 develop에 아직 없으므로 새 Agent를 기존 develop BE와 조합하면 안 된다.
- FE: 최초 연동 검증은 `origin/develop` **44ec00df1d12247cb9f1e0b9e03b93f84947e044**의 복사본으로 수행했다. 이후 **e9b50239ffcdadb93f54c0b00924d649b184c630**을 반영해 build·lint와 재실행 화면을 확인했다.
- 파일 위치: `/private/tmp/ax-catalog-integration/be`, `/private/tmp/ax-catalog-integration/fe`.
- 테스트 DB: 별도 로컬 PostgreSQL 55469의 `catalog_ax`, `catalog_agent`. 기존 로컬 DB·Cloud SQL은 변경하지 않았다.
- 시드 계산 기준일: Spring `AX_EVALUATION_AS_OF=2026-10-01`.

## 변경 내용

1. `ProcessExtract.workType` 필수 Literal 10종과 추출 프롬프트·mock 추가. 없는 숫자 추정 금지 규칙 유지.
2. Business MCP `get_solution_candidates(company_id)`와 Agent READS/collect/State 추가. 템플릿 이름·설명용 `get_solution_catalog`는 유지한다. 중첩 dependsOn도 snake_case로 변환한다.
3. Spring의 제외·지표 충족·요청 범위로 유효 후보를 제한한다. 유형 매칭·선행 업무 선택·점수·ROI·조합 계산은 Spring에 둔다. mock의 유형 매칭은 테스트 fixture용이며 운영 경로에서 사용하지 않는다.
4. 후보 키는 `(process_id, solution_id)`, LLM 후보 ID는 `S501P201`, 직렬화 사전 키는 `201:501`이다. 중복·선정·ROI 조회 결과·선행 관계·일정·검토 여부·설명 모두 쌍으로 검증한다.
5. `RoiResult.dependsOnProcessId`를 필수 nullable로 추가해 Spring 후보의 dependsOn 쌍과 비교한다. 선행 쌍이 요청 범위 유효 후보에 없으면 임의로 대체하지 않고 실패한다.
6. 후보 1~2개도 `max_items=min(3, 후보 수)`로 추천한다. 설명과 선정 수 검증도 1~3개를 지원한다. 유효 후보가 없으면 ROI 호출 없이 진단만 완료하고 지표 부족을 안내한다.
7. 시드 MANUAL 근거와 회사 UPLOADED 조각을 지원한다. LLM은 허용한 B 조각 ID만 고른다. 선택 조각의 문서·절·내용을 보존해 문서 ID만으로 인접 업무 조각을 붙이지 않는다.
8. BE의 두 CSV·DB 스키마/시드 사본을 AI 리포에 반영했다. 오프라인 시드 oracle의 숫자는 유지하고 선행 process ID를 추가했다. mock 포트폴리오는 쌍 키의 사전 계산 fixture만 조회하며 1~2개·runnerUp/greedyTop3.candidates도 지원한다.
9. 실제 BE는 USER_INPUT 지표를 계산 응답에서 SURVEY 신뢰도로 변환한다. Agent가 별도로 재분류하거나 점수에 곱하지 않는다.

## 실제 연결에서 발견하고 수정한 오류

- Business MCP의 `Any` 반환 목록은 빈 배열일 때 FastMCP content가 비어 JSONDecodeError를 일으켰다. 목록형 조회 5개를 `list[dict]`로 명시해 빈 배열도 structured result로 유지했다.
- Spring이 승인 대기 상태를 받은 직후 재개 요청을 보내면 이전 Agent turn의 최종 알림이 끝나기 전이라 409가 발생했다. 동일 interrupt·요청자 검증 후 이전 알림 완료를 최대 5초 기다리고 재개한다. 기존 turn을 취소하지 않는다.
- 기존 collect 프롬프트의 '6개' 지시로 실제 LLM이 새 필수 도구를 포함해도 시스템 조회를 빠뜨렸다. 7개 목록을 명시하고 조기 종료 시 누락 도구를 제한된 기존 루프 안에서 재요청한다.
- 새 회사 1개 추천의 실제 LLM 설명에서 스키마 검증 실패가 발생했다. respond도 strict 구조화 출력으로 변경했다. 오류 추적에는 입력·키 없이 검증 필드 위치와 오류 유형만 남긴다.

## 검증

- `.venv/bin/python -m pytest agent/tests tests -q`: 최종 149 passed / 29 skipped. skip은 별도 DB/API 환경이 필요한 검사다.
- 별도 가상환경의 `uv run --project agent --frozen python -m pytest agent/tests tests -q`도 실행했다. 상세 결과는 Git 제외 로컬 보고서 참고.
- BE 원본 복사본: Java 21 `./gradlew test bootJar --no-daemon` 성공. 61개 중 55 passed / 6 skipped / 실패 0.
- FE 원본 복사본: npm ci, build, lint 성공. 번들 500KB 초과 경고는 남아 있다.
- 한글 폰트를 포함한 텍스트 PDF를 생성해 pypdf가 한국어 문장, 120건·15분·35000원 숫자와 페이지를 보존하는지 확인했다. 스캔 OCR이나 모든 PDF 형식의 정확성을 보장하는 검사는 아니다.
- 실제 FE 프록시 → Spring → Agent → 두 MCP → PostgreSQL/pgvector 연결에서 5개 시나리오를 실행했다. 이 첫 묶음은 LLM만 MockReasoner로 고정하고 계산·저장·검색·임베딩은 실제 서비스로 실행했다.
  - 시드: 507·508·509 / AX점수 265.0 / 비용 295,000,000원 / 선행 (209,509), 승인 후 프로젝트 3개 저장.
  - 새 회사 KNOWLEDGE_QA 1개: 업로드·INDEXED·추출·확정·추천·승인·프로젝트 1개 저장.
  - 새 회사 KNOWLEDGE_QA 2개: 동일 템플릿 501의 서로 다른 업무 두 개 동시 선정·승인·프로젝트 2개 저장.
  - OTHER 또는 지표 없음: 진단만 DONE, 로드맵 없음.
- 실제 OpenAI LLM `gpt-4.1-mini`와 OpenAI 임베딩 `text-embedding-3-small`(384차원)으로도 시드와 새 회사 1개/2개 추천을 실행했다. 결과·task ID는 로컬 보고서 참고. 테스트 자료와 숫자는 합성 샘플이다.
- 실제 FE에서 로그인·이력 복원·265점·2.95억·선행 일정·등록 완료 표시를 확인했다.

## FE·BE에서 남는 범위

- 현재 FE에는 PDF 업로드/INDEXED 상태, 추출 draft 확정, workType 편집, 지표 직접 입력 화면 및 WAITING_CONFIRMATION 처리 경로가 없다. 새 회사 업로드부터 저장까지는 실제 공개 API로 검증했으며 FE 클릭만으로 완주한 것은 아니다.
- 최초 FE 검증 버전에서 solutionId 기반 선행 업무 이름 조회와 EXTRACTED 신뢰도 타입 누락을 확인했다. 이 항목은 해당 버전의 관찰이며 최신 FE 전체 재검증 결과가 아니다. Agent는 후보 쌍 기준 selected와 선행 관계를 제공한다. BE·FE 코드는 이번 작업에서 고치지 않았다.
- BE 후보/ROI/포트폴리오와 새 Agent를 함께 배포해야 한다. 기존 확정 회사의 workType backfill과 운영 migration은 BE 담당 작업이다.
- 후보가 3개 이상이어도 예산·중복 업무·선행 제약 때문에 요청 수를 채울 수 없으면 현재 계약은 insufficient다. 임의로 개수를 줄이거나 숫자를 바꿔 통과시키지 않는다.
- 후보는 최대 10개, PDF는 20MB/100페이지, RAG/LLM 입력 예산은 기존 제한을 유지한다. 업로드 백그라운드 작업의 Cloud Run 재시작 복구·작업 큐는 별도 과제다.
- 패키지의 SQLite와 전체 재생성 도구를 범용 기업 DB로 전면 전환한 것은 아니다. SQLite는 mock 성숙도 정답 조회에만 사용한다. 런타임 SQL 사본과 지정된 두 CSV·시드 정답·포트폴리오 fixture를 동기화했다.

## 로컬 실행 중

- FE: http://127.0.0.1:15184
- Spring 18102 / Agent 18103 / Business MCP 19133 / RAG MCP 19134.
- 런타임 파일·PID·상세 로그: `/private/tmp/ax-catalog-integration/runtime/`.
- Git 제외 검증 결과: `.local/reports/catalog-integration/`.
- 이 문서의 검증은 로컬 통합 환경 기준이며 운영 배포·운영 DB 변경은 포함하지 않는다.
