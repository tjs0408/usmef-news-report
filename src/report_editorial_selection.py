"""Small, source-bound editorial tie-breaker for weekly livestock candidates.

The 2025+ eKAPEPia archive contains 407 local-market paragraphs and 253
domestic-news paragraphs (``work/ekape_archive/*_records.json``).  Its useful
editorial shapes include a market change with an explanation, consumer prices,
and supply/trade changes.  These are descriptive reference patterns, NOT
frequency-trained weights or facts to copy into a different reporting week.

This module never establishes eligibility: callers must first check the actual
date, country, species, source and overseas-market relevance.  The 0..8 bonus is
only a tie-breaker WITHIN an existing relevance tier.  It neither writes a
summary nor infers a cause absent from the source passage.
"""

from __future__ import annotations

import html
import re
from typing import TypedDict


MAX_EDITORIAL_BONUS = 8
MAX_BODY_CHARACTERS = 9000
MAX_EVIDENCE_CHARACTERS = 600


class EditorialSelectionProfile(TypedDict):
    bonus: int
    themes: tuple[str, ...]
    pattern: str
    evidence: str


# Long forms are deliberate: a bare Korean '소', English 'egg' in 'nugget', or
# 'pig' in 'pigment' must not turn unrelated prose into livestock evidence.
_SPECIES = {
    "beef": r"쇠고기|소고기|한우|육우|생우|소값|소\s*가격|송아지|거세우|미경산우|육용우|\b(?:beef|cattle|calves|calf|veal|bovine)\b|牛肉|肉牛|牛価|bovinos?|bovina",
    "pork": r"돼지고기|돼지|돈육|양돈|\b(?:pork|pigs?|hogs?|swine)\b|豚肉|養豚|su[ií]nos?|su[ií]na|suinocultura|Schweine(?:fleisch|markt|preis\w*)?|Ferkel",
    "chicken": r"닭고기|육계|가금육|가금류|치킨|\b(?:chickens?|broilers?|poultry)\b|frangos?|avicultura|鶏肉|ブロイラー",
    "egg": r"계란|달걀|산란계|\b(?:eggs?|layers?)\b|\bovos?\b|鶏卵|採卵|たまご|タマゴ|卵価",
}
_SPECIES_RE = {key: re.compile(value, re.I) for key, value in _SPECIES.items()}
_KINDS = {
    "us": "beef", "australia": "beef", "domestic": "beef",
    "domestic_beef": "beef", "us_pork": "pork", "eu_pork": "pork",
    "domestic_pork": "pork", "us_chicken": "chicken",
    "brazil_chicken": "chicken", "domestic_chicken": "chicken",
    "us_egg": "egg", "japan_egg": "egg", "domestic_egg": "egg",
}

