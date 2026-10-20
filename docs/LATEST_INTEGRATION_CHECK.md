# 최신 BE·FE 연동 점검

점검일: 2026-10-20. 각 저장소의 develop을 fast-forward로 갱신했다.

| 대상 | 커밋 | 변경 |
|---|---|---|
| BE | `f1ad23a` | Cloud SQL 설정·YAML 환경 변수·DB 연결 검증 |
| FE | `4d2d97d` | AX점수 화면·작업 이력 복원·세션 만료·로그아웃/SSE 정리 |

BE·FE의 원격 코드만 가져왔으며 직접 소스를 수정하지 않았다. 갱신 후 추적 파일 219개의 SHA-256이 빌드·검사 전후 일치한다. 기존 BE 내부의 미추적 `BE/` 폴더도 그대로 보존했다. 빌드·실행은 별도의 임시 복사본에서 수행했다.

## 확인한 흐름

- BE 테스트·bootJar, FE 타입 검사·Vite 빌드·lint 통과.
- 실제 Spring 작업 생성 → Agent → Business MCP 조회·계산·저장.
- 실제 RAG MCP → 34개 청크의 pgvector 검색.
- SSE 도구 이벤트·검증된 TOKEN 설명·승인 대기 수신.
- 승인 후 실제 임시 DB에서 로드맵 1개·프로젝트 3개 저장 및 DONE 확인.
- 거절 작업은 REJECTED이며 로드맵 생성 0개 확인.
- 최신 FE의 실제 chatStore·API·SSE 모듈로 후보 8개·AX점수 합 265.0·승인/거절 상태 확인.
- 작업 이력에서 DONE 작업을 복원해 서버 승인 기록과 완료 배지가 유지되는지 확인.
- 근거 문서 조회, 다른 사용자 403, 로그아웃 시 대화·문서·저장된 세션 정리, 실제 잘못된 JWT의 401과 expired 상태 확인.
- React SSR에서 일반 승인 대기·후보 스냅샷 도착 전 승인 카드·이력 복원 완료 화면을 렌더링했다. NaN 없이 3년 순편익과 프로젝트 3건을 표시했다.
- Agent·MCP·pgvector·PostgreSQL 체크포인터 회귀 검사 65개 통과.

## Agent 측 보완

BE·FE를 변경하는 대신, 최신 FE의 타입에 맞춰 표시 응답만 보완했다.

1. `roadmap.items[].threeYearNetValueKrw`: Spring 도구의 검증된 기준 시나리오 3년 순편익을 그대로 제공한다. 기존 `threeYearNetKrw`도 호환용으로 유지한다. 후보 스냅샷 도착 전에도 로드맵 카드가 값을 표시할 수 있다.
2. `candidates[].evidence`: 실제 후보가 인용한 문서와 검색된 근거에서 documentId·제목·절·요약을 제공한다. 근거를 새로 만들거나 계산하지 않는다.

## 남은 제한

- BE 성숙도 저장 응답은 여전히 assessmentId만 반환한다. totalScore를 임의 계산하지 않으므로 총점 차트는 생략된다.
- 이전 FE에 있던 ROI 우선순위 문구는 최신 FE에서 AX점수 기준으로 수정되었다. 이전 점검의 해당 지적은 더 이상 적용되지 않는다.
- LLM은 MockReasoner를 사용했다. 실제 OpenAI 응답 품질 검사는 포함하지 않는다.
- FE 모듈은 Node의 브라우저 타이머·localStorage shim과 React SSR로 검사했다. 실제 브라우저 클릭·레이아웃 검사는 아니다.
- GCP/Cloud SQL에는 연결하지 않았다. BE의 새 설정을 명시적인 로컬 DB 환경 변수와 local 프로필로 실행했다. DB는 격리한 PostgreSQL 17 / pgvector 0.8.1이며 운영 데이터는 변경하지 않았다.

로컬 상세 보고서는 `.local/reports/latest_integration_summary.json`, `latest_backend_e2e.json`, `latest_fe_integration.json`이다. Git에서는 제외한다. 이번 Agent 보완은 아직 커밋·푸시하지 않았다.
