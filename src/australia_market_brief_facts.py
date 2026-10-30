"""Evidence-bound Australian rain/retention/weekly-cattle-market translation."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re
import unicodedata


_FOREIGN_MARKET = re.compile(
    r"\b(?:New Zealand|United States|U\.S\.|USA|Canada|Brazil|Germany|Japan|China|"
    r"United Kingdom|Indonesia|Argentina|South Africa)\b", re.I,
)


def native_australia_market_brief(body: str) -> tuple[str, str] | None:
    """Translate a stated forecast response and its own weekly cattle change.

    A rainy headline is not evidence that observed rainfall caused a previous
    week's change. This branch specifically requires the source's *forecast*
    to have encouraged *some* producers to retain stock, and the exact current
    national cattle-yardings sentence. Other weeks, sheep, regional sale counts,
    preliminary bookings, forecasts of yardings and denials are not substitutes.
    """
    if not isinstance(body, str) or not body.strip():
        return None
    text = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", body)).strip()
    heading = re.search(r"\bMarkets volatile\b", text, re.I)
    if not heading:
        return None
    # Country comes from the article's actual geographic context, not the UI.
    country_sentences = [sentence for sentence in re.split(r"(?<=[.!?])\s+", text[:heading.start()])
                         if re.search(r"\bAustralia\b|\bQueensland\b", sentence, re.I)]
    if not country_sentences:
        return None
    block = text[heading.end():]
    boundary = re.search(r"\bSaleyards offerings contract\b", block, re.I)
    if boundary:
        block = block[:boundary.start()]
    if _FOREIGN_MARKET.search(block):
        return None
    sentences = [sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+", block) if sentence.strip()]
    yarding_sentences = [sentence for sentence in sentences if re.search(r"\bNational cattle yardings\b", sentence, re.I)]
    retention_sentences = [sentence for sentence in sentences if re.search(r"\bproducers\b.*\bretain stock\b", sentence, re.I)]
    if len(yarding_sentences) != 1 or len(retention_sentences) != 1:
        return None
    yardings = re.fullmatch(
        r"National cattle yardings (?P<direction>fell|rose|increased|decreased) "
        r"(?P<rate>\d+(?:\.\d+)?)(?:pc|%) last week to "
        r"(?P<amount>\d{1,3}(?:,\d{3})+|\d+) head week-on-week"
        r"(?:, although the (?P<trend>declining|rising) trend had already started the week before "
        r"as the market anticipated upcoming rain)?\.", yarding_sentences[0], re.I,
    )
    retention = re.fullmatch(
        r"(?:Despite the return to a full selling week last week following the public holiday period, )?"
        r"forecast rainfall encouraged some producers to retain stock\.", retention_sentences[0], re.I,
    )
    if not yardings or not retention:
        return None
    try:
        rate = Decimal(yardings['rate'])
        amount = int(yardings['amount'].replace(',', ''))
    except (InvalidOperation, ValueError):
        return None
    if not (0 < rate < 100) or amount <= 0:
        return None
    decreasing = yardings['direction'].lower() in ('fell', 'decreased')
    if yardings['trend'] and (yardings['trend'].lower() == 'declining') != decreasing:
        return None
    direction = '감소' if decreasing else '증가'
    summary = (f"호주 강우 예보에 일부 소 농가 출하 보류, 지난주 출하두수 "
               f"전주비 {yardings['rate']}% {direction}")
    # Preserve the literal count and period for inspection, without squeezing
    # a second independent number into the one-line report field.
    evidence = ' '.join((country_sentences[0], yarding_sentences[0], retention_sentences[0]))
    return (summary, evidence) if 40 <= len(summary) <= 95 else None
