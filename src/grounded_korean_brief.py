"""Conservative, source-only Korean brief proposals, independent of a week.

These are candidates, not approved summaries. The caller must still apply its
quantity, modality, length and page-layout publication gates. No model output,
headline claim or neighbouring commodity supplies facts to this module.
"""
from __future__ import annotations

import re


_COUNTRIES = (
    "미국|호주|브라질|독일|일본|중국|유럽|북한|홍콩|베트남|태국|캐나다|멕시코|"
    "영국|프랑스|스페인|덴마크|네덜란드|러시아|인도|대만|이란|아르헨티나|"
    "뉴질랜드|싱가포르|필리핀|인도네시아|말레이시아|칠레|이탈리아|아일랜드|"
    "벨기에|벨라루스|튀르키예|해외"
)
_FOREIGN = re.compile(
    # In particular, '것이란 예상' is NOT Iran, and '견인도' is NOT India.
    rf"(?<![가-힣])(?:{_COUNTRIES})|\bEU\b|CPTPP|수입|수출|교역|국제\s*(?:운송|배송)"
)
_SPECIES = {
    "beef": r"소고기|쇠고기|육우|생우|비육우|송아지|번식우",
    "pork": r"돼지(?:고기)?|돈육|양돈",
    "chicken": r"닭고기|육계|가금육|종란|병아리",
    "egg": r"계란|달걀|산란계",
}
_MARKET = re.compile(r"가격|물가|수급|공급|수요|생산|사육|출하|도축|수입|수출|교역|관세|검역|재고|운송")


def genuine_foreign_context(text: str) -> bool:
    """Require an actual foreign token, not a country inside Korean grammar."""
    return bool(_FOREIGN.search(text))


def source_statement_retracted(body: str, statement: str) -> bool:
    """Do not extract a claim whose next two source sentences retract it.

    Only explicit anaphoric correction/denial is considered. A correction of
    another independently named product or a distant report is not silently
    attached to this statement. This is a conservative publication guard, not
    an attempt to choose which side of a disputed report is true.
    """
    normalized = re.sub(r'\s+', ' ', body).strip()
    needle = re.sub(r'\s+', ' ', statement).strip()
    location = normalized.find(needle)
    if location < 0:
        return False
    following = normalized[location + len(needle):].lstrip()
    nearby = ' '.join(re.split(r'(?<=[.!?])\s+', following)[:2])[:900]
    korean_ref = r'(?:이|해당|앞선|당초|기존|위)\s*(?:발표|수치|내용|보도|보고|자료|가격|통계|전망|추정)|이를'
    korean_correction = r'허위|오보|정정|철회|부인|오류|잘못|무효|사실이?\s*아니'
    english_ref = r'\b(?:this|that|these|those|the earlier|the previous)\s+(?:report|statement|claim|prices?|figures?|numbers?|data|forecast)\b'
    english_correction = r'\b(?:correct(?:ed|ion)|retract(?:ed|ion)|withdrawn|invalid|not valid|false|incorrect|denied|erroneous)\b'
    return bool(
        re.search(korean_ref, nearby) and re.search(korean_correction, nearby)
        or re.search(english_ref, nearby, re.I) and re.search(english_correction, nearby, re.I)
    )


def affirmative_nominal_ending(text: str) -> str:
    """Nominalize known affirmative market predicates only.

    Unknown verbs, denials, forecasts and conditionals remain verbatim for
    source-based repair. In particular this never strips a final '다' alone.
    """
    noun = (r"집계|발표|확인|합의|적용|감축|증대|부진|재편|도달|형성|"
            r"반영|개선|악화|완료|성장|회복|확산|가속|지연|소진|재개")
    text = re.sub(
        rf"({noun})(?:한다|했다|하였다|했습니다|하였습니다|합니다|된다|됐다|되었다|"
        r"되었습니다|됐습니다|됩니다|하고\s*있다|되고\s*있다)[.!]?$", r"\1", text,
    )
    for before, after in (
        (r"늘었다", "증가"), (r"줄었다", "감소"),
        (r"올랐다", "상승"), (r"내렸다", "하락"),
        (r"늘고\s*있다", "증가세"), (r"줄고\s*있다", "감소세"),
        (r"수준이다", "수준"),
    ):
        text = re.sub(rf"{before}[.!]?$", after, text)
    text = re.sub(
        r"(상승세|하락세|증가세|감소세|강세|약세|회복세)(?:를|을)\s*"
        r"(?:보인다|보였다|보이고\s*있다)[.!]?$", r"\1", text,
    )
    return text


