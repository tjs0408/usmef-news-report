"""Select original market passages for the requested country and commodity.

The output is evidence for translation, not a generated claim. Import/export
destinations may be other countries; their presence never alone disqualifies a
paragraph about the target country's products. Publication/access validation
and final claim validation remain the caller's responsibility.
"""
from __future__ import annotations

import re

from .grounded_korean_brief import source_statement_retracted


_COUNTRY = {
    'us': r'\bUnited States\b|\bU\.?S\.?(?=\W|$)|(?<!South )(?<!Latin )\bAmerican\b|미국',
    'australia': r'\bAustralia(?:n)?\b|호주',
    'eu_pork': r'\bGermany\b|\bGerman\b|\bDeutschland\b|\bEuropean(?: Union)?\b|\bEurope\b|\bEU\b|\bDenmark\b|\bDanish\b|\bSpain\b|\bSpanish\b|\bFrance\b|\bFrench\b|\bPoland\b|\bPolish\b|\bNetherlands\b|\bDutch\b|독일|유럽',
    'brazil_chicken': r'\bBrazil(?:ian)?\b|\bBrasil\b|\bbrasileir[oa]s?\b|브라질',
    'japan_egg': r'\bJapan(?:ese)?\b|일본|日本',
}
_SPECIES = {
    'beef': r'\bbeef\b|\bcattle\b|\bcalves\b|소고기|쇠고기|생우|송아지',
    'pork': r'\bpork\b|\bpigs?\b|\bhogs?\b|\bswine\b|Schweine\w*|돼지|돈육',
    'chicken': r'\bchickens?\b|\bbroilers?\b|\bpoultry\b|\bfrangos?\b|닭고기|육계|종란|병아리',
    'egg': r'\beggs?\b|\blayers?\b|계란|달걀|산란계|鶏卵|卵|たまご',
}
_DOMAINS = (
    r'\bprices?\b|pre[çc]os?|価格|가격|물가',
    r'\bsuppl(?:y|ies)\b|\bproduction\b|\bslaughter\b|\bstocks?\b|\bprocess(?:ing|ed)\b|\braw materials\b|produ[çc][ãa]o|生産|供給|공급|생산|도축|사육|출하',
    r'\bdemand\b|\bconsum(?:ption|er)\b|demanda|consumo|需要|消費|수요|소비',
    r'\bimports?\b|\bexports?\b|\btariffs?\b|\bquota\b|\bsafeguard\b|exporta[çc]|輸出|輸入|수입|수출|관세|교역',
    r'\bcosts?\b|\bfreight\b|\bfeed\b|\brain\b|\bdrought\b|\bheat\b|\bdisease\b|비용|운송|가뭄|강우|질병',
)
_CAUSE = r'\b(?:after|following|because|due to|result of|resulted in|driven by|despite|redirect\w*|reshap\w*)\b|때문|따라|영향|대응|재배분|여파|\bdevido\b|\bpression\w*'
_ANAPHOR = r'^(?:[“"\s]*)(?:This\b|These\b|Those\b|They\b|It\b|Much of this\b|For this\b|이는|이에|이처럼|이를|이러한)'


def country_market_context(kind: str | None, body: str) -> str | None:
    """Return a bounded intact target-country passage, when explicitly known.

    Do not invent country context for local reports that omit their country:
    return None and let the authenticated/local original's normal path run.
    When a global report names the target, other countries cannot win merely
    by having denser numeric or explanatory prose elsewhere in that report.
    """
    key = 'us' if kind in ('us', 'us_pork', 'us_chicken', 'us_egg') else kind
    if key not in _COUNTRY:
        return None
    country = re.compile(_COUNTRY[key], re.I)
    species_key = 'pork' if kind in ('us_pork', 'eu_pork') else 'chicken' if kind in ('us_chicken', 'brazil_chicken') else 'egg' if kind in ('us_egg', 'japan_egg') else 'beef'
    species = re.compile(_SPECIES[species_key], re.I)
    # Paragraphs preserve local country headings; long HTML paragraphs are
    # split only at actual sentence boundaries, never at decimal points.
    parts = [p.strip() for p in re.split(r'\n+|(?<=[.!?])\s+(?=[A-Z“"가-힣])', body[:7000]) if p.strip()]
    if not parts or not any(country.search(p) and species.search(p) for p in parts):
        return None
    anchors = []
    own_heading = False
    for index, part in enumerate(parts):
        heading = len(part) < 60 and not re.search(r'[.!?,;:]', part) and len(part.split()) <= 6
        if heading:
            own_heading = bool(country.search(part))
            continue
        direct = bool(country.search(part) and species.search(part))
        inherited = bool(own_heading and any(re.search(domain, part, re.I) for domain in _DOMAINS))
        anaphoric = bool(index and re.match(_ANAPHOR, part, re.I)
                         and country.search(parts[index-1]) and species.search(parts[index-1]))
        if not (direct or inherited or anaphoric) or source_statement_retracted(body, part):
            continue
        matched = [bool(re.search(domain, part, re.I)) for domain in _DOMAINS]
        if not any(matched):
            continue
        selected = [part]
        if index and re.match(_ANAPHOR, part, re.I) and country.search(parts[index-1]) and species.search(parts[index-1]):
            selected.insert(0, parts[index-1])
        if index + 1 < len(parts):
            following = parts[index+1]
            if (not source_statement_retracted(body, following)
                    and (country.search(following) and species.search(following)
                         or re.match(_ANAPHOR, following, re.I) and country.search(following))):
                selected.append(following)
        # Trade-policy changes and explicit causes outrank a dense bare count.
        score = sum(matched) * 2 + 3 * matched[3] + 3 * bool(re.search(_CAUSE, ' '.join(selected), re.I))
        score += bool(re.search(r'\d', part))
        anchors.append((score, -index, selected))
    if not anchors:
        return None
    selected = max(anchors, key=lambda item: item[:2])[2]
    result = ''
    for part in selected:
        if len(result) + len(part) + 1 > 1400:
            break  # keep whole source statements, never crop a condition
        result = (result + ' ' + part).strip()
    return result or None
