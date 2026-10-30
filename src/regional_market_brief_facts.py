"""Small translations of explicit regional market-report statements.

These are source grammars, not saved weekly answers. Unsupported clauses,
negations, country substitutions and contradictory numbers fail closed.
"""
from decimal import Decimal
import re
import unicodedata


_NUM = r'\d+(?:[.,]\d+)?'
_MONTHS = dict(zip(('janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho',
                   'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro'), range(1, 13)))
_EU_COUNTRIES = {'Italy': '이탈리아', 'Germany': '독일', 'France': '프랑스', 'Spain': '스페인',
                 'Denmark': '덴마크', 'Poland': '폴란드', 'Netherlands': '네덜란드'}
_OTHER_US_HEADLINE = re.compile(
    r'\b(?:Japan|China|Brazil|Canada|Canadian|Ontario|Quebec|Europe|Germany|Spain|'
    r'Mexico|Denmark|France|UK|Ukraine)\b', re.I)


def us_pork_primary_market(body: str, title: str = '') -> bool:
    """A Canadian/Japanese story is not US news because it quotes a US price."""
    if _OTHER_US_HEADLINE.search(title) and not re.search(r'\b(?:U\.S\.?|US|United States|American)\b', title):
        return False
    if (re.search(r'\bNational negotiated cash hog prices\b', body, re.I)
            and re.search(r'\bUSDA Agricultural Marketing Service\b', body, re.I)
            and re.search(r'\bCME Lean Hog Index\b', body, re.I)):
        return True
    return bool(re.search(r'\bU\.S\.(?=\s|$)|\b(?:US|United States|American)\b', title + ' ' + body[:1200], re.I))


def _us_pork(body: str) -> tuple[str, str] | None:
    if not us_pork_primary_market(body):
        return None
    cutout = re.search(
        rf'After several weeks of declining wholesale pork values, the cutout closed Friday '
        rf'at \$(?P<price>{_NUM})/cwt, virtually unchanged from \${_NUM} the previous week\.', body, re.I)
    cash = re.search(rf'National negotiated cash hog prices fell to \${_NUM}/cwt(?:[^.]|\.(?=\d))*\.(?=\s|$)', body, re.I)
    if not cutout or not cash:
        return None
    # Reject a following correction rather than selecting the convenient lead.
    if re.search(r'not (?:virtually unchanged|fall|fell|improved)|correction|misreported', body, re.I):
        return None
    summary = f"미국 돼지고기 도매 지표 {cutout['price']}달러로 전주와 사실상 보합, 생돈가격 하락"
    attribution = re.search(r'Sources:\s*USDA Agricultural Marketing Service[^.]*\.', body, re.I)
    return summary, ' '.join((cutout[0], cash[0], attribution[0] if attribution else ''))


def _eu_pork(body: str) -> tuple[str, str] | None:
    amount = rf'(?:approximately |about )(?P<count>{_NUM}|one|two|three|four|five) (?P<scale>million|thousand)'
    match = re.search(
        rf'In recent years, due to various factors, we have lost {amount} pigs produced in '
        rf'(?P<country>{"|".join(_EU_COUNTRIES)}), and our level of self-sufficiency has further declined\.', body, re.I)
    if not match or re.search(r'(?:not lost|not declined|correction|misreported)', body, re.I):
        return None
    words = dict(one=1, two=2, three=3, four=4, five=5)
    value = Decimal(str(words.get(match['count'].lower(), match['count'])).replace(',', '.'))
    total = value * (1000000 if match['scale'].lower() == 'million' else 1000)
    if total <= 0 or total != int(total):
        return None
    total = int(total)
    quantity = (f'{total // 10000}만' + (str(total % 10000) if total % 10000 else '')
                if total >= 10000 else str(total))
    country = next(label for name, label in _EU_COUNTRIES.items() if name.lower() == match['country'].lower())
    summary = f'{country} 최근 수년간 돼지 생산 약 {quantity}마리 감소, 자급률도 추가 하락'
    if len(summary) < 40:
        summary = summary.replace('자급률', '돼지 자급률')
    return summary, match[0]


