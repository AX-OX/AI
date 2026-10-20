"""실제 Postgres checkpointer로 승인 대기 → 재개가 되는지 확인 (통합 테스트).

AGENT_TEST_PG_DSN이 없으면 건너뛴다. 예: postgresql://user@localhost/ax_agent_test
"""

import os
import uuid

import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command

from app.graph.builder import build_graph

DSN = os.environ.get("AGENT_TEST_PG_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="AGENT_TEST_PG_DSN 미설정")


async def test_resume_survives_new_graph_instance():
    task_id = str(uuid.uuid4())
    cfg = {"configurable": {"thread_id": task_id}}
    initial = {
        "task_id": task_id, "company_id": 1, "user_id": 7, "request": "x",
        "messages": [], "errors": [], "retry_count": 0,
    }

    async with AsyncPostgresSaver.from_conn_string(DSN) as saver:
        await saver.setup()
        await build_graph(saver).ainvoke(initial, cfg)

    # 프로세스 재시작을 흉내: 새 saver·새 graph로 같은 thread_id를 재개
    async with AsyncPostgresSaver.from_conn_string(DSN) as saver:
        g = build_graph(saver)
        assert (await g.aget_state(cfg)).next == ("approval",)
        await g.ainvoke(Command(resume={"decision": "APPROVE", "userId": 7}), cfg)
        state = await g.aget_state(cfg)
        assert state.next == ()
        assert state.values["approval"]["decision"] == "APPROVE"
