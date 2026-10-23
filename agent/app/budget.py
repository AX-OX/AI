"""Extract an explicit budget (KRW) from the request text. No budget = no constraint."""
import re

# 3억, 3억 5천만, 1.5억, 5000만, 5,000만, 300,000,000원
_AMOUNT = re.compile(r'(?<![\d.,])(?:(\d+(?:\.\d+)?)\s*억(?:\s*(\d+)\s*천\s*만?|\s*(\d+(?:,\d{3})*)\s*만)?'
                     r'|(\d+(?:,\d{3})*)\s*(천만|만)|(\d{1,3}(?:,\d{3})+|\d{5,})\s*원)')
# 금액 바로 뒤에 오는 한도 표현. 금액이 하나라도 한도 표현이 없으면 예산으로 보지 않는다.
_LIMIT = re.compile(r'^\s*(?:원)?\s*(?:의)?\s*(?:예산)?\s*(?:내|이내|안|이하|한도|범위|까지|으로|로)')


def _value(match):
    eok, cheon, man_after_eok, number, unit, won = match.groups()
    if eok:
        value = round(float(eok) * 100_000_000)
        if cheon: value += int(cheon) * 10_000_000
        if man_after_eok: value += int(man_after_eok.replace(',', '')) * 10_000
        return value
    if number:
        return int(number.replace(',', '')) * (10_000_000 if unit == '천만' else 10_000)
    return int(won.replace(',', ''))


def request_budget(text):
    """'예산'이 붙은 금액, 없으면 '내/이내/한도'가 붙은 금액 하나를 예산으로 본다. 없으면 None."""
    matches = list(_AMOUNT.finditer(text or ''))
    if not matches:
        return None
    keyword = (text or '').find('예산')
    if keyword >= 0:
        # '예산 3억', '3억 원의 예산' 모두 허용: 키워드와 가장 가까운 금액.
        nearest = min(matches, key=lambda m: min(abs(m.start() - keyword), abs(m.end() - keyword)))
        if min(abs(nearest.start() - keyword), abs(nearest.end() - keyword)) <= 12:
            return _value(nearest)
    limited = [m for m in matches if _LIMIT.match(text[m.end():])]
    return _value(limited[0]) if len(limited) == 1 else None
