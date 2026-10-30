"""Compare real foreign market issues without rewarding an easy parser.

This is an editorial tie-breaker, NOT an eligibility gate or a summary writer.
The caller must first verify publication date, country, species, original text
and relevance tier. A richer issue may outrank a weekly count only inside that
same tier; this module never authorizes another week or another commodity.
"""
from __future__ import annotations

import re
from typing import TypedDict

from . import report_editorial_selection as editorial
from .grounded_korean_brief import source_statement_retracted


FOREIGN_MARKET_KINDS = frozenset({
    'us', 'australia', 'us_pork', 'eu_pork', 'us_chicken',
    'brazil_chicken', 'us_egg', 'japan_egg',
})

_ISSUE_QUERIES = {
    'us': (
        'US beef demand retail',
        'US beef tariffs imports',
        'US cattle drought labor',
    ),
    'australia': (
        'Australia beef demand retail',
        'Australia beef tariffs exports',
        'Australia cattle drought labour',
    ),
    'us_pork': (
        'US pork demand retail',
        'US pork tariffs exports',
        'US hog disease feed costs',
    ),
    'eu_pork': (
        'Deutschland Schweinefleisch Nachfrage',
        'EU Schweinefleisch Handel',
        'Deutschland Schweine Tierseuchen Futterkosten',
    ),
    'us_chicken': (
        'US chicken demand retail',
        'US chicken tariffs exports',
        'US poultry bird flu costs',
    ),
    'brazil_chicken': (
        'Brasil frango consumo varejo',
        'Brasil frango exportações tarifas',
        'Brasil frango gripe aviária custos',
    ),
    'us_egg': (
        'US eggs demand retail',
        'US eggs imports tariffs',
        'US eggs bird flu',
    ),
    'japan_egg': (
        '日本 卵 価格 需要',
        'タマゴ 値上げ 飼料費 供給',
        'たまご 生産 流通 ニュース',
    ),
}

_EVENT_OR_PROMOTION = re.compile(
    r'\b(?:webinar|seminar|conference|awards?|carcase competition|carcass competition|'
    r'leaders?(?:hip)? program|sponsored|advertorial|buy now|register now)\b|'
    r'시상식|품평회|박람회|세미나|설명회|기념행사|협찬\s*광고|행사\s*개최|'
    r'ウェビナー|セミナー|展示会|授賞|seminário|premiação', re.I)
_POLICY_ACTION = re.compile(
    r'관세.{0,30}(?:철폐|면제|인하|부과|유예)|수입.{0,25}(?:금지|허용|재개|중단)|'
    r'검역.{0,20}(?:완화|강화)|규제.{0,20}(?:완화|강화)|'
    r'\b(?:suspend\w*|waiv\w*|abolish\w*|scrap\w*|lift\w*|impos\w*|ban\w*|'
    r'approv\w*|allow\w*|resum\w*|restrict\w*)\b|'
    r'解禁|禁止|再開|停止|撤廃|免除|制限|suspens\w*|retoma\w*|libera\w*|'
    r'Zoll\w*|Einfuhrverbot|Ausfuhrverbot', re.I)
_POLICY_CONTEXT = re.compile(
    r'관세|쿼터|검역|수입|수출|규제|정부|\b(?:tariffs?|quotas?|imports?|exports?|'
    r'borders?|bans?|government|regulat\w*|restrictions?|inspection)\b|'
    r'輸入|輸出|関税|検疫|政府|規制|tarif\w*|importa\w*|exporta\w*|'
    r'Zoll\w*|Einfuhr\w*|Ausfuhr\w*|Regierung', re.I)
_EXTRA_LINK = re.compile(
    r'\bto\s+(?:ease|curb|support|reduce|increase|boost)\b|'
    r'(?:높아진|낮아진|줄어든|늘어난).{0,16}(?:수요|소비|공급)|'
    r'zum\s+Rückgang|aufgrund|wegen|führt\s+zu|para\s+(?:reduzir|aumentar)', re.I)
_EXTRA_CHANGE = re.compile(
    r'\b(?:halt\w*|suspend\w*|waiv\w*|ban\w*|impos\w*|lift\w*|shift\w*|'
    r'switch\w*|weak\w*|strong\w*)\b|需要減|需要増|供給不足|回復|再開|'
    r'変化|停滞|減少|増加|値上がり|値下がり|高止まり|落ち着|品薄|'
    r'nachlass\w*|steig\w*|sink\w*|rückläufig|'
    r'recuo|recuar\w*|enfraquec\w*', re.I)
_MARKET_STATE = re.compile(
    r'보합|충분|부족|안정|\b(?:steady|adequate|moderate|tight|shortage|surplus)\b|'
    r'横ばい|不足|安定|据え置き|高止まり|estável|estáveis|knapp|stabil', re.I)