def source_korean_compactions(text: str) -> list[str]:
    """Remove grammatical/discourse bulk, never operands or risk qualifiers.

    These proposals still require the caller's complete source/measurement,
    modality and layout checks. No fixed country, statistic or policy is added.
    """
    compact = re.sub(r'^(정부는\s*)이와\s*별개로\s*', r'\1', text)
    compact = re.sub(r'(수급|공급)이\s*(?:다시\s*)?흔들릴\s*가능성', r'\1 불안 가능성', compact)
    compact = re.sub(r'가능성에\s*대비해', '가능성 대비', compact)
    compact = re.sub(r'(공급망|물량|재고)을\s*미리\s*확보하고\s*', r'\1 사전 확보·', compact)
    compact = re.sub(r'(확보|단축|개선|확대|축소|감축|증대)하는\s*방안(?:도|을)?', r'\1 방안', compact)
    compact = re.sub(r'(절차|규모|기간|물량|비용)(?:를|을)\s*(단축|확대|축소|감축)', r'\1 \2', compact)
    compact = re.sub(r'방안\s*검토', '검토', compact)
    variants = [text, compact]
    # These are grammatical substitutions within the same asserted source
    # sentence. In particular, do not delete temporal expressions, possible
    # slaughter volumes, the origin of an import ban or forecast qualifiers.
    compact = re.sub(r'(수출국|수입국)의\s+', r'\1 ', compact)
    compact = re.sub(rf'((?<![가-힣])(?:{_COUNTRIES}))의\s*(?=수입\s*수요)', r'\1 ', compact)
    compact = re.sub(rf'과\s+(?=(?:{_COUNTRIES})(?:의|\s))', '·', compact)
    compact = re.sub(r'(마릿수|물량|공급량)(?:와|과)\s+', r'\1·', compact)
    compact = re.sub(r'(?:이|가)\s*줄어든\s*데다\s+', ' 감소에 ', compact)
    compact = re.sub(r'(감소|증가|고환율|저환율)(?:와|과)\s+', r'\1·', compact)
    compact = re.sub(r'겹치면서\s+', '겹쳐 ', compact)
    compact = re.sub(r'가격이\s*높은\s*수준을\s*유지했다[.!]?$', '높은 가격 유지', compact)
    compact = re.sub(r'가축의\s*성장이\s*둔화한\s*데\s*따른\s*것이다[.!]?$',
                     '가축 성장 둔화 영향', compact)
    compact = re.sub(r'(?:올해|지난해)?\s*\d{1,2}월(?:에는|에)\s*',
                     lambda match: re.sub(r'(?:에는|에)\s*$', ' ', match[0]), compact)
    compact = re.sub(r'(수출|수입)에\s*합의했고,?\s*', r'\1 합의, ', compact)
    compact = re.sub(r'(협상)(?:도|을)?\s*마쳤다[.!]?$', r'\1 완료', compact)
    compact = re.sub(r'(협상)(?:도|을)?\s*마무리했다[.!]?$', r'\1 완료', compact)
    variants.append(compact)
    return list(dict.fromkeys(variants))


