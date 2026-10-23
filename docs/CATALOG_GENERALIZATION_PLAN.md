# 업무 유형 기반 카탈로그 범용화: 코드 점검 및 구현 계획

> 구현 전 검토 기록이다. 최종 계약·구현·검증 결과는 [CATALOG_TEMPLATE_IMPLEMENTATION.md](CATALOG_TEMPLATE_IMPLEMENTATION.md)를 기준으로 확인한다.

기준: agent-enhancement / develop 4a7fa787, 2026-10-22. 이 문서는 설계 검토이며 기능 코드를 변경하지 않는다. BE·FE 최신 원격 구현 완료 여부는 검증하지 않았다.

## 결론

업무 유형 분류는 LLM+사용자 확정, 후보 매칭·정책·숫자 계산은 Spring, Agent는 근거 설명과 계약 검증을 맡는다. 방향은 타당하다. 다만 후보 쌍 전환은 discover뿐 아니라 설명·일정·선정 표시·응답 DTO 전체에 적용해야 한다.

## 현재 확인한 내용

- ProcessExtract에 workType이 없고 후보가 target_process_id에 결합돼 있다.
- candidate_catalog의 S{solution_id} 키: 같은 템플릿을 두 업무에 적용한 입력에서 2개 중 1개만 남는 현상을 재현했다.
- candidates_dto의 selected 판단: 같은 템플릿의 두 업무 중 하나만 선정돼도 둘 모두 selected=true가 되는 현상을 재현했다.
- evaluate, roadmap, render_answer, humanReviewBySolution도 solutionId 단독 키에 의존한다.
- 업로드 청크는 UPLOADED, section=p.N이고 related_process_ids=[]로 저장된다. retrieve는 MANUAL만 업무 검색하며 business_evidence도 MANUAL만 포함한다. candidate_catalog는 업무 ID가 붙은 시드 섹션만 허용한다. 업로드 PDF만 주면 후보 근거 부족이 재현된다.
- RoiResult.dataConfidence는 MEASURED/SURVEY/EXTRACTED/ASSUMED만 허용한다. USER_INPUT 반환 시 검증에 실패한다.
- 정책 제외는 시드 process_id=203에 의존한다. 새 회사의 사람 최종 판단 업무를 같은 규칙으로 차단할 수 없다.
- 문서 업로드·추출 draft 저장·WAITING_CONFIRMATION·확정 후 재조회 경로는 이미 존재한다.
- 예산은 최신 develop에서 질문의 선택값이다. 없으면 None으로 예산 제약을 생략한다. 이전 회사 고정 예산 방식으로 되돌리지 않는다.

## 구현 전 확정할 공통 계약

1. 후보의 유일 키는 (processId, solutionId). 같은 템플릿의 다른 업무 적용은 중복이 아니다. 같은 업무의 복수 템플릿 동시 선정은 금지한다.
2. GET /internal/companies/{companyId}/solution-candidates는 회사 범위 후보와 제외 사유를 반환한다. 메타데이터(이름/유형/가정 비용·효과율 등)도 포함하거나 별도 카탈로그 조회를 유지한다. ID 쌍만 반환하면 기존 이름·조건 설명이 불가능하다.
3. 선행 후보가 같은 부서에 여러 개일 때 선택 규칙을 확정한다. API가 선행 후보 쌍 목록을 제공하고 Spring 최적화가 하나를 선택한다면 목록은 ANY-OF인지 ALL-OF인지 명시한다. 최적화 결과와 저장 항목에는 실제 선택된 선행 쌍을 남긴다. Agent가 임의의 업무를 고르지 않는다. 누락·정책 제외·지표 부족·순환·요청 범위 밖 선행의 처리도 정한다.
4. ROI·포트폴리오 결과와 설명 응답에 processId와 solutionId를 모두 포함한다. dependsOnSolutionId만으로는 선행 업무를 식별할 수 없다.
5. 후보가 0개/1개/2개일 때의 완료 규칙을 확정한다. 현 Agent는 포트폴리오와 설명을 정확히 3개로 검증한다. 0개 진단 완료와 1~2개 추천은 별개 계약이다. 요청 부서 후보 0개와 회사 전체 후보 0개도 구분한다.
6. Impact 정규화 모집단을 회사 전체 eligible 후보인지 요청 범위인지 확정하고 Spring 한 곳에서 일관되게 사용한다.
7. 최소 표준화/API 미충족이 제외인지 경고·점수 감점인지 기존 정책을 확인한다. 명칭만 보고 필터로 바꾸면 시드 결과가 달라질 수 있다.
8. 회사/업무 ID가 아닌 위험·행위 기준 정책 제외를 Spring이 판정한다. DECISION_SUPPORT 유형 전체와 사람 최종 판단 자동화를 동일시하지 않는다.
9. USER_INPUT과 지표 기간 계약: 최근 3개 완료 월을 유지할지 명시한다. 월평균 1개를 실제 3개월 측정치로 복제하지 않는다. 지표 출처와 솔루션 비용/효과율 ASSUMED는 구분한다.

## 단계별 구현과 검증

