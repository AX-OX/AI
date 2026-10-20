"""Guardrails (§11): 이메일·전화번호 마스킹."""

import re
from typing import Any

_EMAIL = re.compile(r"([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*(@[A-Za-z0-9.-]+\.[A-Za-z]{2,})")
# 010-1234-5678, 02-123-4567, 01012345678 등
_PHONE = re.compile(r"(?<!\d)(0\d{1,2})[-.\s]?(\d{3,4})[-.\s]?(\d{4})(?!\d)")


def mask_text(text: str) -> str:
    text = _EMAIL.sub(lambda m: f"{m.group(1)}***{m.group(2)}", text)
    return _PHONE.sub(lambda m: f"{m.group(1)}-****-{m.group(3)}", text)


def mask_pii(obj: Any) -> Any:
    """문자열·dict·list를 재귀적으로 마스킹한 새 객체를 돌려준다."""
    if isinstance(obj, str):
        return mask_text(obj)
    if isinstance(obj, dict):
        return {k: mask_pii(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [mask_pii(v) for v in obj]
    return obj