def korean_source_proposals(kind: str, body: str) -> list[str]:
    """Rank whole own-species source statements before any bounded rewriting.

    A whole affirmative first fact in an additive sentence can stand alone;
    contrast, conditional, denied or projected facts are never cropped at a
    conjunction. Redundant discourse markers are removable, facts are not.
    """
    species = "egg" if "egg" in kind else "chicken" if "chicken" in kind else "pork" if "pork" in kind else "beef"
    target = re.compile(_SPECIES[species])
    domestic = kind == "domestic" or kind.startswith("domestic_")
    proposals = []
    for index, original in enumerate(re.split(r"(?<=[.!?])\s+|\n+", body[:7000])):
        # A section heading is navigation/editorial framing, not a body
        # sentence. Its imported-meat keyword must not outrank the actual
        # foreign-market paragraph beneath it.
        if re.match(r'^\s*#{1,6}\s*\S', original):
            continue
        sentence = re.sub(r"^(?:[■□●ㆍ·\-]\s*)+", "", original.strip())
        sentence = re.sub(r"^(?:특히|또한|아울러|한편)\s+", "", sentence)
        if not 25 <= len(sentence) <= 500 or not target.search(sentence) or not _MARKET.search(sentence):
            continue
        if source_statement_retracted(body, original.strip()):
            continue
        if (not re.search(r"\d|증가|감소|상승|하락|확대|축소|보합|강세|약세|부족|과잉|중단|재개|금지|승인|검토|전망|예상", sentence)
                or re.search(r"않|못|아니|없|만약|경우|조건부", sentence)):
            continue  # uninformative prose/denials need explicit source-based interpretation
        if re.match(r"이는|이에|이것은|이들은|그는|이처럼", sentence):
            continue  # do not guess the subject of an anaphoric source sentence
        if domestic and not genuine_foreign_context(sentence):
            continue
        variants = [sentence]
        # Preserve an explicit trade-diversion cause and its observed flow,
        # without also carrying the later, independent domestic-price fact.
        # The anatomical names are shortened, not replaced by an inferred
        # product/origin. No ban origin is removed from the causal clause.
        trade_flow = re.match(
            rf'^(?P<cause>[^.!?]+?(?:돈육|돼지고기)[^.!?]*?(?:중단|감소|증가|확대|축소))\s*영향으로\s+'
            rf'(?P<origins>(?:{_COUNTRIES})(?:·(?:{_COUNTRIES}))*산)\s+'
            r'(?P<cuts>냉동\s+전지와\s*후지)가\s+'
            r'(?P<destination>국내)로\s*우회\s*유입되면서\s+[^.!?]+[.!]?$', sentence,
        ) if species == 'pork' else None
        if trade_flow:
            cuts = re.sub(r'전지와\s*후지', '전·후지', trade_flow['cuts'])
            effect = cuts + ' ' + trade_flow['destination'] + ' 우회 유입'
            variants.append(trade_flow['cause'] + ' 영향으로 ' + trade_flow['origins'] + ' ' + effect)
            # A shorter version can omit a non-exhaustive origin qualifier
            # from the effect. It never broadens the scope of the import ban,
            # whose complete original origin remains in the cause.
            variants.append(trade_flow['cause'] + '로 ' + effect)
        # An explicitly additive causal sentence can contain two independent
        # reasons for the same price outcome. Retain one stated reason and
        # its original subject/outcome, not a guessed cause assembled from
        # neighbouring paragraphs. Do not drop a temporal/risk qualifier.
        additive_cause = re.match(
            rf'^(?P<subject>{_SPECIES[species]})(?:는|은)\s+'
            r'(?P<omitted>[^.!?]+?)(?:줄어든|늘어난)\s*데다\s+'
            r'(?P<remainder>[^.!?]+(?:가격|수급)[^.!?]+)[.!]?$', sentence,
        )
        if additive_cause and not re.search(
            r'\d|올해|지난해|지난달|전년|전월|전주|가능성|검토|예정|전망|예상|'
            r'우려|불확실|않|못|아니|없|경우|조건|하지만|반면|으나',
            additive_cause['omitted'],
        ):
            variants.append(additive_cause['subject'] + '는 ' + additive_cause['remainder'])
        first = re.split(r"(?P<ending>했으며|했고|하였으며|하였고)[,，]?\s+", sentence, maxsplit=1)
        if len(first) == 3 and not re.search(
            r"않|못|아니|없|만약|경우|가능|검토|예정|전망|예상|우려|불확실|하지만|반면|으나", first[0]
        ):
            variants.append(first[0] + "했다")
        variants = [proposal for variant in variants for proposal in source_korean_compactions(variant)]
        for variant in variants:
            if domestic and not genuine_foreign_context(variant):
                continue
            if not target.search(variant):
                continue
            # Preserve sentence order on a tie. Causal and price/supply issues
            # outrank a bare dense table; numbers are not an editorial goal.
            score = (4 * bool(re.search(r"가격|수급|공급|수요", variant))
                     + 3 * bool(re.search(r"영향|때문|따라|가운데|대응|우려|전망", variant))
                     + 2 * bool(re.search(rf'(?<![가-힣])(?:{_COUNTRIES})|\bEU\b', variant))
                     + min(len(_MARKET.findall(variant)), 4))
            proposals.append((score, -index, variant))
    return list(dict.fromkeys(item[2] for item in sorted(proposals, reverse=True)))
