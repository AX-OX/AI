# 모델 서빙과 AX Agent 모니터링

**Iris는 꽃의 네 가지 측정값으로 품종을 분류하는 scikit-learn 내장 예제**입니다.
AX의 pgvector에 저장된 문서·임베딩과 관계가 없습니다. 이 예제는 장애와 부하를 안전하게 만들어 보는 용도입니다.
별도의 **AX Agent Monitoring** 대시보드에서는 실제 `agent/app` 코드에 추가한 계측을 확인합니다.

## 실행과 화면

Docker Desktop 실행 후 AI 저장소 루트에서:

```sh
docker compose -f model-serving/compose.yaml up --build -d
```

| 화면 | 주소 | 용도 |
| --- | --- | --- |
| Iris 대시보드 | http://127.0.0.1:3001/d/iris-model-serving | 예측·모델 정보·자원·경고 |
| AX Agent 대시보드 | http://127.0.0.1:3001/d/ax-agent-monitoring | 작업·LLM·도구·Agent 자원 |
| Iris API | http://127.0.0.1:8001/docs | 예측·모델 정보·실습 장애 제어 |
| Agent API | http://127.0.0.1:8002/docs | 기존 내부 Agent API |
| 로컬 알림 수신함 | http://127.0.0.1:8003/alerts | 실제로 수신한 firing/resolved 알림 JSON |
| Alertmanager | http://127.0.0.1:9094 | 알림 그룹·현재 상태 |
| Prometheus | http://127.0.0.1:9091 | 수집 상태·규칙 평가 |

Grafana는 익명 Viewer로 확인하며 데이터소스·두 대시보드를 자동 등록합니다.
모든 공개 포트는 `127.0.0.1`에만 바인딩합니다. API 키·GPU·외부 DB가 없는 기본 실행은 Agent **mock 모드**입니다.
기존 AX Agent/BE/FE 배포를 변경하지 않고 독립 Compose 프로젝트로 실행합니다.
첫 빌드에는 이미지와 패키지를 받는 인터넷 연결이 필요합니다.

## 1. 테스트 요청 발생

Python 표준 라이브러리만 사용하는 도구입니다. 저장소 루트에서:

```sh
python3 model-serving/load_test.py --scenario normal
python3 model-serving/load_test.py --scenario invalid
python3 model-serving/load_test.py --scenario mixed
python3 model-serving/load_test.py --scenario load
python3 model-serving/load_test.py --scenario slow
python3 model-serving/load_test.py --scenario failure
```

- `normal`: 정상 예측 100건, 동시 2개.
- `invalid`: 잘못된 입력 100건, HTTP 422 확인.
- `mixed`: 100건 중 20%를 잘못된 입력으로 전송.
- `load`: 정상 예측 500건, 동시 16개.
- `slow`: 예측당 500ms의 **모의 지연**을 넣고 200건 전송.
- `failure`: 두 번째 예측마다 **모의 HTTP 503**을 반환하며 300건 전송.

`--requests 200 --concurrency 8 --interval 0.1`로 조절할 수 있습니다. 최대 요청은 1,000건, 동시는 16개입니다.
로컬 HTTP 주소만 허용하며, AX Agent나 LLM에 부하를 보내지 않습니다.
결과에는 상태 코드별 건수와 클라이언트 관측 p95가 나옵니다. Grafana p95는 HTTP 히스토그램 추정치여서 값이 다를 수 있습니다.
`slow`/`failure`는 종료 시 설정을 원복합니다. 강제 종료나 서버 장애로 원복에 실패하면 아래 명령을 사용하세요.

```sh
curl -sS http://127.0.0.1:8001/demo/control -H 'Content-Type: application/json' -d '{}'
```

모의 지연·실패 API는 `ENABLE_DEMO_CONTROLS=true`일 때만 활성화됩니다. 로컬 Compose만 활성화하며 기본 이미지에서는 꺼져 있습니다.
정상 예측 입력 순서는 **꽃받침 길이·너비, 꽃잎 길이·너비(cm)**입니다.

```sh
curl -sS http://127.0.0.1:8001/predict -H 'Content-Type: application/json' \
  -d '{"features":[5.1,3.5,1.4,0.2]}'
```

## 2. CPU·메모리

