"""팀원 기준표·순수 함수 검증용. 운영 Agent의 성숙도 총점은 Spring 응답을 사용한다."""
from functools import lru_cache
from pathlib import Path

import yaml

CRITERIA_PATH = Path(__file__).resolve().parent.parent / "config" / "maturity_criteria.yaml"


@lru_cache
def load_criteria() -> dict:
    return yaml.safe_load(CRITERIA_PATH.read_text(encoding="utf-8"))


def compute_total_score(scores: dict[str, float]) -> float | None:
    """영역 점수(키: area 이름 data/infra/automation/ai_capability/governance)의 가중합.

    LLM이 아니라 코드로 계산한다. 5개 영역이 모두 있어야 값을 돌려주고,
    하나라도 없으면(근거 부족) None — 일부 점수로 총점을 만들지 않는다.
    """
    areas = load_criteria()["areas"]
    if any(a not in scores or scores[a] is None for a in areas):
        return None
    total = sum(scores[a] * cfg["weight"] for a, cfg in areas.items())
    return round(total, 2)
