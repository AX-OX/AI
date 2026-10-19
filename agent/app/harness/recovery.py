"""Recovery (§11): 429/503이면 2회 재시도 → 대체 모델 → 그래도 실패하면 예외."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")
log = logging.getLogger(__name__)

RETRYABLE_STATUS = {429, 503}
MAX_RETRIES = 2


def is_retryable(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None) or getattr(getattr(exc, "response", None), "status_code", None)
    return status in RETRYABLE_STATUS


async def call_with_recovery(
    primary: Callable[[], Awaitable[T]],
    fallback: Callable[[], Awaitable[T]] | None = None,
    base_delay: float = 1.0,
) -> T:
    for attempt in range(MAX_RETRIES + 1):
        try:
            return await primary()
        except Exception as e:  # noqa: BLE001
            if not is_retryable(e):
                raise
            if attempt < MAX_RETRIES:
                await asyncio.sleep(base_delay * (2**attempt))
                continue
            log.warning("기본 모델 %d회 실패: %s", attempt + 1, e)
    if fallback is None:
        raise RuntimeError("기본 모델 재시도 실패, 대체 모델 없음")
    return await fallback()