def _brazil_chicken(body: str) -> tuple[str, str] | None:
    regional_recovery = _brazil_regional_price_recovery(body)
    if regional_recovery:
        return regional_recovery
    lead = re.search(
        rf'A recuperação dos preços da carne de frango em (?P<month>{"|".join(_MONTHS)}) '
        r'melhorou as margens da agroindústria brasileira[^.]*\.', body, re.I)
    if not lead:
        return None
    block = body[lead.start():lead.start() + 1100]
    prices = re.search(rf'o preço médio mensal da ave avançou (?P<rise>{_NUM})%, '
                       rf'superando a alta de (?P<cost>{_NUM})% no custo de produção da avicultura\.', block, re.I)
    spread = re.search(rf'Com isso, o spread do frango abatido passou de (?P<old>{_NUM})% '
                       rf'para (?P<new>{_NUM})%\.', block, re.I)
    if not prices or not spread or re.search(r'\b(?:não|negou|retificou|corrigiu|estimado|poderia)\b', block[:spread.end()], re.I):
        return None
    values = {name: Decimal(value.replace(',', '.')) for name, value in {
        **prices.groupdict(), **spread.groupdict()}.items()}
    if not (values['rise'] > values['cost'] >= 0 and 0 <= values['old'] < values['new'] <= 100):
        return None
    display = lambda name: str(values[name]).rstrip('0').rstrip('.') if '.' in str(values[name]) else str(values[name])
    summary = (f"브라질 {_MONTHS[lead['month'].lower()]}월 닭고기 가격 {display('rise')}% 상승, "
               f"도축업계 가격·원가 격차율 {display('old')}%→{display('new')}% 확대")
    return summary, ' '.join((lead[0], prices[0], spread[0]))


def _brazil_regional_price_recovery(body: str) -> tuple[str, str] | None:
    """A surveyed-market recovery is not a national monthly price index.

    Keep both the scope ('most surveyed markets') and the reported domestic
    demand/export explanation. Later wage-payment expectations and individual
    São Paulo quotations cannot become the cause or amount of this recovery.
    """
    lead = re.search(
        rf'O preço médio da carne de frango apresentou recuperação em '
        rf'(?P<month>{"|".join(_MONTHS)}) na maior parte das praças acompanhadas '
        r'pelo Centro de Estudos Avançados em Economia Aplicada \(Cepea\)\.', body, re.I)
    if not lead:
        return None
    cause = re.match(
        r'\s*O movimento foi sustentado principalmente pelo aumento da demanda no mercado interno, '
        r'especialmente no início do mês, e pelo bom ritmo das exportações\.', body[lead.end():], re.I)
    region = re.search(
        r'Os indicadores do Cepea consideram os preços da carne negociada no atacado, '
        r'com média das regiões da Grande São Paulo, São José do Rio Preto e Descalvado\.', body, re.I)
    if not cause or not region or re.search(r'\b(?:não|negou|retificou|corrigiu|falso|incorreto)\b', body, re.I):
        return None
    summary = (f"브라질 조사 지역 대부분서 내수 증가·양호한 수출 흐름에 "
               f"{_MONTHS[lead['month'].lower()]}월 닭고기 가격 회복")
    return summary, ' '.join((lead[0], cause[0].strip(), region[0]))


def native_regional_market_brief(kind: str, body: str) -> tuple[str, str] | None:
    text = re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', str(body))).strip()
    parser = {'us_pork': _us_pork, 'eu_pork': _eu_pork, 'brazil_chicken': _brazil_chicken}.get(kind)
    fact = parser(text) if parser else None
    return fact if fact and 40 <= len(fact[0]) <= 95 else None