_THEMES = {
    "retail_price": re.compile(r"가격|물가|소매|소비자|시세|\b(?:prices?|retail|CPI|inflation|wholesale)\b|pre[çc]os?|価格|物価|相場|店頭|仕入れ|値上げ|値下げ|Preise?", re.I),
    "supply": re.compile(r"수급|공급|생산|도축|사육|재고|출하|입식|산란|입란|가공|운송|배송|리콜|회수|\b(?:supply|output|production|slaughter|herds?|inventory|placements?|sets|yardings?|processing|transport|deliver\w*|recalls?)\b|produ[çc][aã]o|abate|供給|生産|飼養|Schlacht", re.I),
    "trade": re.compile(r"수입|수출|관세|교역|쿼터|검역|통관|\b(?:imports?|exports?|tariffs?|quotas?|shipments?|trade|duties)\b|exporta[çc]|importa[çc]|輸入|輸出|関税|Export|Import", re.I),
    "demand": re.compile(r"수요|소비(?!자)|구매|외식|판매|판촉|\b(?:demand|consumption|buying|sales|barbecue|grilling)\b|consumo|需要|消費|Nachfrage", re.I),
    "cost_risk_policy": re.compile(r"사료비|생산비|운송|물류|인력|근로자|이민|단속|가뭄|폭염|조류인플루엔자|질병|방역|규제|정책|\b(?:costs?|feed|drought|floods?|flu|disease|labor|labour|immigration|restrictions?|policy)\b|seca|gripe|鳥インフル|猛暑|規制|飼料|エサ代|餌代|運送代|運送費|輸送費|運賃|物流費", re.I),
}
_MARKET_CHANGE = re.compile(
    r"증가|감소|상승|하락|확대|축소|둔화|회복|부진|강세|약세|안정|부족|과잉|차질|압박|반등|최고|최저|재개|중단|제한|수준|전망|기록|리콜|회수|늘|줄|올랐|내렸|"
    r"\b(?:rose|rise\w*|risen|rising|fell|fall\w*|increas\w*|decreas\w*|declin\w*|reduc\w*|higher|lower|up|down|tight\w*|shortage|surplus|record|recover\w*|slow\w*|disrupt\w*|resume\w*|restrict\w*|curb\w*|boost\w*|limited|limit|grew|grow\w*|recall\w*)\b|"
    r"alta|queda|aument\w*|redu[çc]\w*|上昇|下落|増加|減少|減産|上回|下回|値上げ|値下げ|値上がり|値下がり|高止まり|落ち着|品薄|据え置|横ばい|安定|推移|r[üu]ckgang|steig\w*|sink\w*", re.I,
)
_EXPLICIT_LINK = re.compile(
    r"때문|으로\s*인해|여파로|영향으로|에\s*따라|에\s*따른|면서|"
    r"(?:가뭄|폭염|질병|인력난|비용|공급부족|과잉공급|수요부진|소비위축)(?:으)?로|"
    r"(?:수요|소비|공급|생산|재고|출하)\s*(?:증가|감소|확대|축소|부족|과잉)(?:으)?로|"
    r"\b(?:because|due\s+to|driven\s+by|owing\s+to|amid|caus\w*|leading\s+to|result\w*\s+in|pushing|weigh\w*\s+on|as\s+(?:demand|supply|consumption|production))\b|"
    r"devido|em\s+raz[aã]o|por\s+causa|影響|背景|により|による|ため|ので|ことから|に伴い", re.I,
)
_QUANTITY = re.compile(r"\d[\d,.]*\s*(?:%|％|퍼센트|달러|원|엔|円|トン|羽|헤알|유로|톤|두|마리|개|파운드|만|억|million|billion|tonnes?|tons?|head|birds?|pounds?|yen|reais|euro|dollars?)|[$€¥]\s*\d", re.I)
_FOREIGN = re.compile(r"미국|호주|브라질|유럽|독일|일본|중국|해외|국제|캐나다|프랑스|영국|멕시코|뉴질랜드|태국|베트남|스페인|네덜란드|아르헨티나|\b(?:US|USA|U\.S\.|EU|USDA|China|Japan|Australia|Brazil|Germany|Europe|France|Canada|Mexico)\b|美|中|日", re.I)
_TRADE = _THEMES["trade"]
_MEDICAL = re.compile(r"백신|세포배양|계란\s*변이|임상|항암|의약|환자|\b(?:vaccines?|clinical|patients?|pharmaceutical|cell.cultur\w*)\b|ワクチン|細胞培養|医薬|患者|臨床|卵子|卵巣|受精卵", re.I)
_HISTORY = re.compile(r"창립|창업|설립|기념|연혁|\b(?:founded|established|anniversary|company\s+history)\b|(?:19\d{2}|200\d|201\d)년?.{0,24}(?:인수|설립|진출|설립|acquir|founded)", re.I)
_METADATA = re.compile(r"^(?:home|news|latest\s+news|menu|navigation|share|facebook|twitter|copyright|all\s+rights|published|updated|posted|by\s+|작성자|조회|등록일|기자|기사입력|기사수정|목록|홈\s*>|로그인|메뉴)\b", re.I)
_OTHER_CONSUMER_PRODUCTS = re.compile(r"휘발유|경유|원유|기름값|유가|우유|라면|전기요금|\b(?:gasoline|petrol|diesel|crude\s+oil|milk)\b", re.I)

# A bare Japanese 卵 is useful for local TV reporting, but it is not a global
# egg synonym: fish roe, medical prose and another food's price must not become
# evidence for Japanese chicken-egg markets. Country/date checks remain owned
# by the caller. These patterns only identify a local, original source span.
_JAPANESE_EGG_WORD = re.compile(
    r"鶏卵|採卵鶏|採卵|たまご|タマゴ|(?<![魚受産])卵(?!子|巣|胞|細胞|管|膜|黄|白|焼)")
_JAPANESE_FISH = re.compile(r"魚卵|イクラ|いくら|カジカ|かじか|サケ|さけ|鮭|鱈|タラ|たらこ|数の子|明太子")
_JAPANESE_OTHER_FOOD = re.compile(
    r"新米|お米|コメ|米価|玄米|白米|精米|米(?:の|は|が|も|を)|"
    r"魚卵|イクラ|カジカ|サケ|鮭|鱈|タラ|たらこ|数の子|明太子|ブリ|マグロ|"
    r"野菜|果物|水産|魚|キャベツ|白菜|レタス|トマト|きゅうり|牛乳|豚肉|牛肉|鶏肉")
