"""Literal Australian beef-export and observed processing-supply event frames.

Monthly totals and calendar-year-to-date US shipments need explicit periods and
destinations. Observed weather/supply events need a literal causal lead and local
rain observation. No dates, values, causes or article URLs are supplied by code.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re
import unicodedata


_MONTHS = {
    'january': 1, 'february': 2, 'march': 3, 'april': 4, 'may': 5, 'june': 6,
    'july': 7, 'august': 8, 'september': 9, 'october': 10, 'november': 11, 'december': 12,
}
_MONTH = '(?:' + '|'.join(_MONTHS) + ')'
_NUMBER = r'(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?'
_QUALIFIER = r'(?:about|around|approximately|roughly|more than|over|less than|under)'
_UNIT = r'(?:tonnes?|metric\s+tons?|t)\b'
_BAD = re.compile(
    r'\b(?:if|unless|forecast\w*|project\w*|expect\w*|anticipat\w*|predict\w*|'
    r'estimat\w*|preliminary|provisional|unconfirmed|reportedly|would|could|might|may|will|'
    r'not|no|never|denied|denies|retracted|corrected)\b', re.I)


def _quantity(raw: str) -> str | None:
    try:
        value = Decimal(raw.replace(',', ''))
    except InvalidOperation:
        return None
    if not value.is_finite() or not 0 < value < 100_000_000:
        return None
    if value >= 10_000:
        whole = int(value // 10_000)
        rest = value - whole * 10_000
        return f'{whole}만' + (f' {_decimal(rest)}' if rest else '')
    return _decimal(value)


def _decimal(value: Decimal) -> str:
    return format(value, 'f').rstrip('0').rstrip('.') if value % 1 else str(int(value))


def _qualified(raw: str | None, value: str) -> str:
    qualifier = (raw or '').lower()
    if qualifier in ('about', 'around', 'approximately', 'roughly'):
        return '약 ' + value
    if qualifier in ('less than', 'under'):
        return value + ' 미만'
    if qualifier in ('more than', 'over'):
        return value + ' 초과'
    return value


def _change(tail: str, *, year: bool = False) -> tuple[str, str, str | None] | None:
    period = (r'(?:on|from|over|compared (?:with|to))\s+(?:the\s+)?'
              r'(?:same\s+(?:period|\w+\s+months)|this\s+period)\s+last\s+year'
              if year else r'(?:on|from|over|compared (?:with|to))\s+(?:the\s+)?(?:previous|prior)\s+month')
    match = re.search(
        rf'(?:(?P<qual>{_QUALIFIER})\s+)?(?P<rate>\d+(?:\.\d+)?)\s*(?:pc|%|percent|per cent)\s+'
        rf'(?P<direction>decline|decrease|increase|rise|fall|growth|reduction|higher|lower)\s+{period}', tail, re.I)
    if not match:
        match = re.search(
            rf'(?P<direction>up|down)\s+(?:{_NUMBER}\s*{_UNIT}\s+or\s+)?'
            rf'(?:(?P<qual>{_QUALIFIER})\s+)?(?P<rate>\d+(?:\.\d+)?)\s*(?:pc|%|percent|per cent)\s+{period}', tail, re.I)
    if not match:
        return None
    try:
        rate = Decimal(match['rate'])
    except InvalidOperation:
        return None
    if not 0 < rate < 1000:
        return None
    direction = '감소' if match['direction'].lower() in ('decline', 'decrease', 'fall', 'reduction', 'lower', 'down') else '증가'
    if direction == '감소' and rate >= 100:
        return None
    return match['rate'], direction, match['qual']


def _finish(variants: list[str], evidence: str) -> tuple[str, str] | None:
    from .article_hwpx_layout import summary_reference_layout
    for summary in variants:
        if (40 <= len(summary) <= 95
                and summary_reference_layout(summary, 'australia')['withinLineLimit']):
            return summary, evidence
    return None


def _weather_processing_brief(sentences: list[str]) -> tuple[str, str] | None:
    """Observed rain pressure, not a rain forecast turned into an outcome.

    Only the existing current impact is summarized. An explicitly *potential*
    longer-term effect is not rewritten as an established long-term shortage.
    Queensland/NSW identify the observed Australian rain; a forecast mentioning
    Australia after a foreign rain observation cannot supply that provenance.
    """
    leads = []
    for sentence in sentences[:3]:
        match = re.fullmatch(
            r"This week's (?:rain|rainfall) event is (?:pressuring|tightening) supply for beef processors\s*"
            r"(?:[–—-]\s*both short and potentially,?\s*longer[ -]term\s*[–—-]\s*)?"
            r"[,;]?\s*(?:pushing|lifting|driving) some direct consignment offers and saleyards markets "
            r"(?P<direction>higher|lower)\.", sentence, re.I)
        if match and not _BAD.search(sentence):
            leads.append((match['direction'].lower(), sentence))
    if len(leads) != 1:
        return None
    observations = []
    for sentence in sentences[:4]:
        # Do not use the geography from the following forecast as evidence of
        # where observed rainfall occurred.
        observed = re.split(r'\bwith the (?:prospect|forecast)\b', sentence, maxsplit=1, flags=re.I)[0].rstrip(' ,')
        if (_BAD.search(observed)
                or re.search(r'\b(?:New Zealand|United States|Canada|Brazil|China|Japan)\b', observed, re.I)):
            continue
        if (re.search(r"\bthere(?:'s| has) been\b.{0,70}\brain\b", observed, re.I)
                and re.search(r'\b(?:Australia|Queensland|NSW|New South Wales)\b', observed, re.I)
                and re.search(r'\bover the past week\b|\bin recent days\b|\bthis week\b', observed, re.I)):
            observations.append(observed)
    if not observations:
        return None
    direction, lead = leads[0]
    movement = '상승' if direction == 'higher' else '하락'
    summary = f'호주 강우로 소고기 가공업체 공급 압박, 일부 직거래·가축시장 가격 {movement}'
    return _finish([summary], lead + ' ' + observations[0])


def native_australia_export_brief(body: str) -> tuple[str, str] | None:
    """Return one grounded Korean report sentence and its literal source evidence."""
    if not isinstance(body, str) or not body.strip():
        return None
    text = re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', body)).strip().replace('’', "'")
    # Export grinding-meat value is a different series from domestic cattle
    # prices. Preserve the source's own origin, product, start month and
    # approximation rather than borrowing the US market's other quotations.
    grinding = re.search(
        rf"THERE'S been a sharp (?P<change>decline|increase) in the value of Australian export lean trimmings "
        rf"used for hamburger beef this year, (?P<verb>falling|rising) "
        rf"(?P<approx>around|about|approximately) (?P<rate>\d+(?:\.\d+)?) percent since (?P<month>{_MONTH})[.]",
        text, re.I)
    if (grinding and not _BAD.search(grinding[0])
            and (grinding['change'].lower(), grinding['verb'].lower()) in (('decline', 'falling'), ('increase', 'rising'))
            and 0 < Decimal(grinding['rate']) < 100
            and not re.search(r'\b(?:corrected|retracted|misreported|incorrect)\b', text, re.I)):
        month = _MONTHS[grinding['month'].lower()]
        movement = '하락' if grinding['change'].lower() == 'decline' else '상승'
        variants = [f"호주 햄버거용 저지방 쇠고기 원료 수출가격, 올해 {month}월 이후 약 {grinding['rate']}% {movement}",
                    f"호주 저지방 쇠고기 원료 수출가격은 올해 {month}월 이후 약 {grinding['rate']}% {movement}한 수준"]
        return _finish(variants, grinding[0])
    sentences = [item.strip() for item in re.split(r'(?<=[.!?])\s+(?=[A-Z“])', text) if item.strip()]
    weather = _weather_processing_brief(sentences)
    if weather:
        return weather
    headers = []
    for index, sentence in enumerate(sentences):
        match = re.search(rf"\bAustralia(?:'s|n)\s+(?P<month>{_MONTH})\s+beef\s+export(?:s|\s+statistics)?\b", sentence, re.I)
        if not match:
            match = re.search(rf'\bAustralian\s+beef\s+exports?\s+(?:for|in)\s+(?P<month>{_MONTH})\b', sentence, re.I)
        if match and not _BAD.search(sentence):
            headers.append((index, _MONTHS[match['month'].lower()], sentence))
    # A place name or UI section alone cannot establish Australian beef scope.
    if len(headers) != 1:
        return None
    header_index, month, header = headers[0]
    monthly = []
    for sentence in sentences[header_index + 1:header_index + 3]:
        match = re.match(
            rf'^Total\s+(?:beef\s+)?exports\s+for\s+the\s+month(?:\s+to\s+all\s+markets)?\s+'
            rf'(?:reached|totalled|totaled|were|amounted to)\s+'
            rf'(?:(?P<qual>{_QUALIFIER})\s+)?(?P<amount>{_NUMBER})\s*{_UNIT}(?P<tail>.*)$', sentence, re.I)
        if not match or _BAD.search(sentence):
            continue
        amount = _quantity(match['amount'])
        change = _change(match['tail'])
        if amount and change:
            rate, direction, rate_qual = change
            quantity = _qualified(match['qual'], amount + '톤')
            percent = _qualified(rate_qual, rate + '%')
            variants = [f'호주 {month}월 전체 시장 쇠고기 수출량은 전월 대비 {percent} {direction}한 {quantity} 기록',
                        f'호주 {month}월 쇠고기 총수출량은 전월 대비 {percent} {direction}한 {quantity} 기록']
            monthly.append((variants, header + ' ' + sentence))
    if len(monthly) == 1:
        return _finish(*monthly[0])
    if monthly:
        return None  # Ambiguous/conflicting duplicate totals are not guessed.
    calendar = [sentence for sentence in sentences if re.search(
        rf'\bcalendar\s+year\s+to\s+date\b.*\b(?:by|to)\s+the\s+end\s+of\s+{_MONTH}\b', sentence, re.I)
        and not _BAD.search(sentence)]
    if len(calendar) != 1:
        return None
    calendar_month = re.search(rf'\bend\s+of\s+(?P<month>{_MONTH})\b', calendar[0], re.I)
    if not calendar_month or _MONTHS[calendar_month['month'].lower()] != month:
        return None
    us = []
    for sentence in sentences:
        match = re.match(
            rf'^Year\s+to\s+date,?\s+(?:beef\s+)?exports\s+to\s+(?:the\s+)?(?:US|USA|United States)\s+'
            rf'have\s+(?:already\s+)?reached\s+(?:a\s+phenomenal\s+)?'
            rf'(?:(?P<qual>{_QUALIFIER})\s+)?(?P<amount>{_NUMBER})\s*{_UNIT}(?P<tail>.*)$', sentence, re.I)
        if not match or _BAD.search(sentence):
            continue
        amount = _quantity(match['amount'])
        change = _change(match['tail'], year=True)
        if amount and change:
            rate, direction, rate_qual = change
            quantity = _qualified(match['qual'], amount + '톤')
            percent = _qualified(rate_qual, rate + '%')
            # "월 누적" denotes the calendar-year-to-date total through that
            # month, not that month's isolated shipment volume.
            variants = [f'호주 {month}월 누적 대미 쇠고기 수출량 {quantity}, 전년 동기비 {percent} {direction}',
                        f'호주 {month}월까지 대미 쇠고기 수출은 누적 {quantity}, 전년 동기비 {percent} {direction}']
            us.append((variants, ' '.join((header, calendar[0], sentence))))
    return _finish(*us[0]) if len(us) == 1 else None
