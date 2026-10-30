"""Source-bound Korean trade briefs for recurring domestic reporting clauses."""

from decimal import Decimal, InvalidOperation
import re
import unicodedata

from .grounded_korean_brief import source_statement_retracted


_NUMBER = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
_AMOUNT = rf"{_NUMBER}(?:\s*[억만천](?:\s*{_NUMBER})?){{0,2}}"
_ORIGINS = r"브라질|미국|태국|호주|일본|중국|캐나다|덴마크|네덜란드|베트남|뉴질랜드"
_DESTINATION = r"싱가포르|몽골|홍콩|일본|미국|대만|베트남|호주|중국|필리핀|말레이시아|태국"
_DENIAL = r"허위|부인|반박|정정|오기|오류|잘못|사실이\s*아니|아니라|아니었|않|없었|없다|추정|가정"


def _sentences(body: str) -> list[str]:
    text = unicodedata.normalize("NFKC", str(body))
    text = re.sub(r"\s+", " ", text).strip()
    return [item.strip() for item in re.split(r"(?<=[.!?])\s+", text) if item.strip()]


def _compact_amount(value: str) -> str:
    return re.sub(r"\s+", "", value)


def _positive(value: str) -> bool:
    """Validate explicit unsigned source amounts without calculating a price."""
    try:
        parts = re.findall(rf"({_NUMBER})\s*([억만천]?)", value)
        return bool(parts) and any(Decimal(number.replace(",", "")) > 0 for number, _ in parts)
    except InvalidOperation:
        return False


def _egg_import_criticism(body: str) -> tuple[str, str] | None:
    clause = re.compile(
        r"(?:최근\s*)?(?:국정감사|국감)에서(?:는)?\s*"
        rf"(?P<origin>{_ORIGINS})산\s*(?:계란|달걀)\s*"
        rf"(?P<count_approx>약\s*)?(?P<count>{_AMOUNT})\s*개를\s*"
        r"(?:들여오는\s*데|수입하는\s*데)\s*"
        rf"(?P<total_approx>약\s*)?(?P<total>{_AMOUNT})\s*원이\s*"
        r"(?:투입돼|투입되어|소요돼|소요되어)\s*"
        rf"한\s*판\s*\(\s*(?P<package>{_NUMBER})\s*개\s*\)당\s*"
        r"수입\s*단가(?:가|는)\s*"
        rf"(?P<price_approx>약\s*)?(?P<price>{_AMOUNT})\s*원에\s*"
        r"달했다는\s*지적이\s*(?:나왔다|제기됐다|제기되었다)",
    )
    sentences = _sentences(body)
    for index, sentence in enumerate(sentences):
        match = clause.search(sentence)
        if not match or re.search(_DENIAL, sentence):
            continue
        # A following correction of these figures defeats the positive quote;
        # an unrelated criticism elsewhere does not negate the whole article.
        following = sentences[index + 1] if index + 1 < len(sentences) else ""
        if (re.search(r"해당\s*(?:수치|지적|보도)|이\s*(?:수치|지적|보도)", following)
                and re.search(_DENIAL, following)):
            continue
        if not all(_positive(match[name]) for name in ("count", "total", "package", "price")):
            continue
        display = lambda name: ("약 " if match[name + "_approx"] else "") + _compact_amount(match[name])
        summary = (f"국감서 {match['origin']}산 계란 {display('count')}개 수입에 "
                   f"{display('total')}원 투입·{_compact_amount(match['package'])}개당 "
                   f"{display('price')}원 지적")
        if 40 <= len(summary) <= 80:
            return summary, sentence
    return None


def _pork_export_diversification(body: str) -> tuple[str, str] | None:
    clause = re.compile(
        r"(?P<seller>[가-힣]{2,20}(?:농협|조합|협회|공사|식품))은\s*"
        rf"(?P<destinations>(?:{_DESTINATION})(?:\s*(?:와|과|및|·|,)\s*(?:{_DESTINATION})){{1,3}})\s*"
        r"수출을\s*통해\s*"
        r"(?P<origin>[가-힣]{2,10})산\s*(?:돼지고기|돈육)의\s*"
        r"우수성을\s*해외시장에\s*알리고\s*"
        r"수출\s*시장(?:에)?\s*다변화에\s*힘쓰고\s*있다",
    )
    for sentence in _sentences(body):
        match = clause.search(sentence)
        if not match or re.search(_DENIAL + r"|예정|계획|가능성", sentence):
            continue
        destinations = re.findall(_DESTINATION, match['destinations'])
        if len(destinations) != len(set(destinations)):
            continue
        summary = (f"{match['seller']}, {'·'.join(destinations)}에 "
                   f"{match['origin']}산 돼지고기 수출하며 수출시장 다변화 추진")
        if 40 <= len(summary) <= 80:
            return summary, sentence
    return None


