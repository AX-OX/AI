# OpenAI 실호출로 입력·응답·Agent Loop 확인

`llm-demo`는 실제 OpenAI LLM과 v3 도구 fixture를 연결하는 로컬 개발 모드다. Spring·PostgreSQL·MCP 서버 없이 입력·LLM 도구 선택·성숙도 제안·후보 생성·한국어 설명·자동 가상 등록 흐름을 확인한다. 실제 pgvector 검색이나 실제 등록을 검증하는 모드는 아니다.

## 시작

`.env`에 다음 값을 설정한다. `.env`는 Git에서 제외되어 있고 키는 터미널 화면·로그·소스에 기록하지 않는다.

```dotenv
OPENAI_API_KEY=<본인 키>
LLM_MODEL=gpt-4.1-mini
```

프로젝트 루트에서:

```sh
.venv/bin/python scripts/chat_agent.py
```

기존 8000번 서버를 종료하지 않아도 된다. 이 스크립트는 별도 포트를 열지 않고 동일 FastAPI 앱을 ASGI로 실행한다. CLI의 설정은 항상 메모리 체크포인터를 사용하므로 `.env`의 Docker용 DB 주소 때문에 DB에 연결하지 않는다. 프로세스를 종료하면 이 데모의 체크포인트·실행 추적은 사라진다.

입력 예시:

```text
예산 3억 원 안에서 AX 과제 3개를 선정하고 근거와 선행 과제를 설명해줘
```

기본 화면은 진행 단계·과제 표·Agent 응답을 표시한다. y/n 입력 없이 가상 등록까지 자동 진행하고 DONE으로 종료한다. 도구 인자·전체 공개 이벤트는 --verbose로 확인한다. `/exit`로 종료한다. 각 입력은 독립된 새 taskId이며 이전 입력과 이어지는 자유 대화 세션은 아니다. 현재 MVP는 회사 1의 전체 업무 또는 명시한 부서(예: 개발부·개발팀·기획부·인사부)에서 기존 회사 예산으로 과제 3개를 선정한다. 전체 데이터 수집과 기업 성숙도 평가는 유지하고 후보 생성부터 부서 범위를 적용한다. Impact 정규화는 부서 후보로 다시 하지 않고 회사 전체 기준을 유지한다. 임의 예산 변경·단일 지표 질의는 별도 intent 분기 대상이다. 인사처럼 선정 가능 업무가 3개 미만인 부서는 세 과제 포트폴리오를 만들 수 없다.

키 없이 화면과 흐름만 확인:

```sh
.venv/bin/python scripts/chat_agent.py --mode mock
```

한 번 실행하고 가상 등록 완료까지 진행:

```sh
.venv/bin/python scripts/chat_agent.py --prompt '예산 3억 원 안에서 AX 과제 3개를 선정해줘'
# 공개 결과·실행 기록을 JSON으로 저장하려면 --output reports/my_llm_demo.json 추가
```

모델은 `--model` → `LLM_MODEL` → `gpt-4.1-mini` 순으로 선택한다. 실제 호출에는 API 사용량이 발생한다. 다른 모델은 계정 접근 권한과 도구 호출 지원을 확인해야 한다.

## 무엇이 실제인가

| 모드 | LLM | 도구·계산·검색·등록 | checkpointer |
|---|---|---|---|
| mock | mock | v3 fixture | 기본 메모리 |
| llm-demo | 실제 OpenAI | v3 fixture | CLI는 메모리 |
| live | 실제 OpenAI | 실제 MCP·Spring·pgvector | PostgreSQL 필수 |

llm-demo의 AX점수·ROI는 패키지의 계산 정답을 반환한다. 포트폴리오는 후보 부분집합 256개에 대해 사전 계산한 agent/fixtures/portfolio_subsets_v3.json을 조회한다. scripts/build_demo_portfolios.py는 오프라인 전용이며 실제 요청 처리에 계산 코드를 넣지 않는다. 원본 CSV·정책·정답 해시가 다르면 재생성을 요구한다. 모델은 성숙도 영역 점수·후보 설명·최종 한국어 설명을 생성한다. mock 성숙도 저장은 새로운 LLM 영역 점수에 이전 정답의 총점을 붙이지 않는다. 점수가 reference와 다르면 총점은 생략한다. 가중 총점은 실제 Spring에서 계산해야 한다.

