import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.graph.builder import build_graph

BASE = {
    "task_id": "t1",
    "company_id": 1,
    "user_id": 7,
    "request": "x",
    "messages": [],
    "errors": [],
    "retry_count": 0,
}


def cfg(task_id="t1"):
    return {"configurable": {"thread_id": task_id}}


def traced(order):
    """Node 호출 순서를 기록하는 스텁 생성기."""

    def make(name, update=None):
        async def fn(state):
            order.append(name)
            return update(state) if callable(update) else (update or {})

        return fn

    return make


async def test_happy_path_waits_at_approval_then_registers():
    order = []
    mk = traced(order)
    g = build_graph(
        InMemorySaver(),
        nodes={n: mk(n) for n in ["collect", "retrieve", "assess", "discover", "evaluate", "roadmap", "register"]},
    )

    await g.ainvoke(BASE, cfg())
    assert order == ["collect", "retrieve", "assess", "discover", "evaluate", "roadmap"]
    assert g.get_state(cfg()).next == ("approval",)  # 승인 대기

    await g.ainvoke(Command(resume={"decision": "APPROVE", "userId": 7, "reason": None}), cfg())
    assert order[-1] == "register"


async def test_reject_ends_without_register():
    order = []
    mk = traced(order)
    g = build_graph(InMemorySaver(), nodes={"register": mk("register")})
    await g.ainvoke(BASE, cfg("t2"))
    await g.ainvoke(Command(resume={"decision": "REJECT", "userId": 7, "reason": "no"}), cfg("t2"))
    assert "register" not in order
    assert g.get_state(cfg("t2")).values["approval"]["decision"] == "REJECT"


async def test_wrong_user_cannot_approve():
    g = build_graph(InMemorySaver())
    await g.ainvoke(BASE, cfg("t3"))
    with pytest.raises(PermissionError):
        await g.ainvoke(Command(resume={"decision": "APPROVE", "userId": 999}), cfg("t3"))


async def test_collect_error_ends_early():
    order = []
    mk = traced(order)
    g = build_graph(
        InMemorySaver(),
        nodes={
            "collect": mk("collect", {"errors": ["회사 99는 없다"]}),
            "retrieve": mk("retrieve"),
        },
    )
    await g.ainvoke(BASE, cfg("t4"))
    assert order == ["collect"]
    assert g.get_state(cfg("t4")).next == ()


async def test_insufficient_portfolio_retries_discover_at_most_twice():
    order = []
    mk = traced(order)

    # retry_count는 재탐색으로 돌아온 discover가 올린다 (insufficient 때문에 다시 실행된 경우)
    def discover(state):
        again = (state.get("portfolio") or {}).get("insufficient", False)
        return {"retry_count": state["retry_count"] + 1} if again else {}

    g = build_graph(
        InMemorySaver(),
        nodes={
            "discover": mk("discover", discover),
            "evaluate": mk("evaluate", {"portfolio": {"insufficient": True}}),
            "roadmap": mk("roadmap"),
        },
    )
    await g.ainvoke(BASE, cfg("t5"))
    assert order.count("discover") == 3  # 최초 1회 + 재탐색 2회
    assert order[-1] == "roadmap"
