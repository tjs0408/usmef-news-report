"""Translate an explicit cross-border pork-processing plan, not live-pig trade.

Only a source's named Danish pork / Polish processing business / annual raw
material equivalent / shipment-plan chain supplies this fact. Quantities are
read from the source, and an ambition to double later is not current capacity.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re


_NUMBER = r'(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?'
_UNSAFE = re.compile(
    r'\b(?:not|never|no longer|false|incorrect|untrue|misreported|rumou?r|'
    r'cancelled|canceled|abandoned|withdrawn|postponed|suspended|denied|retracted|'
    r'corrected|correction|conditional|if|unless|would|could|might|may)\b|'
    r'\bsubject to\b', re.I)
_RETRACTION = re.compile(
    r'\b(?:cancelled|canceled|abandoned|withdrawn|postponed|suspended|denied|'
    r'retracted|corrected|misreported|false|incorrect|untrue)\b', re.I)
_REFERENCE = re.compile(r'\b(?:plan|initiative|announcement|report|shipment|processing|raw materials?)\b', re.I)


def _quantity(value: str, scale: str | None) -> str | None:
    try:
        count = Decimal(value.replace(',', ''))
        count *= {'thousand': 1000, 'million': 1000000}.get((scale or '').lower(), 1)
    except InvalidOperation:
        return None
    if count <= 0 or count != count.to_integral_value():
        return None
    amount = int(count)
    if amount >= 10000:
        high, low = divmod(amount, 10000)
        return f'{high}만' + (f' {low}' if low else '')
    return str(amount)


def native_europe_pork_processing_brief(body: str) -> tuple[str, str] | None:
    """Return a planned annual pork-raw-material equivalent and its evidence.

    A finished processing/slaughter result, a live-animal shipment, a different
    source/destination, an unreported denominator or a cancelled/conditional
    plan cannot use this grammar. Source statements remain intact as evidence.
    """
    text = re.sub(r'\s+', ' ', str(body)).strip()
    statements = [part.strip() for part in re.split(r'(?<=[.!?])\s+', text) if part.strip()]
    origin = next((part for part in statements
                   if re.search(r'\bDanish pork is being sent to Poland\b', part, re.I)
                   and not re.search(r'not true|not being|never|false|incorrect|untrue', part, re.I)), None)
    if origin is None:
        return None
    processing = None
    plant = None
    for part in statements:
        match = re.search(
            r"\braw materials from Danish Crown[’']s shareholders will be processed in "
            r"(?P<plant>[A-ZÀ-Ž][A-Za-zÀ-ž0-9 -]{1,55}), the group[’']s Polish business\.", part)
        if match and not _UNSAFE.search(part):
            processing, plant = part, match['plant'].strip()
            break
    if processing is None or plant is None:
        return None
    # Only nearby, linked origin/processing statements can lend a country to
    # the plan; another commodity-country section elsewhere cannot do so.
    if not 0 <= text.find(processing) - text.find(origin) <= 700:
        return None
    for part in statements:
        match = re.search(
            rf'\bDanish Crown (?:plans to|intends to|is planning to) send raw materials '
            rf'equivalent to (?:(?P<approx>around|about|approximately|roughly) )?'
            rf'(?P<count>{_NUMBER})(?: (?P<scale>thousand|million))? pigs '
            rf'(?:per year|a year|annually|each year) to {re.escape(plant)}(?=[,.\s]|$)', part, re.I)
        if match is None or _UNSAFE.search(part):
            continue
        if not 0 <= text.find(part) - text.find(processing) <= 700:
            continue
        count = _quantity(match['count'], match['scale'])
        if count is None:
            continue
        linked = processing + ' ' + part
        # A later correction or withdrawal must not leave an earlier plan
        # approved simply because its convenient positive sentence matches.
        if any(_RETRACTION.search(other) and _REFERENCE.search(other)
               for other in statements):
            return None
        if re.search(r'\b(?:live pigs|already processed|has processed|had processed)\b', linked, re.I):
            return None
        approx = '약 ' if match['approx'] else ''
        product = '돈육' if len(count) > 5 else '돼지고기'
        summary = (f'덴마크산 {product} 원료 연간 {approx}{count}두 상당을 '
                   '폴란드 가공업체에 공급 계획')
        if not 40 <= len(summary) <= 95:
            return None
        return summary, ' '.join((origin, processing, part))
    return None