_CONSUMER_PRICE = re.compile(
    r'소비자\s*가격|소비자가격|소매\s*가격|소매가격|소비자물가|'
    r'\b(?:retail|consumer|grocery|CPI)\b|小売価格|消費者物価|店頭価格|店頭|'
    r'varejo|consumidor|Verbraucherpreis\w*|Einzelhandel', re.I)

# Add local-language market vocabulary without making the caller's country or
# date decision. There is deliberately no publisher whitelist here.
_EXTRA_THEMES = {
    'retail_price': re.compile(r'cotação|cotações|小売|卸売|Verbraucherpreis\w*', re.I),
    'supply': re.compile(r'Angebot|Erzeugung|Produktion|出荷|入荷|産卵|在庫|oferta', re.I),
    'trade': re.compile(r'Handel|Einfuhr|Ausfuhr|Zoll\w*|Import\w*|Export\w*', re.I),
    'demand': re.compile(r'Verbrauch|Absatz|Kauf\w*|Nachfrage|小売需要|買い|購買|demanda', re.I),
    'cost_risk_policy': re.compile(
        r'Futterkosten|Arbeitskräft\w*|Tierseuchen|Dürre|飼料費|人手不足|高温|'
        r'飼料価格|custos|ração|mão de obra|política', re.I),
}


class MarketIssueProfile(TypedDict):
    level: int
    themes: tuple[str, ...]
    pattern: str
    evidence: str


def issue_queries(kind: str) -> tuple[str, ...]:
    """Three unrestricted local-language issue searches; no dates guessed."""
    return _ISSUE_QUERIES.get(kind, ())


def _rank(profile: MarketIssueProfile) -> tuple[int, int, int]:
    pattern_strength = {
        'none': 0, 'market_indicator': 0, 'consumer_price_change': 1,
        'demand_or_trade_change': 1, 'policy_market_change': 2,
        'linked_market_change': 3,
    }[profile['pattern']]
    return profile['level'], pattern_strength, min(len(profile['themes']), 4)


def market_issue_profile(kind: str, title: str, body: str) -> MarketIssueProfile:
    """Rank one commodity-local source span, not keyword density or fluency.

    Level 1 is a valid but repetitive statistic/quote. Level 2 is a consumer,
    demand, trade or policy change. Level 3 explicitly links a market movement
    to another market aspect. Headlines never supply evidence or extra themes.
    """
    empty: MarketIssueProfile = {'level': 0, 'themes': (), 'pattern': 'none', 'evidence': ''}
    if kind not in FOREIGN_MARKET_KINDS or not isinstance(body, str):
        return empty
    title = editorial._clean(title)[:350]
    body = editorial._clean(body)[:editorial.MAX_BODY_CHARACTERS]
    best = empty
    for paragraph, passage in editorial._kind_passages(kind, title, body):
        if source_statement_retracted(body, paragraph):
            continue
        if (editorial._MEDICAL.search(passage) or editorial._HISTORY.search(passage)
                or _EVENT_OR_PROMOTION.search(passage)):
            continue
        themes = tuple(name for name, regex in editorial._THEMES.items()
                       if regex.search(passage) or _EXTRA_THEMES[name].search(passage))
        core = set(themes).intersection({'retail_price', 'supply', 'trade', 'demand'})
        changed = bool(editorial._MARKET_CHANGE.search(passage) or _EXTRA_CHANGE.search(passage))
        policy = bool(_POLICY_ACTION.search(passage) and _POLICY_CONTEXT.search(passage)
                      and core.intersection({'trade', 'supply'}))
        if not core or not (changed or policy or editorial._QUANTITY.search(passage)
                            or _MARKET_STATE.search(passage)):
            continue
        linked = (changed or policy) and len(themes) >= 2 and bool(
            editorial._EXPLICIT_LINK.search(passage) or _EXTRA_LINK.search(passage))
        if linked:
            level, pattern = 3, 'linked_market_change'
        elif policy:
            level, pattern = 2, 'policy_market_change'
        elif changed and core.intersection({'demand', 'trade'}):
            level, pattern = 2, 'demand_or_trade_change'
        elif changed and 'retail_price' in core and _CONSUMER_PRICE.search(passage):
            level, pattern = 2, 'consumer_price_change'
        else:
            level, pattern = 1, 'market_indicator'
        candidate: MarketIssueProfile = {
            'level': level, 'themes': themes, 'pattern': pattern,
            'evidence': passage[:editorial.MAX_EVIDENCE_CHARACTERS],
        }
        if _rank(candidate) > _rank(best):
            best = candidate
    return best


def market_issue_rank(kind: str, title: str, body: str) -> tuple[int, int, int]:
    """Deterministic within-tier rank, independent of native/model readiness."""
    return _rank(market_issue_profile(kind, title, body))
