"""Agent Loop 한도 (§11): 최대 8턴, 작업 120초, 같은 도구 3회. 결과 2,000자 자르기."""

import time
from collections import Counter

from ..config import Settings


class LimitExceeded(Exception):
    pass


def truncate_result(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    omitted = len(text) - max_chars
    return text[:max_chars] + f"\n...[{omitted}자 생략]"


class LoopGuard:
    """ReAct 루프 1회(예: collect Node)의 턴·시간·도구 호출 횟수를 감시한다."""

    def __init__(self, settings: Settings, clock=time.monotonic):
        self._max_turns = settings.max_agent_turns
        self._max_same = settings.max_same_tool_calls
        self._deadline = clock() + (settings.task_timeout_seconds or settings.timeout)
        self._clock = clock
        self._turns = 0
        self._tools: Counter[str] = Counter()

    def next_turn(self) -> None:
        self._turns += 1
        if self._turns > self._max_turns:
            raise LimitExceeded(f"최대 {self._max_turns}턴 초과")
        if self._clock() > self._deadline:
            raise LimitExceeded("작업 시간 초과")

    def record_tool(self, name: str) -> None:
        self._tools[name] += 1
        if self._tools[name] > self._max_same:
            raise LimitExceeded(f"같은 도구 {name}을(를) {self._max_same}회 초과 호출")