_JAPANESE_EGG_MARKET = re.compile(
    r"価格|相場|店頭|小売|卸売|仕入れ|パック|個入り|個入|入荷|出荷|"
    r"飼料|エサ代|餌代|鳥インフル|需要|消費|生産|供給|販売|品薄|"
    r"値上げ|値下げ|値上がり|値下がり|高止まり|円")
_JAPANESE_SPEAKER = re.compile(r"(?:さん|氏|社長|店長|担当者)[）)」』]?[：:]?\s*$")
_JAPANESE_ANAPHOR = re.compile(r"^[「『（(\s]*(?:これ|それ|この|その|前週|前々週|今は|今後|年末)")
_JAPANESE_OUTLOOK_CONTINUATION = re.compile(
    r"^[「『\s]*(?:推移していく|推移する|と(?:思って|考えて|見て)います)")


def _japanese_food_egg_span(segment: str) -> str:
    """Keep an egg clause, not the adjacent rice/fish headline or predicate."""
    if _MEDICAL.search(segment):
        return ""
    mentions = []
    for match in _JAPANESE_EGG_WORD.finditer(segment):
        # カジカの卵 is fish roe, whereas サケは高値、タマゴは… is a
        # separate food-egg clause. A punctuation boundary separates them.
        prefix = re.split(r"[、,;；。]", segment[:match.start()])[-1]
        if _JAPANESE_FISH.search(prefix) and (
                match.group() == "卵" or re.search(r"の\s*$", prefix)):
            continue
        mentions.append(match)
    if not mentions:
        return ""
    first = mentions[0]
    start, end = 0, len(segment)
    for other in _JAPANESE_OTHER_FOOD.finditer(segment):
        if other.end() <= first.start():
            start = first.start()
        elif other.start() >= first.end():
            end = min(end, other.start())
    if end < len(segment):
        # Remove connective fragments leading into the next food section.
        boundary = max(segment.rfind("、", start, end), segment.rfind(",", start, end))
        if boundary >= start:
            end = boundary
    return segment[start:end].strip()


def japanese_egg_editorial_passages(title: str, body: str) -> list[str]:
    """Return ordered, source-only food-egg passages from Japanese reporting.

    An egg market subject anchors its immediately adjacent explanation/quote;
    an attribution line may be retained between that subject and explanation.
    A new commodity, medical sentence, metadata or unrelated prose closes the
    block. No themes or causes are pooled across those boundaries. A bare 卵
    is accepted only together with food-market language in its own clause.
    This helper does not establish country, publication date or eligibility.
    """
    title = _clean(title)[:350]
    body = _clean(body)[:MAX_BODY_CHARACTERS]
    title_key = re.sub(r"\s+", "", title).casefold()
    passages: list[str] = []
    current: list[str] = []
    attribution: list[str] = []

    def finish() -> None:
        if current:
            passages.append("\n".join(current))
            current.clear()
        attribution.clear()

    for match in re.finditer(r"[^。！？!?\n]+[。！？!?]?", body):
        segment = match.group().strip()
        if (not segment or re.sub(r"\s+", "", segment).casefold() == title_key
                or _METADATA.match(segment) or _MEDICAL.search(segment)
                or re.fullmatch(r"(?:https?://|www\.)\S+", segment)):
            finish()
            continue
        egg_span = _japanese_food_egg_span(segment)
        if egg_span and _JAPANESE_EGG_MARKET.search(egg_span):
            # A preceding unrelated commodity cannot donate its cause.
            if egg_span != segment:
                finish()
            current.extend(attribution)
            attribution.clear()
            current.append(egg_span)
            # Nor may a following commodity donate its next explanation.
            if not segment.endswith(egg_span):
                finish()
        elif current and not _JAPANESE_OTHER_FOOD.search(segment):
            if _JAPANESE_SPEAKER.search(segment) and len(segment) <= 100:
                attribution.append(segment)
            elif (_JAPANESE_EGG_MARKET.search(segment)
                    or (_JAPANESE_ANAPHOR.match(segment) and _QUANTITY.search(segment))
                    or (_JAPANESE_OUTLOOK_CONTINUATION.match(segment)
                        and re.search(r'価格|需要|供給|相場', current[-1]))):
                current.extend(attribution)
                attribution.clear()
                current.append(segment)
            else:
                finish()
        else:
            finish()
    finish()
    return passages


