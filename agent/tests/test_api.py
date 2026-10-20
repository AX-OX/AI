import asyncio

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from app.config import Settings
from app.graph.builder import build_graph
from app.main import create_app
from app.runner import TaskRunner


class FakeSpring:
    def __init__(self):
        self.events, self.patches = [], []

    async def emit(self, task_id, type_, node=None, data=None):
        self.events.append((type_.value, node, data))

    async def patch_task(self, task_id, **fields):
        self.patches.append(fields)


@pytest.fixture
def ctx():
    spring = FakeSpring()
    runner = TaskRunner(build_graph(InMemorySaver()), spring, Settings())
    with TestClient(create_app(runner)) as client:
        yield client, spring


def wait(client, spring, cond, tries=50):
    import time

    for _ in range(tries):
        if cond():
            return
        time.sleep(0.05)
    raise AssertionError(f"timeout: {spring.events} {spring.patches}")


RUN = {"companyId": 1, "userId": 7, "requestText": "x"}


def test_health(ctx):
    client, _ = ctx
    assert client.get("/health").json() == {"status": "ok"}


def test_run_returns_202_and_stops_at_approval(ctx):
    client, spring = ctx
    r = client.post("/tasks/t1/run", json=RUN)
    assert r.status_code == 202
    wait(client, spring, lambda: any(e[0] == "APPROVAL_REQUIRED" for e in spring.events))
    assert spring.patches[-1]["status"] == "WAITING_APPROVAL"


def test_duplicate_run_is_409(ctx):
    client, spring = ctx
    client.post("/tasks/t1/run", json=RUN)
    wait(client, spring, lambda: any(e[0] == "APPROVAL_REQUIRED" for e in spring.events))
    assert client.post("/tasks/t1/run", json=RUN).status_code == 409


def test_resume_by_other_user_is_403(ctx):
    client, spring = ctx
    client.post("/tasks/t1/run", json=RUN)
    wait(client, spring, lambda: any(e[0] == "APPROVAL_REQUIRED" for e in spring.events))
    r = client.post("/tasks/t1/resume", json={"decision": "APPROVE", "userId": 999})
    assert r.status_code == 403


def test_resume_without_waiting_is_409(ctx):
    client, _ = ctx
    r = client.post("/tasks/nope/resume", json={"decision": "APPROVE", "userId": 7})
    assert r.status_code == 409


def test_approve_finishes_done(ctx):
    client, spring = ctx
    client.post("/tasks/t1/run", json=RUN)
    wait(client, spring, lambda: any(e[0] == "APPROVAL_REQUIRED" for e in spring.events))
    assert client.post("/tasks/t1/resume", json={"decision": "APPROVE", "userId": 7}).status_code == 202
    wait(client, spring, lambda: spring.events[-1][0] == "DONE")
    assert spring.patches[-1]["status"] == "DONE"


def test_reject_sets_rejected(ctx):
    client, spring = ctx
    client.post("/tasks/t1/run", json=RUN)
    wait(client, spring, lambda: any(e[0] == "APPROVAL_REQUIRED" for e in spring.events))
    client.post("/tasks/t1/resume", json={"decision": "REJECT", "userId": 7, "reason": "no"})
    wait(client, spring, lambda: spring.patches[-1]["status"] == "REJECTED")