| 단계 | 작업 | 통과 기준 |
|---|---|---|
| 1. 계약·BE | WorkType enum, 후보/선행/제외 응답, 예산·모집단·완료 규칙, DB migration 확정 | 새 회사 ID로 후보 생성; NULL/OTHER 제외; 회사 간 데이터 혼합 없음 |
| 2. DB·데이터 | 기존 업무 유형 backfill → 카탈로그 work_type 추가 → API 전환 → target_process_id 제거 | 기존 DB 업그레이드와 빈 DB 초기화 모두 성공; 비용·효과율·시드 후보 보존 |
| 3. 추출·확정 | ProcessExtract.workType enum, extract.md 설명·OTHER, FE 편집 및 Spring 저장·재조회 | 잘못된 enum 거부; 불명확 OTHER; 사용자 수정값이 collect 결과에 반영 |
| 4. MCP·collect | get_solution_candidates(company_id), normalize_read, State/Mock/READS/context 갱신 | Spring 후보 쌍·제외 사유를 손실 없이 보존; Agent가 매칭 규칙 중복 구현 안 함 |
| 5. 업무 근거 | 시드 MANUAL과 UPLOADED 모두 지원; 추출 source의 문서/페이지/청크를 확정 업무 ID에 연결 | 임의 ID의 새 회사 업무도 근거 확보; 다른 업무·회사 근거 차단; 페이지 인용 가능 |
| 6. 후보·결과 | 후보 ID를 쌍으로 구성하고 discover/evaluate/roadmap/Narrative/selected/review 키 전부 전환 | 동일 solutionId 다중 업무 유지; 선정 표시·이유·일정·승인 값 혼동 없음 |
| 7. 지표 | USER_INPUT enum·Confidence·월별 기간 및 단위 검증, 누락 목록 제공 | 입력 지표로 계산; 0건·누락·음수·기간 오류 처리; 숫자 생성 없음 |
| 8. 연동·배포 | 실제 Spring+Agent+MCP+PostgreSQL+FE 업로드부터 승인까지, 동일 버전 이미지/환경 배포 | 시드 수치 회귀 및 새 회사 분석 성공; 승인 전 등록 없음; 잘못된 DONE은 Spring 차단 |

## 수정할 AI 파일

- agent/app/schemas.py: WorkType, ProcessExtract, 후보·선행 쌍 DTO, Recommendation(process_id 추가), USER_INPUT 계약.
- agent/prompts/extract.md / discover.md / respond.md: 분류 설명, 서버 후보·쌍 기반 인용, 가정값 표시.
- business-mcp/server.py, agent/app/clients/mcp.py, contracts.py, models/state.py: 후보 도구와 상태·응답 변환.
- agent/app/candidate_refs.py, contexts.py, reasoning.py: 후보 ID/전체성/근거 연결, mock 전환.
- agent/app/graph/nodes/implemented.py: 쌍 검증·선행·일정·승인·설명·종료 검증.
- agent/app/presentation.py: 쌍 기반 selected와 이름·근거 표시.
- agent/app/mock.py, agent/tests, tests/test_rag_strategy.py: 새 회사·동일 템플릿 다중 업무·선행 조합 회귀.

## PDF·Cloud 추가 확인

- pypdf는 ingest.py에서 텍스트 PDF를 읽는다. 20MB/100페이지 제한, 업로드 청킹 1,200자·겹침 없음. 스캔 PDF는 OCR 범위 밖이며 텍스트가 없으면 명확히 실패시킨다.
- 기존 PDF 단위 검사는 영문 합성 PDF 중심이다. 실제 한글 폰트 PDF의 페이지·표 수치·줄바꿈·빈 페이지를 확인해야 한다.
- 성숙도 공통 근거 200개/추출 근거 400개와 LLM 문자 예산은 별도 제약이다. 큰 PDF가 모두 들어간다는 보장은 없으므로 경계·오류 표시를 검증한다.
- 현재 업로드는 메모리의 asyncio 작업이다. Cloud Run 요청 종료 이후 실행 보장과 재시작 시 복구가 없다. 운영 업로드는 내구성 있는 작업 큐/재처리 설계를 별도 반영한다.
- rag-mcp 업로드 실행에는 RAG_INDEX_DATABASE_URL과 색인 role 쓰기 권한, OPENAI_API_KEY가 필요하다. 시드 전용 Job 설정과 구분한다.
- AX_EVALUATION_AS_OF=2026-10-01은 Spring 계산 서비스 설정이다. 시드 회귀 기준일로 고정하고 새 회사의 입력 월과 일치 여부를 확인한다.
- 기존 DB에는 init SQL 수정만으로 컬럼이 추가되지 않는다. migration과 시드/정책/정답 파일의 버전 동기화가 필요하다.

## 최소 회귀 시나리오

1. 시드 예산 3억, 기준일 고정: 이전 코드에서 얻은 후보 수·선정 쌍·비용·점수·선행·ROI를 동일 입력으로 비교.
2. 새 회사의 서로 다른 업무 두 개가 동일 템플릿을 사용해도 둘 다 유지되고 올바른 하나만 선정 표시.
3. 동일 부서의 선행 후보 1개/여러 개/없음 및 다른 부서 선행만 있는 경우.
4. OTHER/NULL, 정책 제외, 지표 없음, 표준화/API 조건 미충족의 각각의 사유.
5. PDF → INDEXED → 추출 → 사용자 유형·지표 수정 → 확정 → 재조회 → 추천 → 승인 → 로드맵/프로젝트 저장.
6. 승인 없는 DONE 요청: 회사 후보가 존재하면 거부, 실제 0개일 때만 합의된 진단 완료 허용.
7. 예산 있음/없음 및 후보 0·1·2·3·10개 초과 경계.