def _kind_passages(kind: str, title: str, body: str):
    """Yield paragraph/local-span pairs with a scoped Japanese bare-egg path."""
    # The same ranking API also checks already-written Korean briefs. Do not
    # treat a Korean translation as missing market context just because its
    # source section is Japanese. Non-Japanese prose keeps the existing
    # commodity matcher; country/language eligibility still belongs to callers.
    japanese_body = kind == "japan_egg" and bool(re.search(r"[\u3040-\u30ff]", body) or (
        not re.search(r"[가-힣]", body) and _JAPANESE_EGG_WORD.search(body)))
    if japanese_body:
        for passage in japanese_egg_editorial_passages(title, body):
            # Ranking may not reward a cause beyond the displayed evidence.
            yield passage, passage[:MAX_EVIDENCE_CHARACTERS]
        return
    species = _KINDS[kind]
    for paragraph in _source_paragraphs(title, body):
        for passage in _commodity_passages(paragraph, species):
            yield paragraph, passage


def _clean(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", str(value or ""))
    return html.unescape(value).replace("\u00a0", " ")


def _source_paragraphs(title: str, body: str):
    """Yield original body passages, never a headline/search metadata surrogate."""
    title_key = re.sub(r"\s+", "", title).casefold()
    for paragraph in re.split(r"\n+|(?<=[.!?。])\s+(?=[A-Z가-힣])", body):
        paragraph = re.sub(r"\s+", " ", paragraph).strip()
        if not paragraph or re.sub(r"\s+", "", paragraph).casefold() == title_key:
            continue
        if _METADATA.match(paragraph) or re.fullmatch(r"[\d\s:./-]+", paragraph):
            continue
        if re.fullmatch(r"(?:https?://|www\.)\S+", paragraph):
            continue
        yield paragraph[:1200]


def _commodity_passages(paragraph: str, species: str):
    """Bind evidence to a product clause, not another commodity's CPI section.

    A causal continuation may be joined only if the preceding clause actually
    names this species and neither clause introduces a competing livestock.
    All returned strings are unchanged source spans apart from whitespace.
    """
    own = _SPECIES_RE[species]
    competitors = [_SPECIES_RE[key] for key in _SPECIES_RE if key != species]
    competitors.append(_OTHER_CONSUMER_PRODUCTS)
    clauses = re.split(r"(?<!\d)[,;](?!\d)\s*|\s+(?:while|whereas|but)\s+|반면|한편", paragraph, flags=re.I)
    for index, clause in enumerate(clauses):
        mentions = list(own.finditer(clause))
        if not mentions:
            continue
        for mention in mentions:
            # On either side of a livestock list, prefer the actual local
            # predicate rather than carrying another species' market story.
            start = max(0, mention.start() - 150)
            end = min(len(clause), mention.end() + 300)
            for other in competitors:
                for match in other.finditer(clause):
                    if match.end() <= mention.start():
                        # Do not retain 'supply shortage caused prices to rise'
                        # AFTER another product noun but BEFORE our product.
                        # That predicate still belongs to the other product.
                        start = max(start, mention.start())
                    elif match.start() >= mention.end():
                        end = min(end, match.start())
            passage = clause[start:end].strip()
            if not passage:
                continue
            if index + 1 < len(clauses):
                following = clauses[index + 1].strip()
                if (re.match(r"(?:causing|pushing|leading\s+to|resulting\s+in)\b", following, re.I)
                        and not any(other.search(clause + following) for other in competitors)):
                    passage += ", " + following[:220]
            yield passage[:MAX_EVIDENCE_CHARACTERS]


def editorial_selection_profile(kind: str, title: str, body: str) -> EditorialSelectionProfile:
    """Explain the strongest small bonus supported by one species-local span.

    No count of keyword occurrences or numbers raises the score.  One coherent
    passage wins; themes from unrelated paragraphs are never pooled together.
    Domestic articles need an explicit foreign/trade context in the same source
    paragraph (a foreign macro-price headline may supply that context).
    """
    empty: EditorialSelectionProfile = {"bonus": 0, "themes": (), "pattern": "none", "evidence": ""}
    species = _KINDS.get(kind)
    if species is None:
        return empty
    title = _clean(title)[:350]
    body = _clean(body)[:MAX_BODY_CHARACTERS]
    domestic = kind == "domestic" or kind.startswith("domestic_")
    best = empty
    for paragraph, passage in _kind_passages(kind, title, body):
        if _MEDICAL.search(passage) or _HISTORY.search(passage):
            continue
        themes = tuple(name for name, regex in _THEMES.items() if regex.search(passage))
        # Cost/policy prose without a real product price/supply/trade/demand
        # fact cannot become an editorial market candidate by itself.
        core = set(themes).intersection({"retail_price", "supply", "trade", "demand"})
        if not core or not (_MARKET_CHANGE.search(passage) or _QUANTITY.search(passage)):
            continue
        foreign = bool(_FOREIGN.search(paragraph) or _TRADE.search(passage))
        if not foreign and _THEMES["retail_price"].search(title) and _FOREIGN.search(title):
            foreign = not bool(re.search(r"한국|국내|우리나라", paragraph))
        if domestic and not foreign:
            continue
        changed = bool(_MARKET_CHANGE.search(passage))
        # A cause word alone is insufficient: it needs a market movement
        # and two different market/issue dimensions in this SAME passage.
        linked = changed and len(themes) >= 2 and bool(_EXPLICIT_LINK.search(passage))
        if linked:
            bonus, pattern = MAX_EDITORIAL_BONUS, "linked_market_change"
        elif changed and core.intersection({"retail_price", "trade"}):
            bonus, pattern = 4, "price_or_trade_change"
        elif changed and len(core) >= 2:
            bonus, pattern = 3, "market_change"
        elif changed:
            bonus, pattern = 2, "market_change"
        else:
            bonus, pattern = 1, "market_indicator"
        if bonus > best["bonus"]:
            best = {"bonus": bonus, "themes": themes, "pattern": pattern, "evidence": passage}
    return best


def editorial_selection_bonus(kind: str, title: str, body: str) -> int:
    """Return a 0..8 source-supported, within-tier editorial tie-breaker."""
    return editorial_selection_profile(kind, title, body)["bonus"]


def editorial_candidate_link_supported(kind: str, title: str, body: str) -> bool:
    """Veto only a competing-species headline with no actual target fact.

    This is NOT another eligibility check.  The caller already checked date,
    country, species and market relevance.  General/macro headlines, or titles
    which also name the requested species, always retain that decision.  Only
    an explicitly competing-species headline is checked for the known failure:
    a poultry story offered as a pork alternative merely because a company's
    background product list names pork.

    Such a story remains useful if its body actually contains a target market
    fact, including a collective 'pork and chicken imports will increase' claim.
    No foreign-context or full-text requirement is added to general headlines.
    """
    species = _KINDS.get(kind)
    if species is None:
        return True
    own = _SPECIES_RE[species]
    title = _clean(title)[:350]
    if own.search(title) or not any(
            regex.search(title) for key, regex in _SPECIES_RE.items() if key != species):
        return True
    body = _clean(body)[:MAX_BODY_CHARACTERS]
    for paragraph in _source_paragraphs(title, body):
        if not own.search(paragraph) or _MEDICAL.search(paragraph) or _HISTORY.search(paragraph):
            continue
        for passage in _commodity_passages(paragraph, species):
            core = any(_THEMES[name].search(passage) for name in ("retail_price", "supply", "trade", "demand"))
            if core and (_MARKET_CHANGE.search(passage) or _QUANTITY.search(passage)):
                return True
        # A shared list must finish immediately before the common market
        # predicate.  This avoids borrowing a following poultry-only outcome.
        matches = sorted(
            (match for regex in _SPECIES_RE.values() for match in regex.finditer(paragraph)),
            key=lambda match: match.start(),
        )
        for index, mention in enumerate(matches):
            if not own.fullmatch(mention.group()):
                continue
            last = mention
            included_species = {species}
            for following in matches[index + 1:]:
                between = paragraph[last.end():following.start()]
                if (len(between) > 35 or not re.fullmatch(
                        r"[\s·‧ㆍ,/&]*(?:(?:and|or|와|과|및)[\s·‧ㆍ,/&]*)?(?:(?:캐나다|미국|브라질|호주|일본|유럽|독일|멕시코|중국)산?\s*)?",
                        between, re.I)):
                    break
                last = following
                included_species.update(key for key, regex in _SPECIES_RE.items() if regex.fullmatch(following.group()))
            if len(included_species) < 2:
                continue
            predicate = paragraph[last.end():last.end() + 150]
            if not re.match(r"^[\s·‧ㆍ,]*(?:등|의|는|은|이|가|를|을|및|모두|함께|수입|수출|가격|생산|공급|재고|소비|회수|리콜|\b(?:and|imports?|exports?|prices?|production|supply|inventor|consumption|recall))", predicate, re.I):
                continue
            # 'are among the company's products' is not a collective market
            # change.  Require a market action right after the species list.
            metric = re.search(r"수입|수출|가격|생산|공급|재고|소비|회수|리콜|\b(?:imports?|exports?|prices?|production|supply|inventory|consumption|recall)\b", predicate, re.I)
            if not metric or metric.start() > 28:
                continue
            if not (_MARKET_CHANGE.search(predicate) or _QUANTITY.search(predicate)):
                continue
            return True
    return False