Iris와 AX Agent에 Prometheus ProcessCollector를 등록했습니다.
각 대시보드에서 **프로세스 CPU 사용률**과 **상주 메모리(RSS)**를 확인합니다.
CPU 100%는 코어 하나를 전부 사용하는 값입니다. 호스트 전체나 컨테이너 전체 사용량이 아닙니다.
Linux 컨테이너에서 수집하며 macOS Python 직접 실행에서는 process 지표가 없을 수 있습니다.
요청률·지연·자원 변화를 함께 비교할 수 있습니다. 스크레이프는 5초, CPU는 최근 1분 변화량입니다.

## 3. 장애 알림

```text
Prometheus 규칙 평가 → Alertmanager → 독립 로컬 알림 수신함(SQLite)
                           ↓
                  발생(firing)·복구(resolved) 알림
```

모델 서버가 내려가도 수신함은 별도 프로세스에서 동작합니다. 수신 알림은 전용 볼륨에 최대 200개 보관하고 API는 최근 100개를 제공합니다.
외부 Slack·이메일 계정으로 전송하지 않습니다. 외부 수신 채널은 사용자가 목적지를 정하면 추가할 수 있습니다.

| 규칙 | 조건 |
| --- | --- |
| ServingTargetDown | Iris 또는 Agent 수집 실패가 15초 지속 |
| ModelNotReady | 모델 준비 상태 0이 15초 지속 |
| ModelHighErrorRatio | 최근 1분 10건 이상 요청 중 HTTP 5xx 비율 10% 초과, 15초 지속 |
| ModelSlowRequests | 최근 1분 10건 이상 요청에서 p95 300ms 초과, 15초 지속 |
| AgentLLMErrors | 최근 2분 LLM 실패 시도 3회 이상, 15초 지속 |
| AgentToolErrors | 최근 2분 도구 실패 3회 이상, 15초 지속 |

HTTP 422는 입력 오류 그래프에는 포함하지만 서버 장애 알림에는 포함하지 않습니다.
규칙은 5초마다 평가하고 최초 알림은 그룹 대기 5초를 더해 전달됩니다. 장애 해소 후에도 1~2분 통계창이 남아 있으므로 즉시 복구 알림이 나오지 않을 수 있습니다.
같은 미복구 경고의 반복 통보 간격은 4시간입니다.

```sh
# 약 25~40초 후 ServingTargetDown 알림 확인
# 확인 후 반드시 다시 시작합니다.
docker compose -f model-serving/compose.yaml stop model
# http://127.0.0.1:8003/alerts 확인
docker compose -f model-serving/compose.yaml start model
```

Grafana의 `Firing alerts`와 `Active alert details`는 Prometheus의 현재 상태, 수신함은 실제 전달 기록입니다.

## 4. 모델 정보

`GET /model`과 대시보드에 다음을 노출합니다.

- 이름·버전, 데이터셋 출처, 입력 필드 순서, 클래스 목록.
- 이미지 빌드 중 학습한 시각과 서버가 모델을 로드한 시각.
- 학습 120건/테스트 30건, 빌드 시 holdout 정확도.

정확도는 실시간 예측의 품질이 아닙니다. 정답 수집·드리프트·버전 비교는 구현 범위에 포함하지 않습니다.
아티팩트는 이 프로젝트가 이미지 빌드 중 생성한 파일만 로드합니다.

## 5. 실제 AX Agent 계측

변경 위치는 `agent/app/telemetry.py`와 기존 FastAPI·TaskRunner·Reasoner·Gateway 실행 경로입니다.
별도의 가짜 Agent 지표 서버가 아니라 **기존 Agent 애플리케이션이 자신의 동작을 측정**합니다.

| 지표 | 의미 |
| --- | --- |
| 모드·설정 모델·준비 상태 | 현재 프로세스가 어떤 방식으로 동작하는지 |
| HTTP 요청/시간 | 경로 템플릿과 상태 코드별 집계 |
| 실행 결과·동시 실행·시간 | DONE, FAILED, 승인/기업정보 확정 대기, 거절, 취소 |
| LLM 시도·p95 | 단계·설정 모델별 실제 호출, 재시도도 각각 집계. 재시도 대기 시간 제외 |
| 입력·출력 토큰 | provider가 보고한 usage만 누적. 추정값 생성 없음 |
| 도구 성공·실패·지연 | Gateway의 논리 도구 호출. 내부 재시도는 한 호출의 지연에 포함 |
| CPU·RSS | Agent 프로세스 자원 |

