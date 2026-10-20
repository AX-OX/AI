import pytest

from app.config import Settings
from app.harness.guardrails import mask_pii, mask_text
from app.harness.limits import LimitExceeded, LoopGuard, truncate_result
from app.harness.recovery import call_with_recovery
from app.harness.tool_output import prepare_tool_output
from app.maturity import compute_total_score, load_criteria


def test_mask_email_and_phone():
    s = mask_text("담당 hong.gildong@company.co.kr / 010-1234-5678, 02-123-4567")
    assert "hong.gildong" not in s and "5678" in s and "1234-5678" not in s
    assert "h***@company.co.kr" in s


def test_mask_nested():
    out = mask_pii({"a": [{"email": "a@b.com"}], "n": 3})
    assert out == {"a": [{"email": "a***@b.com"}], "n": 3}


def test_truncate():
    assert truncate_result("abc", 10) == "abc"
    assert truncate_result("x" * 3000, 2000).startswith("x" * 2000)
    assert "1000자 생략" in truncate_result("x" * 3000, 2000)


def test_prepare_masks_before_truncating():
    text = "x" * 1995 + " hong@company.com"
    out = prepare_tool_output(text, Settings())
    assert "hong@company.com" not in out


def test_loop_guard_turns_and_same_tool():
    g = LoopGuard(Settings(max_agent_turns=2, max_same_tool_calls=2))
    g.next_turn(); g.next_turn()
    with pytest.raises(LimitExceeded):
        g.next_turn()
    g = LoopGuard(Settings(max_same_tool_calls=2))
    g.record_tool("t"); g.record_tool("t")
    with pytest.raises(LimitExceeded):
        g.record_tool("t")


def test_loop_guard_timeout():
    now = [0.0]
    g = LoopGuard(Settings(task_timeout_seconds=120), clock=lambda: now[0])
    g.next_turn()
    now[0] = 121
    with pytest.raises(LimitExceeded):
        g.next_turn()


class Boom(Exception):
    def __init__(self, status):
        self.status_code = status


async def test_recovery_retries_then_succeeds():
    calls = []

    async def primary():
        calls.append(1)
        if len(calls) < 3:
            raise Boom(429)
        return "ok"

    assert await call_with_recovery(primary, base_delay=0) == "ok"
    assert len(calls) == 3  # 최초 + 재시도 2회


async def test_recovery_falls_back_after_retries():
    async def primary():
        raise Boom(503)

    async def fallback():
        return "fallback"

    assert await call_with_recovery(primary, fallback, base_delay=0) == "fallback"


async def test_recovery_does_not_retry_other_errors():
    calls = []

    async def primary():
        calls.append(1)
        raise Boom(400)

    with pytest.raises(Boom):
        await call_with_recovery(primary, base_delay=0)
    assert len(calls) == 1


async def test_recovery_raises_without_fallback():
    async def primary():
        raise Boom(429)

    with pytest.raises(RuntimeError):
        await call_with_recovery(primary, base_delay=0)


def test_maturity_weights_sum_to_one():
    areas = load_criteria()["areas"]
    assert round(sum(a["weight"] for a in areas.values()), 6) == 1.0


def test_total_score_weighted_sum():
    scores = {"data": 80, "infra": 60, "automation": 40, "ai_capability": 20, "governance": 100}
    # 80*.25 + 60*.2 + 40*.2 + 20*.2 + 100*.15 = 20+12+8+4+15
    assert compute_total_score(scores) == 59.0


def test_total_score_none_when_area_missing():
    assert compute_total_score({"data": 80, "infra": 60}) is None
