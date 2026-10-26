# GCP 운영 모니터링

기존 `/opt/axox-vm`의 live Agent를 수집한다. 로컬 Iris 및 mock Agent는 배포하지 않는다.
설치된 Grafana는 `https://<SITE_ADDRESS>/grafana/`에서 로그인 후 접속한다.

## 적용

운영 VM에서 root로 실행한다. Agent 이미지에 `/opt/axox-monitoring-package`가 포함되며,
`cloudbuild.vm.yaml`은 Agent 배포 및 기존 연동 검증 후 이 패키지를 꺼내 설치한다.
수동 설치 시 저장소 전체의 `ops/monitoring/install.py`를 실행할 수도 있다.

```sh
sudo python3 /opt/axox-monitoring-package-next/install.py
sudo python3 /opt/axox-monitoring-package-next/install.py --verify
sudo python3 /opt/axox-monitoring-package-next/install.py --test-alert
```

기존 배포와 같은 `/run/lock/axox-vm-deploy.lock`을 사용한다. 최초 설치 시 실행 중인
Agent 작업이 없을 때 `METRICS_TOKEN`을 추가하고 Agent를 한 번 재생성한다. 이때 짧은
중단이 발생할 수 있다. 이후 설치에서는 동일 토큰·Grafana 비밀번호·데이터 볼륨을 유지한다.
DB 초기화, 문서 재색인 및 임의의 LLM 호출은 실행하지 않는다.

## 확인할 수 있는 지표

`AXOX Production / AX Agent · GCP Production` 대시보드에 Agent 준비 상태, live 모드,
HTTP 요청·오류·지연, 실행 결과, LLM 호출·오류·응답 시간·입출력 토큰, 도구 호출,
Agent 프로세스 CPU 및 RSS를 표시한다. 토큰은 제공자가 보고한 값만 누적한다.
요청이 없으면 해당 지표가 비어 있을 수 있다. CPU·RSS는 Agent 프로세스이며 VM 전체가 아니다.
프로세스 재시작 시 카운터는 초기화되지만 Prometheus의 기존 시계열은 유지된다.

Prometheus는 15초마다 수집하고 시계열을 최대 7일/1GB 보관한다. 컨테이너 메모리
상한은 Prometheus 256MiB, Grafana 256MiB, Alertmanager 64MiB, 수신함 96MiB다.
운영 환경이 4GiB 단일 VM이므로 실제 사용량을 확인하며 조정한다.

## 인증과 알림

Grafana 익명 접근과 가입을 차단한다. 사용자 이름은 `axox-admin`, 초기 무작위 비밀번호는
VM의 `/opt/axox-monitoring/grafana-access.txt`에 root 전용으로 보관한다. 비밀번호는 Git,
Cloud Build 로그, URL 및 컨테이너 환경 변수에 넣지 않는다. 로그인 정보 파일을 안전한
경로로 받아 사용하고 팀 사용자 계정은 Grafana에서 별도로 관리한다.

Prometheus·Alertmanager·알림 수신함은 호스트 포트를 열지 않는다. Grafana는 기존 Caddy
HTTPS 경로를 통해서만 공개한다. Agent `/metrics`는 전용 Bearer 토큰을 사용한다.
운영 방화벽과 DB 접속 설정은 기존 구성을 사용한다.

알림 조건은 수집 실패/미준비 1분, 서버 오류 비율 10% 초과(5분간 최소 10건, 2분 유지),
5분간 LLM/도구 오류 3건 이상(1분 유지), RSS 1.5GiB 초과(5분 유지)다. Alertmanager는
발생·해제 웹훅을 독립 수신함 SQLite에 최대 200개 저장한다. Grafana의 Active alerts에
현재 상태가 표시된다. Slack·메일 등 외부 통지는 설정하지 않았다.

```sh
sudo docker exec axox-monitoring-alert-inbox-1 python -c \
  'import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:8000/alerts").read().decode())'
sudo docker stats --no-stream
```

## 복구

설치 전 Caddyfile·Agent env·기존 모니터링 설정은
`/opt/axox-monitoring/backups/<UTC timestamp>/`에 저장한다. 설치 실패 시 Caddy 경로와
이번에 추가한 Agent 토큰을 복구하고 기존 모니터링 설정을 되돌린다. 첫 설치 실패 시에는
모니터링 컨테이너만 정지한다. 실패 로그는 `/opt/axox-monitoring/last-error.log`에 root
전용으로 저장한다. 데이터 볼륨을 삭제하지 않는다.

운영 모니터링만 중지하려면 모니터링 Compose에 `stop`을 사용한다. Agent·백엔드에는
영향을 주지 않는다. `/grafana/` 경로 제거는 백업 Caddyfile을 검토한 뒤 복구하고
`caddy validate` 및 `caddy reload`를 실행한다.

## 최초 운영 검증 (2026-10-26)

기존 GCP VM에 적용 후 Agent `mode=live`, PostgreSQL 체크포인트, Prometheus의
Agent/self 대상 `UP`, 준비 상태 1, HTTPS Grafana 로그인 및 인증된 대시보드 조회를 확인했다.
합성 알림의 발생·해제 모두 독립 수신함에 저장됐으며, 기존 백엔드·Agent·RAG reader/indexer의
PostgreSQL 연결 검사와 인증된 RAG MCP 검사도 통과했다. 테스트용 장애나 LLM 호출은 만들지 않았다.

운영 주소: `https://axox.34.104.191.144.sslip.io/grafana/d/ax-agent-monitoring`.
VM의 임시 외부 IP가 바뀌면 기존 애플리케이션과 함께 `SITE_ADDRESS`를 갱신해야 한다.
