"""Conservative Korean trade/recall compaction from complete original clauses.

These are source frames, not week-specific summaries or URL fallbacks. They
preserve the actual commodity, quantity, procedural cause and conditional
policy. The caller still owns original publication-date and layout checks.
"""
from __future__ import annotations

import re

from .grounded_korean_brief import source_statement_retracted


_QUANTITY = r"\d[\d,]*(?:\s*[억만천](?:\s*[\d,]+)?)*"


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _samgyetang_reinspection_recall(body: str) -> tuple[str, str] | None:
    # Bind the weight to the named imported Korean chicken product and the
    # observed official recall. Do not use a retailer's packing weight, states
    # count or an unrelated meat product's recall quantity.
    text = _clean(body)
    order = re.search(
        r"미국\s+농무부\(USDA\)\s+산하\s+식품안전검사국\(FSIS\)은\s+"
        r"[^.!?]{0,160}?한국산\s+삼계탕\s+완제품\s+"
        r"(?P<approx>약\s*)?(?P<weight>\d[\d,]*(?:\.\d+)?)파운드"
        r"(?:\([^)]{1,40}\))?에\s+대해\s+공식\s+리콜을\s+명령했다[.]",
        text)
    if not order:
        return None
    # The explanatory sentence must immediately follow the actual order. Its
    # explicit procedural cause is not a claim of bacterial contamination.
    reason = re.match(
        r"\s*이번\s+조치는\s+(?:[^.!?]|\.(?=\d)){0,400}?"
        r"물리적\s+재검사\s+절차가\s+누락된\s+행정적\s+결함에서\s+"
        r"비롯된\s+것으로\s+확인됐다[.]",
        text[order.end():])
    if not reason:
        return None
    evidence = text[order.start():order.end() + reason.end()]
    if source_statement_retracted(text, evidence):
        return None
    approximate = "약 " if order['approx'] else ""
    return (f"미국 FSIS, 수입 재검사 누락된 한국산 삼계탕 {approximate}{order['weight']}파운드 리콜", evidence)


def _egg_import_pause_and_conditional_restart(body: str) -> tuple[str, str] | None:
    text = _clean(body)
    match = re.search(
        rf"추석\s+연휴\s+전까지\s+(?P<quantity>{_QUANTITY})개\s+계란을\s+"
        r"수입하고\s+잠정\s+중단했는데,\s+현재\s+aT가\s+갖고\s+있는\s+"
        r"수입란\s+재고는\s+없다[.]\s*상황에\s+따라\s+언제든\s+"
        r"추가\s+수입을\s+검토할\s+수\s+있다",
        text)
    if not match:
        return None
    evidence = match[0]
    if source_statement_retracted(text, evidence):
        return None
    quantity = re.sub(r"(?<=[억만천])(?=\d)", " ", _clean(match['quantity']))
    return (f"추석 전 계란 {quantity}개 수입 후 잠정 중단, 상황에 따라 추가 수입 검토 가능성", evidence)


def _fao_pork_supply_price(body: str) -> tuple[str, str] | None:
    text = _clean(body)
    period = re.search(r"유엔 식량농업기구\(FAO\)의 (?P<month>1[0-2]|[1-9])월 세계식량가격지수", text)
    fact = re.search(r"돼지고기도 주요 수출국의 풍부한 공급으로 하락했다[.]", text)
    if not period or not fact or not 0 < fact.start() - period.end() < 3200:
        return None
    # The poultry sentence before this clause has its own Brazil/EU cause.
    # Never borrow its country or the aggregate meat index's percentage.
    if any(source_statement_retracted(text, match[0]) for match in (period, fact)):
        return None
    return (f"FAO {period['month']}월 동향, 돼지고기 가격은 주요 수출국의 풍부한 공급 영향으로 하락",
            period[0] + ' … ' + fact[0])


def native_domestic_recovery(kind: str, body: str) -> tuple[str, str] | None:
    """Return a source-bound brief and its exact evidence, or safely abstain."""
    if not isinstance(body, str) or not body.strip():
        return None
    if kind == 'domestic_chicken':
        return _samgyetang_reinspection_recall(body)
    if kind == 'domestic_egg':
        return _egg_import_pause_and_conditional_restart(body)
    if kind == 'domestic_pork':
        return _fao_pork_supply_price(body)
    return None
