"""Small, fail-closed translations of USDA's own national market statements.

This is not a general summarizer. Every rendered clause must have one complete
recognized source sentence. Regional/export observations, estimates, negations,
and comparison periods are never silently turned into national current facts.
Publication dates and source authenticity are checked by the caller.
"""
from __future__ import annotations

import re
import unicodedata


_REGIONS = (r"California|New York|Midwest|Southeast|Southwest|Northeast|"
            r"Northwest|South Central|regional")
_MOVEMENT = {
    "steady": "보합", "lower": "하락", "higher": "상승",
    "weak": "약세", "firm": "강세", "steady to lower": "보합~하락",
    "steady to higher": "보합~상승", "steady to weak": "보합~약세",
    "steady to firm": "보합~강세",
}
_MOVEMENT_PATTERN = "|".join(sorted(_MOVEMENT, key=len, reverse=True))


def _sentences(text: str) -> list[str]:
    return [re.sub(r"\s+", " ", item).strip()
            for item in re.split(r"(?<=[.!?])\s+", text.strip()) if item.strip()]


def _one_statement(sentences: list[str], starts: str, pattern: str):
    """Do not pick a convenient assertion beside a contradictory statement."""
    applicable = [item for item in sentences if re.match(starts, item, re.I)]
    if not applicable:
        return None
    matches = [re.fullmatch(pattern, item, re.I) for item in applicable]
    if any(match is None for match in matches):
        return None
    distinct = {tuple(sorted(match.groupdict().items())) for match in matches}
    if len(distinct) != 1:
        return None
    return matches[0], applicable[0]


def _broiler_fact(body: str) -> tuple[str, str] | None:
    heading = re.search(r"\bDOMESTIC\s+MARKET\s+HIGHLIGHTS\b", body, re.I)
    if not heading:
        return None
    block = body[heading.end():]
    boundary = re.search(rf"\b(?:EXPORT\s+MARKET\s+HIGHLIGHTS|{_REGIONS}|Source:)\b", block, re.I)
    if boundary:
        block = block[:boundary.start()]
    sentences = _sentences(block)
    wog = _one_statement(
        sentences, r"WOGs?\b",
        rf"WOGs? are trending (?P<movement>{_MOVEMENT_PATTERN}) to start the week\.",
    )
    stocks = _one_statement(
        sentences, r"Floor stocks\b",
        r"Floor stocks are adequate for the (?P<demand>light|moderate|active) demand\.",
    )
    market = _one_statement(
        sentences, r"The market\b",
        rf"The market is (?P<movement>{_MOVEMENT_PATTERN})\.",
    )
    if not wog or not stocks or not market:
        return None
    demand = {"light": "약한", "moderate": "보통", "active": "활발한"}[stocks[0]['demand'].lower()]
    summary = (f"미국 닭고기 통닭 시장은 주 초 {_MOVEMENT[wog[0]['movement'].lower()]}, "
               f"전체 시장은 {_MOVEMENT[market[0]['movement'].lower()]}이며 "
               f"재고는 {demand} 수요에 적정 수준")
    return summary, "DOMESTIC MARKET HIGHLIGHTS " + " ".join(item[1] for item in (wog, stocks, market))


def _egg_fact(body: str) -> tuple[str, str] | None:
    price_lead = re.search(r"\bNational\s+FOB\s+shell\s+egg\s+weighted\s+average\s+prices\b", body, re.I)
    if not price_lead:
        return None
    block = body[price_lead.start():]
    boundary = re.search(rf"\n\s*\n|\b(?:{_REGIONS}|NEGOTIATED|NATIONAL\s+SHELL|Source:)\b", block, re.I)
    if boundary:
        block = block[:boundary.start()]
    sentences = _sentences(block)
    price = _one_statement(
        sentences, r"National FOB shell egg weighted average prices\b",
        rf"National FOB shell egg weighted average prices are "
        rf"(?P<qualifier>mostly |generally |largely |about )?"
        rf"(?P<movement>{_MOVEMENT_PATTERN})(?P<test> on light test)?\.",
    )
    supplies = _one_statement(
        sentences, r"Supplies\b",
        r"Supplies (?:are|remain) (?P<qualifier>mostly |generally |largely )?"
        r"(?P<level>moderate to fully adequate|moderate)\.",
    )
    if not price or not supplies:
        return None
    price_qualifier = "대체로 " if price[0]['qualifier'] else ""
    supply_qualifier = "대체로 " if supplies[0]['qualifier'] else ""
    test = "(거래 제한)" if price[0]['test'] else ""
    supply = "보통~충분" if supplies[0]['level'].lower() == "moderate to fully adequate" else "보통"
    movement = _MOVEMENT[price[0]['movement'].lower()]
    summary = (f"미국 계란 전국 FOB 가중평균가 {price_qualifier}{movement}{test}, "
               f"공급 {supply_qualifier}{supply} 수준")
    if len(summary) < 40:
        summary = (f"미국 계란의 전국 FOB 가중평균 가격은 {price_qualifier}{movement}{test} 흐름이며 "
                   f"공급은 {supply_qualifier}{supply} 수준")
    return summary, price[1] + " " + supplies[1]


def native_usda_brief(kind: str, body: str) -> tuple[str, str] | None:
    """Return a Korean market brief and its exact evidence, without AI calls."""
    if not isinstance(body, str) or not body.strip():
        return None
    text = unicodedata.normalize("NFKC", body)
    fact = _broiler_fact(text) if kind == "us_chicken" else _egg_fact(text) if kind == "us_egg" else None
    if fact and 40 <= len(fact[0]) <= 95:
        return fact
    return None
