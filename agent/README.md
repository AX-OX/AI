# AX Navigator AI — Agent

FastAPI + LangGraph. 계약은 `AX_NAVIGATOR_CONTEXT.md`를 따른다.

## 실행
```bash
cd agent
uv sync
cp .env.example .env   # 값 채우기 (키는 커밋하지 않는다)
uv run uvicorn app.main:app --port 8000
```

## 테스트
```bash
uv run pytest
# 실제 Postgres checkpointer 통합 테스트
AGENT_TEST_PG_DSN=postgresql://user@localhost/ax_agent_test uv run pytest
```

## 엔드포인트 (내부)
| Method | Path | 응답 |
|---|---|---|
| POST | `/tasks/{taskId}/run` | 202 (중복 taskId는 409) |
| POST | `/tasks/{taskId}/resume` | 202 (승인 대기 아님 409, 요청자 아님 403) |
| GET | `/health` | 200 |

## 구현 상태
- 완료: 그래프 뼈대·분기·승인 재개, FastAPI, Spring 전송부, Harness 부품(마스킹/자르기/한도/재시도), 성숙도 기준표·총점
- 대기: Node 실제 구현(MCP·데이터 필요), MCP Client 연결, 계약 테스트, LLM 호출
