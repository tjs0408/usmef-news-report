"""Source-bound completed trade statistics for Korean market reporting.

These grammars identify a commodity's own original quantities, destination,
period and observed activity. They do not use headlines, selected dates,
publisher names or fixed weekly answers to supply a missing fact. Returned
proposals still require the caller's ordinary factual and layout checks.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re
import unicodedata

from .grounded_korean_brief import source_statement_retracted


_NUMBER = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
_AMOUNT = rf"{_NUMBER}(?:\s*[억만천](?:\s*{_NUMBER})?){{0,2}}"
_COUNTRY = (
    r"싱가포르|몽골|홍콩|일본|미국|대만|베트남|호주|중국|필리핀|말레이시아|태국|"
    r"캐나다|독일|프랑스|스페인|인도네시아|뉴질랜드|영국|브라질"
)
_REGION = rf"유럽연합\s*\(\s*EU\s*\)|EU|유럽|{_COUNTRY}"
_UNASSERTED = (
    r"허위|부인|반박|정정|오기|오류|잘못|사실이?\s*아니|아니라|아니었|않|못했|"
    r"없었|없다|가정|예정|계획|목표|전망|예상|가능성|조건|시나리오"
)


def _source_sentences(body: str) -> tuple[str, list[str]]:
    text = unicodedata.normalize("NFKC", str(body))
    # Preserve line boundaries until sentence splitting so subheadings cannot
    # become the grammatical subject of the following original sentence.
    text = re.sub(r"[^\S\n]+", " ", text).strip()
    sentences = [item.strip() for item in re.split(r"(?<=[.!?])\s+|\n+", text) if item.strip()]
    return text, sentences


def _positive(value: str) -> bool:
    try:
        parts = re.findall(rf"({_NUMBER})\s*([억만천]?)", value)
        return bool(parts) and any(Decimal(number.replace(",", "")) > 0 for number, _ in parts)
    except InvalidOperation:
        return False


def _single_pork_export_record(body: str) -> tuple[str, str] | None:
    record = re.compile(
        r"(?P<seller>[가-힣A-Za-z0-9·]{2,24}(?:농협|조합|협회|공사|식품|푸드|유통))"
        r"(?:\([^()]{1,50}\))?(?:이|가)\s*"
        rf"(?P<destination>{_COUNTRY})에\s*(?P<product>돼지고기|돈육)\s*"
        rf"(?P<approx>약\s*)?(?P<amount>{_AMOUNT})\s*(?:t|톤)을\s*"
        r"한꺼번에\s*수출하며\s*단일\s*수출\s*물량으로는\s*"
        r"역대\s*최대\s*실적을\s*기록했다[.]?$"
    )
    source, sentences = _source_sentences(body)
    for sentence in sentences:
        fact = record.fullmatch(sentence)
        if (not fact or re.search(_UNASSERTED, sentence)
                or not _positive(fact['amount'])
                or source_statement_retracted(source, sentence)):
            continue
        amount = re.sub(r"\s+", "", fact['amount'])
        quantity = ("약 " if fact['approx'] else "") + amount + "톤"
        summary = (f"{fact['seller']}, {fact['destination']}에 {fact['product']} {quantity} 수출하며 "
                   "단일 수출 물량 역대 최대 기록")
        return summary, sentence
    return None


def _poultry_export_value(body: str) -> tuple[str, str] | None:
    """Bind poultry's own value/rate to an adjacent stated monthly period.

    A comparison of other destinations can intervene, but a different dated
    report, product paragraph, unasserted plan or fresh geographic topic
    cannot inherit the earlier period. K-food's value/rate are never reused.
    """
    value = re.compile(
        r"^(?:특히\s*)?(?:\d{4}년\s*검역\s*협상이\s*타결된\s*)?"
        r"(?P<product>열처리\s*(?:가금육|닭고기))\s*수출액은\s*"
        rf"(?P<amount>{_AMOUNT})\s*달러로\s*전년\s*동기\s*(?:대비|비)\s*"
        rf"(?P<rate>{_NUMBER})%\s*(?:늘었다|증가했다|증가하였다)[.]?$"
    )
    period = re.compile(
        rf"^(?P<year>올해|지난해|20\d{{2}}년)\s*"
        r"(?P<first>\d{1,2})(?:월)?\s*[~∼~-]\s*(?P<last>\d{1,2})월\s*"
        rf"(?P<region>{_REGION})\s*(?:권역\s*)?K-?푸드\s*수출액은\s*"
        rf"{_AMOUNT}\s*달러로\s*전년\s*동기\s*(?:대비|비)\s*"
        rf"{_NUMBER}%\s*(?:증가했다|늘었다|증가하였다)[.]?$"
    )
    comparison = re.compile(
        rf"^같은\s*기간\s*(?:{_COUNTRY})(?:과|와)\s*(?:{_COUNTRY})의\s*"
        r"수출\s*증가율은\s*각각\s*"
        rf"{_NUMBER}%,?\s*{_NUMBER}%였다[.]?$"
    )
    source, sentences = _source_sentences(body)
    for index, sentence in enumerate(sentences):
        fact = value.fullmatch(sentence)
        if (not fact or re.search(_UNASSERTED, sentence)
                or not _positive(fact['amount']) or not _positive(fact['rate'])
                or source_statement_retracted(source, sentence)):
            continue
        context_index = index - 1
        if context_index >= 0 and comparison.fullmatch(sentences[context_index]):
            context_index -= 1
        if context_index < 0:
            continue
        context = sentences[context_index]
        date = period.fullmatch(context)
        if (not date or re.search(_UNASSERTED, context)
                or not 1 <= int(date['first']) <= int(date['last']) <= 12
                or source_statement_retracted(source, context)):
            continue
        region = "EU" if re.fullmatch(r"유럽연합\s*\(\s*EU\s*\)", date['region']) else date['region']
        product = re.sub(r"\s+", " ", fact['product']).replace("열처리가금육", "열처리 가금육").replace("열처리닭고기", "열처리 닭고기")
        amount = re.sub(r"\s+", "", fact['amount'])
        summary = (f"{date['year']} {int(date['first'])}~{int(date['last'])}월 {region} {product} "
                   f"수출액 {amount}달러, 전년 동기비 {fact['rate']}% 증가")
        return summary, context + " " + sentence
    return None


def native_korean_trade_current_brief(kind: str, body: str) -> tuple[str, str] | None:
    """Return a source-only proposal, never an unconditional completed result."""
    if kind == 'domestic_pork':
        return _single_pork_export_record(body)
    if kind == 'domestic_chicken':
        return _poultry_export_value(body)
    return None
