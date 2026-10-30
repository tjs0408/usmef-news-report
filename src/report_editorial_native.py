"""Small, source-licensed market-context briefs, not a general paraphraser.

These frames prefer an explicit market explanation over a recurring table.
They deliberately recognize only a few complete source constructions. A
missing qualifier, changed direction, negation, or different regional scope
returns ``None`` so that the ordinary pipeline can try another method.

Numbers and months always come from the current source. Historical report
examples are not facts, and no model or network is used here. The caller must
still apply its normal factual, length, and document-layout validators.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re

from .grounded_korean_brief import source_statement_retracted


_MONTHS = {
    name.lower(): index
    for index, name in enumerate(
        ("January", "February", "March", "April", "May", "June", "July",
         "August", "September", "October", "November", "December"), 1
    )
}
_MONTH_RE = "(?:" + "|".join(_MONTHS) + ")"
_NUMBER = r"\d+(?:\.\d+)?"
_BROILER_STATISTIC = (
    r"(?P<statistic>The\s+USDA\s+says\s+placements\s+of\s+broiler-type\s+chicks\s+"
    rf"into\s+meat\s+production\s+of\s+(?P<amount>{_NUMBER})\s+million\s+head\s+"
    rf"were\s+up\s+(?P<weekly>{_NUMBER})\s+million\s+head\s+on\s+the\s+week\s+"
    rf"and\s+(?P<annual>{_NUMBER})%\s+on\s+the\s+year"
    r"(?:,\s+with\s+those\s+birds\s+heading\s+to\s+market\s+starting\s+in\s+"
    rf"(?:(?P<market_part>early|mid|late)[- ])?(?P<market_month>{_MONTH_RE}))?[.])"
)


def _normal_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _positive_percent(value: str) -> str | None:
    try:
        number = Decimal(value)
    except InvalidOperation:
        return None
    if not number.is_finite() or number <= 0 or number > 100:
        return None
    return format(number, "f").rstrip("0").rstrip(".") if "." in value else str(number)


def _us_beef_context(body: str) -> str | None:
    # Korean sentence boundaries, unlike decimal dots, terminate in '다.'.
    # Keeping the causal construction within one sentence prevents joining a
    # supply problem in one paragraph with an unrelated price in another.
    sentences = re.split(r"(?<=다)[.!?]\s*", _normal_space(body))
    supply = None
    for sentence in sentences:
        compact = re.sub(r"\s+", "", sentence)
        if re.search(
            r"암소도축감소로인한(?:leanbeef공급부족으로인해|"
            r"빠듯한국내산leanbeef공급과견조한수요가가격을지지하며,)"
            r"여전히(?:역대최고가|높은가격)수준을유지하고있다$",
            compact, re.I,
        ):
            supply = sentence
            break
    if supply is None:
        return None

    # This is a separate, independently licensed policy fact. In particular,
    # a proposed/rejected removal or an ordinary tariff must not become an
    # announced temporary removal of the out-of-quota duty.
    policy_month = None
    for sentence in sentences:
        policy = re.search(
            r"지난(?P<month>\d{1,2})월트럼프행정부는"
            r"분쇄육\(groundbeef\)용leanbeef공급을위해"
            r"[^.!?]{0,180}?쿼터외관세\(out-of-quotaduty\)를"
            r"한시적으로철폐하는행정명령을발표했다$",
            re.sub(r"\s+", "", sentence), re.I,
        )
        if policy and 1 <= int(policy["month"]) <= 12:
            policy_month = int(policy["month"])
            break
    result = "미국 암소 도축 감소로 저지방 쇠고기 공급이 부족해 높은 가격 수준 유지"
    if policy_month is not None:
        # Do not present an old announcement as this reporting week's event.
        # If its own sentence has no unambiguous month, omit the policy fact.
        result += f", 지난 {policy_month}월 분쇄육 원료 쿼터 외 관세 한시 철폐 발표"
    return result


def _us_egg_production_context(body: str) -> str | None:
    # All three changes must be in the same observed monthly USDA sentence.
    # 'with' is rendered as '함께', not upgraded into a claimed causal link.
    # The exact positive constructions also exclude forecasts and negation.
    match = re.search(
        rf"\b(?:The\s+)?USDA\s+says\s+{_NUMBER}\s+(?:billion|million)\s+eggs\s+"
        rf"were\s+produced\s+in\s+(?P<month>{_MONTH_RE}),\s*"
        rf"up\s+(?P<production>{_NUMBER})%\s+on\s+the\s+year,\s*"
        rf"with\s+a[n]?\s+(?P<layers>{_NUMBER})%\s+increase\s+in\s+the\s+average\s+"
        rf"number\s+of\s+layers\s+to\s+{_NUMBER}\s+million\s+head\s+and\s+"
        rf"(?P<rate>{_NUMBER})%\s+rise\s+in\s+the\s+rate\s+of\s+production\s+"
        rf"per\s+100\s+layers(?=\s*[.!?])",
        _normal_space(body), re.I,
    )
    if match is None:
        return None
    production = _positive_percent(match["production"])
    if production is None or any(
        _positive_percent(match[name]) is None for name in ("layers", "rate")
    ):
        return None
    month = _MONTHS[match["month"].lower()]
    return (
        f"미국 {month}월 계란 생산량, 산란계 수·산란율 증가와 함께 "
        f"전년 동월비 {production}% 증가"
    )


def _broiler_context_supported(text: str, match: re.Match[str]) -> bool:
    """Reject corrections and uncertainty attached to the selected block."""
    lead, statistic = match['lead'], match['statistic']
    if any(source_statement_retracted(text, statement) for statement in (lead, statistic)):
        return False
    # An anaphoric uncertainty statement immediately after this figure is not
    # permission to publish its production signal as an established fact.
    following = ' '.join(re.split(r'(?<=[.!?])\s+', text[match.end():].lstrip())[:2])
    if re.search(
        r"\b(?:this|that|these|those)(?:\s+(?:report|forecast|statement|claim|figures?|numbers?|data))?\s+"
        r"(?:is|are|was|were|has|have|remain|remains)\b[^.!?]{0,100}"
        r"\b(?:unconfirmed|disputed|denied|false|incorrect|retracted|withdrawn|not\s+(?:been\s+)?confirmed)\b",
        following, re.I,
    ):
        return False
    return True


def _broiler_placements_values(match: re.Match[str]) -> tuple[str, str] | None:
    """Translate this placement count exactly, never a neighbouring egg total."""
    annual = _positive_percent(match['annual'])
    amount = Decimal(match['amount']) * 1_000_000
    weekly = Decimal(match['weekly']) * 1_000_000
    if (annual is None or amount <= 0 or not 0 < weekly < amount
            or amount != amount.to_integral_value()):
        return None
    remaining = int(amount)
    parts = []
    for unit, label in ((100_000_000, '억'), (10_000, '만')):
        count, remaining = divmod(remaining, unit)
        if count:
            parts.append(f'{count}{label}')
    if remaining:
        parts.append(str(remaining))
    return ' '.join(parts), annual


def _us_broiler_demand_placements(body: str) -> tuple[str, str] | None:
    """Bind a national production signal to its adjacent observed placements.

    Higher sets/placements point towards future output; they do not establish
    an already observed production increase. The optional intervening sentence
    is the same US-broiler continuation, never another country or commodity.
    """
    text = _normal_space(body)
    match = re.search(
        r"(?:^|(?<=[.!?])\s+)"
        r"(?P<lead>U[.]S[.]\s+broiler\s+sets\s+and\s+placements\s+were\s+up\s+"
        r"on\s+both\s+the\s+week\s+and\s+the\s+year,\s+continuing\s+to\s+point\s+"
        r"towards\s+higher\s+production\s+as\s+poultry\s+producers\s+try\s+to\s+meet\s+demand[.])\s+"
        r"(?:U[.]S[.]\s+broiler\s+numbers\s+continue\s+to\s+rise[.]\s+)?"
        + _BROILER_STATISTIC, text, re.I,
    )
    if match is None or not _broiler_context_supported(text, match):
        return None
    values = _broiler_placements_values(match)
    if values is None:
        return None
    heads, annual = values
    summary = (
        "미국 육계 입란·입식 증가가 수요 충족을 위한 생산 확대 시사, "
        f"병아리 입식수 {heads}마리로 전년비 {annual}% 증가"
    )
    return summary, text[match.start('lead'):match.end('statistic')]


def _us_broiler_placements_marketing(body: str) -> tuple[str, str] | None:
    """Keep observed US chick placements and their explicit future market date.

    This body-only frame does not borrow demand claims from a publisher's
    separate summary. The US anchor must directly precede its own statistic,
    whose same birds must have a stated early/mid/late-month marketing date.
    """
    text = _normal_space(body)
    match = re.search(
        r"(?:^|(?<=[.!?])\s+)"
        r"(?P<lead>U[.]S[.]\s+broiler\s+numbers\s+continue\s+to\s+rise[.])\s+"
        + _BROILER_STATISTIC, text, re.I,
    )
    if (match is None or not match['market_part'] or not match['market_month']
            or not _broiler_context_supported(text, match)):
        return None
    values = _broiler_placements_values(match)
    if values is None:
        return None
    heads, annual = values
    month = _MONTHS[match['market_month'].lower()]
    part = {'early': '초', 'mid': '중순', 'late': '말'}[match['market_part'].lower()]
    summary = (
        f"미국 육계 병아리 입식수는 {heads}마리로 전년비 {annual}% 증가, "
        f"해당 병아리는 {month}월 {part}부터 출하 예정"
    )
    return summary, text[match.start('lead'):match.end('statistic')]


def _australia_winter_exports(body: str) -> str | None:
    # The all-markets sentence must immediately follow its Australian
    # month/country anchor. A US-destination figure or a tariff headline alone
    # is insufficient evidence for a national production-led export decline.
    match = re.search(
        rf"\bAustralia['’]s\s+(?P<month>{_MONTH_RE})\s+beef\s+export\s+statistics"
        r"[^.!?]{0,100}[.]\s*"
        r"Total\s+exports\s+for\s+the\s+month\s+to\s+all\s+markets\s+reached\s+"
        r"\d[\d,]*\s+tonnes,\s+a\s+sizeable\s+\d[\d,]*t\s+or\s+"
        rf"(?P<decline>{_NUMBER})(?:pc|%)\s+decline\s+on\s+the\s+previous\s+month\s*"
        r"[–—-]\s*but\s+that\s+can\s+largely\s+be\s+attributed\s+to\s+lower\s+"
        r"mid[- ]winter\s+production,\s+rather\s+than\s+any\s+decline\s+in\s+overall\s+demand"
        r"(?=\s*[.!?])",
        _normal_space(body), re.I,
    )
    if match is None:
        return None
    decline = _positive_percent(match["decline"])
    if decline is None:
        return None
    month = _MONTHS[match["month"].lower()]
    return (
        f"호주 {month}월 전체 쇠고기 수출량은 겨울철 생산 감소 영향으로 "
        f"전월비 {decline}% 감소"
    )


def _domestic_us_cattle(body: str) -> tuple[str, str] | None:
    match = re.search(
        r'미국은\s+가뭄과\s+사료비\s+부담으로\s+소\s+사육\s+규모가\s+'
        r'(?P<years>\d{1,3})년\s+만에\s+최소\s+수준으로\s+줄었다[.]',
        _normal_space(body))
    if not match:
        return None
    return (f"미국은 가뭄·사료비 부담으로 소 사육 규모가 {int(match['years'])}년 만에 최소 수준으로 감소", match[0])


def _brazil_conditional_outlook(body: str) -> tuple[str, str] | None:
    # Two adjacent source sentences; the EU-access premise belongs to these
    # Brazilian forecasts, not the following Chinese growth rates.
    match = re.search(
        rf'\bPara\s+(?P<year>20\d{{2}}),\s+as\s+primeiras\s+projeções\s+'
        rf'do\s+Departamento\s+de\s+Agricultura\s+dos\s+Estados\s+Unidos\s+\(USDA\),\s+'
        rf'apresentadas\s+no\s+relatório\s+do\s+Itaú\s+BBA,\s+indicam\s+crescimento\s+'
        rf'de\s+\d+(?:[,.]\d+)?%\s+na\s+produção\s+brasileira\s+de\s+carne\s+de\s+frango\s+'
        rf'e\s+de\s+(?P<exports>\d+(?:[,.]\d+)?)%\s+nas\s+exportações[.]\s+'
        r'Esse\s+cenário\s+considera\s+a\s+manutenção\s+das\s+restrições\s+de\s+acesso\s+'
        r'ao\s+mercado\s+europeu\s+durante\s+todo\s+o\s+próximo\s+ano[.]',
        _normal_space(body), re.I)
    if not match:
        return None
    exports = _positive_percent(match['exports'].replace(',', '.'))
    if exports is None:
        return None
    return (f"유럽 시장 접근 제한 연중 유지 시, {match['year']}년 브라질 닭고기 수출 {exports}% 증가 전망", match[0])


def _domestic_australian_tariff(body: str) -> tuple[str, str] | None:
    match = re.search(
        r'호주산\s+(?:소고기|쇠고기)에\s+지난\s+(?P<month>1[0-2]|[1-9])월\s+하순부터\s+'
        r'(?P<high>\d+(?:\.\d+)?)%의\s+관세가\s+붙고\s+있습니다[.]\s+'
        r'한·호주\s+자유무역협정\(FTA\)에\s+따라\s+올해\s+적용되는\s+관세는\s+'
        r'(?P<low>\d+(?:\.\d+)?)%이지만,\s+낮은\s+관세로\s+들여올\s+수\s+있는\s+'
        r'물량이\s+(?P<quota_month>1[0-2]|[1-9])월에\s+일찌감치\s+바닥났기\s+때문입니다[.]',
        _normal_space(body))
    if not match or match['month'] != match['quota_month'] or Decimal(match['high']) <= Decimal(match['low']):
        return None
    return (f"호주산 소고기 저율관세 물량이 지난 {match['month']}월 소진되면서 수입관세 {match['low']}%에서 {match['high']}%로 인상", match[0])


def editorial_native_brief(kind: str, body: str) -> str | None:
    """Return a strict source-bound editorial frame, or abstain with ``None``."""
    if not isinstance(body, str) or not body.strip():
        return None
    if re.search(r'\b(?:this|that)\s+(?:report|forecast|statement).{0,90}\b(?:incorrect|retracted|withdrawn|false|denied)\b', body, re.I):
        return None
    if kind == "us":
        return _us_beef_context(body)
    if kind == "us_egg":
        return _us_egg_production_context(body)
    if kind == "us_chicken":
        fact = _us_broiler_demand_placements(body) or _us_broiler_placements_marketing(body)
        return fact[0] if fact else None
    if kind == "australia":
        return _australia_winter_exports(body)
    if kind == 'domestic':
        fact = _domestic_us_cattle(body) or _domestic_australian_tariff(body)
        return fact[0] if fact else None
    if kind == 'brazil_chicken':
        fact = _brazil_conditional_outlook(body)
        return fact[0] if fact else None
    return None


def editorial_native_source_excerpt(body: str, summary: str) -> str | None:
    """Exact parser-selected source spans, never an eight/month keyword hit."""
    text = _normal_space(body)
    for kind, reader in (('domestic', _domestic_us_cattle), ('domestic', _domestic_australian_tariff),
                         ('brazil_chicken', _brazil_conditional_outlook),
                         ('us_chicken', _us_broiler_demand_placements),
                         ('us_chicken', _us_broiler_placements_marketing)):
        fact = reader(text)
        if fact and summary == fact[0] and editorial_native_brief(kind, body) == summary:
            return fact[1]
    if editorial_native_brief('us', body) == summary:
        sentences = [s.strip() + '.' for s in re.split(r'(?<=다)[.!?]\s*', text) if s.strip()]
        selected = [s for s in sentences if re.search(r'암소\s*도축\s*감소', s) and re.search(r'lean\s*beef', s, re.I)
                    and re.search(r'가격|최고가', s)]
        if '관세' in summary:
            selected.extend(s for s in sentences if '행정명령' in s and '분쇄육' in s and '발표했다' in s)
        return ' '.join(selected) or None
    if editorial_native_brief('us_egg', body) == summary:
        match = re.search(r'\b(?:The\s+)?USDA\s+says\s+\d.*?per\s+100\s+layers[.]', text, re.I)
        return match[0] if match else None
    if editorial_native_brief('australia', body) == summary:
        match = re.search(r"\bAustralia['’]s\s+\w+\s+beef\s+export\s+statistics.*?overall\s+demand[.]", text, re.I)
        return match[0] if match else None
    return None
