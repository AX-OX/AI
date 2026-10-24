# AI VM 자동 배포

`main`에 PR을 병합하면 Cloud Build가 `cloudbuild.vm.yaml`을 실행한다.

1. 기존 Dockerfile로 Agent·Business MCP·RAG MCP 통합 이미지를 빌드하고 `pip check`를 수행한다.
2. 네트워크를 차단한 컨테이너에서 Python 소스 구문을 검사한다.
3. 기존 Artifact Registry에 커밋 SHA 태그로 게시하고 digest를 조회한다.
4. IAP SSH로 VM `axox-vm-20261024`의 `agent` 컨테이너만 교체한다.
5. 컨테이너 health와 기존 `verify-runtime.py`의 BE·AI·DB·RAG 연결 점검을 수행한다.

배포 스크립트 `/opt/axox-vm/update-service.sh`는 BE와 공용 잠금을 사용해
동시 배포를 직렬화하고, 새 컨테이너가 정상 기동하지 못하면 이전 이미지로 복구한다.
후속 연결 점검 실패는 Cloud Build 실패로 보고되며, 이 점검 자체가 롤백을 수행하지는 않는다.

BE에서 설정한 빌드 서비스 계정과 IAP 권한, 단기 SSH 로그인 `be-cicd`를 재사용한다.
SSH 키는 배포마다 생성하며 30분 후 만료한다. JSON 서비스 계정 키나 GitHub 시크릿 추가는 필요 없다.
애플리케이션 시크릿과 DB 연결 설정은 VM의 기존 Compose 환경을 그대로 사용한다.
`SPRING_INTERNAL_URL=http://backend:8080/internal`이 이미지 기본값보다 우선한다.
Cloud Run 배포, DB 초기화, 시드 재색인은 실행하지 않는다.

## GCP 트리거 설정

기존 AI 트리거 ID `2eafeb89-8581-47f8-a5f9-6b0a5db244f2`를 다음 설정으로 연결한다.

- 프로젝트/리전: `my-project-axox` / `global`
- 저장소/분기: `AX-OX/AI` / `^main$`
- 빌드 구성: 저장소의 `cloudbuild.vm.yaml` (기존 Cloud Run 인라인 구성 제거)
- 서비스 계정: `853402721456-compute@developer.gserviceaccount.com`
- 상태: 사용 설정

PR 병합 전에는 main에 설정 파일이 없으므로 배포를 수동 실행하지 않는다.
검토 후 이 PR을 main에 병합하면 첫 자동 빌드·배포가 시작된다.
Agent 재시작으로 진행 중인 분석이 중단될 수 있으므로 분석 작업이 없는 시점에 병합한다.
