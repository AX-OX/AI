# 가장 간단한 모델 서빙 + Grafana

scikit-learn의 내장 Iris 데이터로 학습한 작은 RandomForest를 FastAPI로 서빙합니다.
컨테이너를 빌드할 때 한 번 학습해 `iris.joblib`로 저장하고, 서버 시작 시 로드해 재사용합니다.
데이터 다운로드, GPU, OpenAI 키, DB, 기존 Agent 실행이 필요 없습니다.

```text
POST /predict → FastAPI + Iris RandomForest
                   ↓ /metrics (5초마다 수집)
                Prometheus → Grafana
```

## 실행

Docker Desktop을 실행한 뒤 AI 저장소 루트에서:

```sh
docker compose -f model-serving/compose.yaml up --build -d
```

- [Grafana 대시보드](http://localhost:3001/d/iris-model-serving): 로그인 없이 Viewer로 확인. 데이터소스와 대시보드 자동 등록.
- [Swagger](http://localhost:8001/docs): API 호출 UI.
- [모델 준비 상태](http://localhost:8001/health), [원본 메트릭](http://localhost:8001/metrics).
- [Prometheus](http://localhost:9091): `up{job="iris-model"}` 쿼리로 수집 상태 확인.

기존 서비스와 포트 충돌을 줄이기 위해 8001/9091/3001을 사용합니다. 모든 포트는 로컬호스트에만 바인딩합니다.
첫 빌드에는 이미지와 Python 패키지를 받는 인터넷 연결이 필요합니다. 실행 후 모델 다운로드나 외부 API 호출은 없습니다.

## 예측

입력 순서는 **꽃받침 길이, 꽃받침 너비, 꽃잎 길이, 꽃잎 너비(cm)** 입니다.
양수이며 100 이하인 유한한 숫자 4개를 받습니다. 문자열·잘못된 길이·범위는 HTTP 422입니다.

```sh
curl -sS http://localhost:8001/predict \
  -H 'Content-Type: application/json' \
  -d '{"features":[5.1,3.5,1.4,0.2]}'
```

응답은 `model_version`, `class_id`, `class_name`(이 예시는 `setosa`), 세 품종별 `probabilities`입니다.
확률은 모델의 분류 확률이며, 실서비스의 정확도를 뜻하지 않습니다.

요청과 오류를 만들어 대시보드를 확인하려면:

```sh
for i in $(seq 1 30); do
  curl -sS -o /dev/null http://localhost:8001/predict \
    -H 'Content-Type: application/json' -d '{"features":[5.1,3.5,1.4,0.2]}'
  sleep 1
done
curl -sS http://localhost:8001/predict \
  -H 'Content-Type: application/json' -d '{"features":[1,2]}'
```

Grafana는 5초마다 갱신합니다. 최초 수집은 약 5초, 요청률/오류율/p95는 최소 두 번 수집 후 표시됩니다.

## 확인할 지표

| 패널 | 의미 |
| --- | --- |
| Serving ready | Prometheus 수집 성공 × 모델 로드 상태. 서버를 중지하면 DOWN |
| Prediction requests | 프로세스 시작 후 예측 요청 누계, HTTP 상태별 |
| Requests / second | 최근 2분 요청률 |
| Error ratio | 최근 2분 HTTP 4xx/5xx 비율. 잘못된 입력(422)도 포함 |
| Request latency p95 | 최근 2분 예측 HTTP 처리 시간의 히스토그램 추정 p95 |
| Build holdout accuracy | 고정 seed로 분리한 Iris 30건의 빌드 시 정확도. 실시간 품질/드리프트 아님 |

가동 중단 확인: `docker compose -f model-serving/compose.yaml stop model` 후 10초 내 Serving ready가 DOWN으로 바뀝니다.
`docker compose -f model-serving/compose.yaml start model`로 복구합니다.
예측 요청 카운터는 모델 프로세스 재시작 시 초기화됩니다. Prometheus와 Grafana 데이터는 전용 볼륨에 보관합니다.

## 로컬 Python 검사

```sh
cd model-serving
uv venv --python 3.11
uv pip sync requirements.txt
uv pip install pytest httpx
.venv/bin/python -m pytest tests -q
# Docker 없이 API만 실행
.venv/bin/python -m app.train
.venv/bin/uvicorn app.main:app --port 8001
```

런타임 의존성은 `requirements.in`에서 `uv pip compile requirements.in --python-version 3.11 -o requirements.txt`로 고정합니다.
신뢰하는 이 프로젝트가 생성한 모델 파일만 로드합니다. 기본 실행은 단일 worker이며 메트릭도 프로세스 단위입니다.

## 종료

```sh
docker compose -f model-serving/compose.yaml down
```

로컬 학습/모니터링용 독립 예제입니다. 기존 AX Agent/BE/FE, VM 배포 파이프라인에 연결하지 않습니다.
Grafana Viewer 익명 접속은 로컬 실습 편의를 위한 설정입니다. 외부 공개 시 별도 인증과 네트워크 구성이 필요합니다.

참고: 제공 자료의 「Application 내 추론 런타임 (Scikit-learn)」(PDF 70~78쪽)과
「LGTM」의 Prometheus 수집/Grafana 시각화 흐름(PDF 305쪽)을 작은 독립 예제로 구성했습니다.
계측과 자동 등록은 [Prometheus Python Histogram](https://prometheus.github.io/client_python/instrumenting/histogram/),
[Grafana provisioning](https://grafana.com/docs/grafana/latest/administration/provisioning/) 방식을 따릅니다.
