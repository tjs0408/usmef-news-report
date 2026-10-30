"""Literal USDA poultry-market statements and monthly egg production.

The source's own scope, reporting month, physical quantity and comparison are
required. This module supplies no selected-week facts or publisher URLs.
"""
from decimal import Decimal, InvalidOperation
import re
import unicodedata

from .grounded_korean_brief import source_statement_retracted


_MONTHS = dict(zip(('January', 'February', 'March', 'April', 'May', 'June',
                   'July', 'August', 'September', 'October', 'November', 'December'), range(1, 13)))
_OTHER_COUNTRY = re.compile(r'\b(?:Canada|Canadian|Brazil|Brazilian|China|Chinese|Japan|Japanese|'
                            r'Germany|German|Mexico|Mexican|European Union|Australia|Australian)\b', re.I)


def _egg_production(body: str) -> tuple[str, str] | None:
    match = re.search(
        rf'The USDA says (?P<amount>\d+(?:\.\d+)?) (?P<scale>billion|million) eggs were produced '
        rf'in (?P<month>{"|".join(_MONTHS)}), (?P<direction>up|down) '
        r'(?P<rate>\d+(?:\.\d+)?)% on the year(?=[,.\s]|$)', body, re.I)
    if not match:
        return None
    sentence = next((part for part in re.split(r'(?<=[.!?])\s+', body) if match[0] in part), '')
    if (not sentence or _OTHER_COUNTRY.search(body[:match.end()])
            or re.search(r'\b(?:not|never|could|might|may|expected|forecast|estimated)\b', sentence, re.I)
            or source_statement_retracted(body, sentence)):
        return None
    try:
        total = Decimal(match['amount']) * (1000000000 if match['scale'].lower() == 'billion' else 1000000)
        rate = Decimal(match['rate'])
    except InvalidOperation:
        return None
    if total <= 0 or total != total.to_integral_value() or not 0 < rate < 100:
        return None
    count = int(total)
    parts = []
    for factor, label in ((100000000, '억'), (10000, '만')):
        whole, count = divmod(count, factor)
        if whole:
            parts.append(str(whole) + label)
    if count:
        parts.append(str(count))
    amount = ' '.join(parts)
    month = next(number for name, number in _MONTHS.items() if name.lower() == match['month'].lower())
    movement = '증가' if match['direction'].lower() == 'up' else '감소'
    summary = f"미국 {month}월 계란 생산량은 전년 동월보다 {match['rate']}% {movement}한 {amount}개를 기록"
    return summary, sentence


def _broiler_market(body: str) -> tuple[str, str] | None:
    if (not re.search(r'Daily National Broiler Market-At-A-Glance', body, re.I)
            or not re.search(r'Agricultural Marketing Service|USDA AMS', body, re.I)
            or not re.search(r'Atlanta, Georgia', body, re.I)):
        return None
    heading = re.search(r'DOMESTIC MARKET HIGHLIGHTS', body, re.I)
    boundary = re.search(r'EXPORT MARKET HIGHLIGHTS', body, re.I)
    if not heading or not boundary or heading.end() >= boundary.start():
        return None
    domestic = body[heading.end():boundary.start()]
    export = body[boundary.end():].split('Source:', 1)[0].strip()
    required = ('WOGs are trending steady.', 'Floor stocks are adequate.',
                'Demand is about moderate.', 'The market is overall steady.')
    if (not all(phrase in domestic for phrase in required)
            or export != 'Export market is moderate to active.'
            or _OTHER_COUNTRY.search(domestic + ' ' + export)
            # A different cut can receive little attention without negating
            # the independently stated WOG/overall market observations.
            or re.search(r'\b(?:not|never|forecast|expected)\b', ' '.join(required) + ' ' + export, re.I)
            or any(source_statement_retracted(body, phrase) for phrase in required)):
        return None
    summary = ('미국 닭고기 통닭·전체 시장은 보합, 재고 적정·수요 대체로 보통인 가운데 '
               '수출 시장은 보통~활발한 수준')
    evidence = 'DOMESTIC MARKET HIGHLIGHTS ' + ' '.join(required) + ' EXPORT MARKET HIGHLIGHTS ' + export
    return summary, evidence


def native_us_poultry_supply_brief(kind: str, body: str) -> tuple[str, str] | None:
    text = re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', str(body))).strip()
    return _broiler_market(text) if kind == 'us_chicken' else _egg_production(text) if kind == 'us_egg' else None