def _beef_supply_currency_prices(body: str) -> tuple[str, str] | None:
    """Keep an adjacent import-price cause and its explicit CPI comparison.

    The item need not declare an annual/monthly comparison. Consequently the
    brief never supplies one: it reports only the named month's stated rise.
    Both the cattle-supply and currency causes must be present, and the import
    rise must actually exceed the domestic rise as the source asserts.
    """
    cause = re.compile(
        r"(?P<country>미국|호주|브라질|캐나다)\s*사육\s*감소와\s*환율이\s*"
        r"겹치며\s*수입\s*(?:쇠고기|소고기)(?:도|가|는)\s*올랐다\s*[.]?$",
    )
    prices = re.compile(
        rf"^(?P<month>\d{{1,2}})월\s*수입\s*(?:쇠고기|소고기)\s*소비자물가는\s*"
        rf"(?P<import_rate>{_NUMBER})%\s*올라\s*국산\s*"
        rf"\(\s*(?P<domestic_rate>{_NUMBER})%\s*\)보다\s*(?:오히려\s*)?가파르다\s*[.]?$",
    )
    sentences = _sentences(body)
    for index, first in enumerate(sentences[:-1]):
        source_cause = cause.search(first)
        second = sentences[index + 1]
        price = prices.fullmatch(second)
        if not source_cause or not price or re.search(_DENIAL, first + " " + second):
            continue
        if not 1 <= int(price['month']) <= 12:
            continue
        if Decimal(price['import_rate'].replace(",", "")) <= Decimal(price['domestic_rate'].replace(",", "")):
            continue
        following = sentences[index + 2] if index + 2 < len(sentences) else ""
        if (re.search(r"해당\s*(?:수치|지적|보도)|이\s*(?:수치|지적|보도)", following)
                and re.search(_DENIAL, following)):
            continue
        summary = (f"{source_cause['country']} 사육 감소·환율로 수입 쇠고기값 상승, "
                   f"{int(price['month'])}월 소비자물가 {price['import_rate']}% 올라 "
                   f"국산 {price['domestic_rate']}% 상회")
        if 40 <= len(summary) <= 80:
            return summary, first + " " + second
    return None


def _egg_import_schedule(body: str) -> tuple[str, str] | None:
    """Separate completed year-to-date imports from a future weekly plan.

    Both quantities must be explicit in the same original sentence. Never
    calculate a total from the weekly rate or infer the eggs' origin country.
    """
    pattern = re.compile(
        rf"올해\s*(?:들어\s*)?(?:지금까지\s*)?수입된\s*신선란은\s*"
        rf"(?P<actual_approx>약\s*)?(?P<actual>{_AMOUNT})\s*개이며,?\s*"
        rf"(?P<horizon>추석\s*전까지|연말까지)(?:는)?\s*매주\s*"
        rf"(?P<weekly_approx>약\s*)?(?P<weekly>{_AMOUNT})\s*개(?P<weekly_suffix>가량|정도)?\s*"
        r"(?:을\s*)?추가로\s*들여올\s*계획(?:이다)?"
    )
    for sentence in _sentences(body):
        match = pattern.search(sentence)
        if not match or re.search(_DENIAL, sentence) or source_statement_retracted(body, sentence):
            continue
        if not all(_positive(match[name]) for name in ('actual', 'weekly')):
            continue
        actual = ('약 ' if match['actual_approx'] else '') + _compact_amount(match['actual'])
        weekly = ('약 ' if match['weekly_approx'] or match['weekly_suffix'] else '') + _compact_amount(match['weekly'])
        horizon = '추석 전' if match['horizon'].startswith('추석') else '연말까지'
        summary = (f"올해 신선 계란 {actual}개 수입, {horizon} 매주 "
                   f"{weekly}개 추가 수입 계획")
        return summary, sentence
    return None


def native_korean_trade_brief(kind: str, body: str) -> tuple[str, str] | None:
    """Extract explicit trade facts, preserving allegation and activity scope.

    No import unit cost is computed from totals. A parliamentary criticism is
    still a criticism, not an audited purchase price. Export diversification
    requires the same sentence's seller, destinations, pork origin and action.
    """
    if kind == "domestic_egg":
        return _egg_import_criticism(body) or _egg_import_schedule(body)
    if kind == "domestic_pork":
        return _pork_export_diversification(body)
    if kind == "domestic":
        return _beef_supply_currency_prices(body)
    return None
