"""Source-scoped daily US regional egg quotes, never national price inference."""
from __future__ import annotations

import re
from .grounded_korean_brief import source_statement_retracted


_WORDS = {word: str(number) for number, word in enumerate(
    ('zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten', 'eleven', 'twelve'))}


def native_new_york_egg_quote(body: str) -> tuple[str, str] | None:
    """Translate one explicit regional size/price/period comparison.

    Missing store-delivery scope, daily comparison, unchanged middle size or
    currency denominator is not repaired with assumptions. Headline numbers,
    surrounding dates and a different region cannot provide those operands.
    """
    text = re.sub(r'\s+', ' ', body).strip()
    lead = re.match(
        r'The USDA Agricultural Marketing Service released its daily New York shell egg report '
        r'for [A-Za-z]+ \d{1,2}, 20\d{2}, covering caged white eggs delivered to store doors\.', text, re.I)
    if not lead:
        return None
    sentence = re.match(
        r'\s*(?:According to the report, )?prices for extra large and large eggs '
        r'(?P<direction>declined|increased|rose|fell) by '
        r'(?P<amount>\d+(?:\.\d+)?|' + '|'.join(_WORDS) + r') cents? per dozen '
        r'compared to the previous trading day, while medium egg prices '
        r'(?P<medium>remained unchanged|held steady)\.', text[lead.end():], re.I)
    if not sentence:
        return None
    evidence = lead[0] + ' ' + sentence[0].strip()
    if source_statement_retracted(text, evidence):
        return None
    amount = _WORDS.get(sentence['amount'].lower(), sentence['amount'])
    movement = '하락' if sentence['direction'].lower() in ('declined', 'fell') else '상승'
    summary = (f'미국 뉴욕 흰 계란 소매납품가 특대·대란 전일비 12개당 {amount}센트 {movement}, 중란 보합')
    return summary, evidence
