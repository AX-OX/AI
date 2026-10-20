from ..config import Settings
from .guardrails import mask_text
from .limits import truncate_result


def prepare_tool_output(text: str, settings: Settings) -> str:
    """도구 결과를 모델에 넘기기 전 처리: 개인정보 마스킹 → 길이 제한.

    마스킹을 먼저 해서, 자르는 경계에서 이메일이 반쯤 잘려 마스킹을 피하는 일이 없게 한다.
    """
    return truncate_result(mask_text(text), settings.tool_result_max_chars)


def tool_error_text(exc: Exception) -> str:
    """도구 오류를 ToolMessage 내용으로 변환. 재시도에 필요한 hint(유효 ID 등)가 메시지에 있으면 그대로 보존."""
    return f"[도구 오류] {exc}"
