"""Literal fallback translations of verified market/industry passages.

These small source grammars are not saved weekly answers. The caller must
still check article date, country/species eligibility, source grounding and
document width. They make no model/network requests and never fill with a
historical report's facts.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re
import unicodedata

from .grounded_korean_brief import source_statement_retracted


_NUM = r'\d+(?:[.,]\d+)?'
_MONTHS_PT = dict(zip(('janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho',
                       'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro'), range(1, 13)))


def _text(body: str) -> str:
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', body)).strip()


def _positive(value: str, *, maximum: Decimal | None = None) -> str | None:
    try:
        number = Decimal(value.replace(',', '.'))
    except InvalidOperation:
        return None
    if not number.is_finite() or number <= 0 or maximum is not None and number >= maximum:
        return None
    return format(number.normalize(), 'f')


def _us_pork(body: str) -> tuple[str, str] | None:
    price = re.search(
        rf'지난주\s+돼지고기\s+컷아웃\s+가격은\s+전주\s+대비\s+'
        rf'(?P<rate>{_NUM})%\s*\([^)]*달러\)\s*소폭\s+하락한\s+'
        rf'{_NUM}달러로\s+20\d{{2}}년\s+\d{{1,2}}월\s+이래\s+최저가를\s+기록했다[.]', body)
    cause = re.search(
        r'대분할\s+belly\s*와\s+ham\s+부위에\s+더해\s+최근\s+몇\s+주간은\s+'
        r'picnic과\s+loin\s+부위의\s+가격\s+약세\s+역시\s+전체\s+컷아웃\s+'
        r'가격을\s+끌어내리는\s+요인으로\s+작용하고\s+있다[.]', body, re.I)
    if not price or not cause or not 0 <= cause.start() - price.end() <= 500:
        return None
    rate = _positive(price['rate'], maximum=Decimal(100))
    if not rate:
        return None
    if any(source_statement_retracted(body, m[0]) for m in (price, cause)):
        return None
    summary = f'미국 돼지고기 도매가격 지표, 최근 일부 부위 약세로 전주비 {rate}% 하락'
    return summary, price[0] + ' ' + cause[0]


def _australia_feedlot_guide(body: str) -> tuple[str, str] | None:
    lead = re.search(
        r'IN AN effort to optimise feedlot performance, a new best practice guide has been developed '
        r'for producers, outlining how to best prepare cattle for a feedlot[.]', body, re.I)
    author = re.search(
        r'The guide was developed by Meat & Livestock Australia and authored by [^.]{1,160}[.]', body, re.I)
    scope = re.search(
        r'The guide outlines the challenges feedlot cattle face and the strategies that help reduce '
        r'health and wellbeing risks in a feedlot to improve performance[.]', body, re.I)
    if not all((lead, author, scope)) or not lead.end() <= author.start() <= scope.start() <= lead.end() + 700:
        return None
    if any(source_statement_retracted(body, m[0]) for m in (lead, author, scope)):
        return None
    # A related industry fallback, not a cattle-price or production forecast.
    return ('호주 MLA, 비육장 소 입식 준비 및 건강·복지 위험 완화 관리지침 개발 완료',
            ' '.join(m[0] for m in (lead, author, scope)))


def _australia_china_quota_exports(body: str) -> tuple[str, str] | None:
    fact = re.search(
        rf'China has put a [\d,]+t quota on Australian beef, with a (?P<rate>{_NUM})pc tariff '
        r'when it is triggered [–-] which happened in [A-Z][a-z]+ this year[.] '
        r'Since then export volumes have declined (?:dramatically|drmatically)[.]', body)
    if not fact or source_statement_retracted(body, fact[0]):
        return None
    rate = _positive(fact['rate'], maximum=Decimal(100))
    if not rate:
        return None
    # Explicit post-trigger observation, not a forecast or an invented causal
    # estimate. Do not attach Korea's separate safeguard rate to China.
    return (f'중국의 호주산 쇠고기 수입에 대한 {rate}% 관세 발동 이후 대중국 수출량 감소', fact[0])


def _us_shell_egg_market(body: str) -> tuple[str, str] | None:
    # Use the independently stated qualitative national market, not nearby
    # price rows whose year-on-year prose can contradict their own numbers.
    country = re.search(
        r'The Agricultural Marketing Service, in its Daily National Shell Egg Index Report dated '
        r'[A-Z][a-z]+ \d{1,2}, 20\d{2}, reported mixed national free-on-board weighted average '
        r'prices for shell eggs\s*[.]', body)
    undertone = re.search(
        r'According to the USDA AMS MyMarketNews report, only caged Extra Large and Large grades '
        r'were well tested, while the overall market undertone was mostly steady[.]', body)
    supply = re.search(
        r'Offerings were moderate, supplies were generally moderate, and market activity was moderate to slow[.]', body)
    if not all((country, undertone, supply)) or not country.end() <= undertone.start() <= supply.start() <= country.end() + 750:
        return None
    if re.search(r'\bCalifornia\b', body[country.start():supply.end()]):
        return None
    if any(source_statement_retracted(body, m[0]) for m in (country, undertone, supply)):
        return None
    return ('미국 계란 시장은 대체로 보합, 공급은 대체로 보통·거래는 보통~한산한 수준',
            ' '.join(m[0] for m in (country, undertone, supply)))


def _brazil_chilled_carcass_quote(body: str) -> tuple[str, str] | None:
    geography = re.search(r'a carcaça de frango passou a ser negociada acima da carcaça suína '
                          r'no atacado de São Paulo[.]', body, re.I)
    quote = re.search(
        rf'Segundo dados do Centro de Estudos Avançados em Economia Aplicada \(Cepea\), '
        rf'o preço médio da carcaça de frango resfriado chegou a R\$\s*(?P<price>{_NUM})/kg '
        rf'em (?P<month>{"|".join(_MONTHS_PT)}), considerando os dados até (?P<day>\d{{1,2}}) '
        rf'de (?P<asof_month>{"|".join(_MONTHS_PT)}),', body, re.I)
    if not geography or not quote or not 0 <= quote.start() - geography.end() <= 100:
        return None
    month = quote['month'].lower()
    day = int(quote['day'])
    month_number = _MONTHS_PT[month]
    last_day = 29 if month_number == 2 else 30 if month_number in (4, 6, 9, 11) else 31
    if month != quote['asof_month'].lower() or not 1 <= day <= last_day:
        return None
    price = _positive(quote['price'])
    if not price or any(source_statement_retracted(body, m[0]) for m in (geography, quote)):
        return None
    # ONLY the chicken quote: never carry pork oversupply/cost/loss to poultry.
    return (f"브라질 상파울루 냉장 닭 도체가격, {month_number}월 {day}일까지 평균 kg당 {price}헤알 기록",
            geography[0] + ' ' + quote[0].rstrip(','))


def _brazil_monthly_price_support(body: str) -> tuple[str, str] | None:
    lead = re.search(
        rf'A avicultura de corte apresentou um mês de (?P<month>{"|".join(_MONTHS_PT)}) '
        r'de preços mais altos no atacado e mercados independentes do vivo[.]', body, re.I)
    sales = re.search(
        r'No atacado, os principais cortes também acumularam valorização, refletindo uma melhora '
        r'no fluxo das vendas[.] [“"]A entrada dos salários favoreceu o consumo e a reposição entre '
        r'atacado e varejo durante a primeira metade do mês[”"]', body, re.I)
    exports = re.search(
        r'[“"]As exportações permaneceram como importante fator de sustentação, mantendo parte '
        r'relevante da produção direcionada ao exterior[”"]', body, re.I)
    regional = re.search(
        r'A recuperação, entretanto, ocorreu de maneira desigual, com preços ainda fragilizados '
        r'no Nordeste e em parte da Região Sul[.]', body, re.I)
    country = re.search(
        r'O levantamento mensal realizado por Safras & Mercado nas principais praças de '
        r'comercialização do Brasil apontou que[^.]{0,220}[.]', body, re.I)
    matches = (lead, sales, exports, regional, country)
    if not all(matches) or not lead.end() <= sales.start() <= exports.start() <= regional.start() <= lead.end() + 1400:
        return None
    if any(source_statement_retracted(body, match[0]) for match in matches):
        return None
    # Mixed regional recovery is NOT a nationwide uniform increase. Preserve
    # the contrast rather than inventing a second figure or a future forecast.
    return (f"브라질 {_MONTHS_PT[lead['month'].lower()]}월 닭고기 가격, 내수·수출 지지 속 상승하나 지역별 회복 차이",
            ' '.join(match[0] for match in matches))


def native_recovery_fact(kind: str, body: str) -> tuple[str, str] | None:
    """Return an exact original-bound fallback or abstain with ``None``."""
    if not isinstance(body, str) or not body.strip():
        return None
    text = _text(body)
    if kind == 'brazil_chicken':
        return _brazil_monthly_price_support(text) or _brazil_chilled_carcass_quote(text)
    if kind == 'australia':
        return _australia_china_quota_exports(text) or _australia_feedlot_guide(text)
    reader = {'us_pork': _us_pork,
              'us_egg': _us_shell_egg_market}.get(kind)
    return reader(text) if reader else None