LLM은 계산을 하지 않는다. 최종 응답의 핵심 수치 표시는 검증된 도구 값에서 코드가 붙인다. 설명의 솔루션·근거 ID도 실제 선택·검색 결과와 대조한다. 실제 추천 설명에는 여전히 사람의 내용 검토가 필요하다. 가정 데이터가 실제 효과의 증거가 되지는 않는다.

## 관찰할 수 있는 Agent Loop

```text
사용자 입력
 → collect: LLM → 읽기 도구 선택 → 도구 결과 → 필요 시 LLM 재호출(최대 8턴)
 → retrieve: 문서 근거 수집
 → assess: LLM 영역 점수·근거 → 평가 저장
 → discover: LLM 후보·설명 → 대상 업무·제외·선행 조건 검증
 → evaluate: ROI·포트폴리오 도구
      └ 부족하면 discover로 재탐색(최대 2회)
 → roadmap: 일정·도구 수치 조립 + LLM 한국어 설명
 → approval: CLI가 자동 재개 (서비스 API는 요청자 승인 대기 유지)
 → register: CLI 가상 등록 완료 (DONE)
```

전체가 자유롭게 다음 행동을 고르는 무제한 ReAct 루프는 아니다. LangGraph의 정해진 노드 흐름 안에 LLM 도구 선택 루프·후보 재탐색·승인 중단/재개가 있다.

`NODE_START/END`, `LLM_REQUEST/RESPONSE`, `LLM_TOOL_CALL`, `TOOL_CALL/RESULT`, 승인·실패를 볼 수 있다. 기록은 공개 작업·도구·결과이며 내부 추론 원문이 아니다. trace는 최근 100개 작업, 작업별 500개 이벤트로 제한하고 자격증명 필드는 제거한다. 기존 내부 GET `/tasks/{taskId}`에서도 `trace`, `result.answer`를 확인할 수 있다. 새 Spring 공개 API는 추가하지 않았다.

## 오류 확인

- LLM_ERROR에 401/403: 키·프로젝트·모델 접근 설정 확인.
- 429: 사용량 한도·크레딧·요청 제한 확인.
- 400: 모델/도구 스키마 호환 문제 확인.
- NODE_ERROR: 근거 ID·후보 연결·숫자 검증 등 단계와 message에 표시된 후보 ID를 확인한다. CANDIDATES_PROPOSED에서 모델이 제안한 ID를 대조할 수 있다.
- 입력과 모드·도구 backend를 함께 확인하여 실제 호출과 fixture를 구분한다.

키를 공유할 필요는 없다. 오류를 공유할 때는 키·토큰을 제외한 HTTP 상태와 공개 실행 기록을 전달한다.

공식 근거: [OpenAI Function calling](https://developers.openai.com/api/docs/guides/function-calling), [GPT-4.1 mini](https://developers.openai.com/api/docs/models/gpt-4.1-mini). 이 프로젝트는 LangChain ChatOpenAI를 통해 Responses API를 사용한다.


## 읽기 쉬운 화면과 자동 등록

기본 실행은 노드 진행·도구 선택 요약·과제 표·Agent 응답만 표시한다. 도구 인자·토큰 사용량·전체 공개 이벤트는 `--verbose`로 확인하고, JSON은 `--output`으로 저장한다. 가상 등록까지 완료한 최종 상태를 출력 파일에 기록한다.

```sh
python3 scripts/chat_agent.py
python3 scripts/chat_agent.py --verbose
```

`exit`, `/exit`, `quit`, `종료`로 종료할 수 있다. 여러 줄을 붙여 넣으려면 먼저 `/multi`를 입력하고, 질문을 붙여 넣은 뒤 마지막 줄에 `/send`를 입력한다. y/n 승인 입력은 받지 않는다.

CLI는 `mock`·`llm-demo`에서만 실행되며, 승인 대기 상태를 감지하면 `/resume`에 APPROVE를 자동 전달한다. 별도 PostgreSQL 서버 없이 가상 로드맵·프로젝트 ID를 메모리에 기록한다. 종료 후 상태는 유지되지 않는다. 패키지 SQLite 파일은 평가 참고값 읽기용이며 실행 결과를 쓰는 저장소가 아니다. 서비스 API의 승인 계약과 live 저장 동작은 유지되며, live에서는 요청자 승인 후 Business MCP → Spring 저장 API → PostgreSQL로 저장한다. 업무별 사람 최종 검토 조건도 유지된다.