작업은 승인에서 멈췄다가 재개하므로 **실행 구간**을 셉니다. 성공 비율은 DONE/(DONE+FAILED) 구간 기준이며 승인 대기·거절·취소는 제외합니다.
영속 복구의 재실행도 각각 집계하므로 고유 작업 수와 같지 않습니다.
프롬프트·문서 내용·사용자/회사/작업 ID·토큰 문자열·원문 오류는 메트릭 라벨에 넣지 않습니다.
`/metrics`는 `Authorization: Bearer <METRICS_TOKEN>`이 필요하며 미설정 시 기존 내부 토큰을 사용합니다.
운영에서는 전용 METRICS_TOKEN과 Prometheus `authorization.credentials_file`을 사용하세요.

기본 로컬 모드는 명확히 구분됩니다.

- **mock**: 실제 Agent 실행 + fixture 도구. OpenAI·pgvector 네트워크 호출 없음. LLM/토큰 패널은 데이터 없음.
- **llm-demo**: 실제 OpenAI 호출 + fixture 도구. provider 토큰·LLM 지연을 확인할 수 있음.
- **live**: 실제 OpenAI + MCP + pgvector + PostgreSQL 체크포인터. 해당 서비스 연결과 키가 필요.

API 키 없이 Agent 실행 흐름을 재현하려면:

```sh
python3 model-serving/agent_demo.py
```

로컬 mock 모드에서만 동작하며 `WAITING_APPROVAL → DONE`까지 가상 승인·등록합니다. 실행 결과·도구 호출·자원 패널을 확인하세요.

실제 LLM을 로컬에서 관측하려면 별도 비공개 env 파일에 `OPENAI_API_KEY`, `LLM_MODEL`, `INTERNAL_TOKEN`을 설정하고:

```sh
docker compose --env-file /absolute/path/to/private.env \
  -f model-serving/compose.yaml -f model-serving/compose.agent-live.yaml up --build -d
```

기본은 `llm-demo`이며 실제 API 사용량이 발생합니다. 이 경우 요청은 Agent `/docs`에서 실제 내부 토큰으로 보내세요.
`AGENT_MODE=live`로 전환할 때는 `AGENT_DATABASE_URL`, `SPRING_INTERNAL_URL`, `BUSINESS_MCP_URL`, `RAG_MCP_URL`도 설정해야 합니다.
이 override는 로컬 전용 Prometheus 인증을 그대로 사용하며 운영 배포 설정이 아닙니다.
기존 VM 운영 Agent를 관측하려면 이 계측 코드 배포 후, 내부 네트워크에서 그 Agent를 스크레이프하도록 대상·전용 인증 파일을 설정해야 합니다.
본 PR에서는 운영 배포나 외부 계정 알림을 실행하지 않습니다.

## 검사와 종료

```sh
cd model-serving
uv venv --python 3.11
uv pip sync requirements.txt
uv pip install pytest httpx
.venv/bin/python -m pytest tests -q
cd ..
uv sync --project agent --locked --python 3.11
agent/.venv/bin/python -m pytest agent/tests tests -q

docker run --rm --entrypoint promtool \
  -v "$PWD/model-serving/monitoring:/rules:ro" -w /rules \
  prom/prometheus:v3.15.1 test rules alerts.test.yml

docker compose -f model-serving/compose.yaml down
```

Prometheus 시계열, Grafana 설정, Alertmanager 상태, 수신함은 각 전용 볼륨에 유지합니다.
예측·Agent 카운터는 프로세스 재시작 시 초기화됩니다. 단일 worker 기준이며 멀티 worker의 메트릭 합산은 포함하지 않습니다.
자료의 scikit-learn/Prometheus/Grafana 흐름과 [ProcessCollector](https://prometheus.github.io/client_python/collector/),
[Alertmanager webhook](https://prometheus.io/docs/alerting/latest/configuration/),
[Grafana provisioning](https://grafana.com/docs/grafana/latest/administration/provisioning/) 구성을 사용합니다.
