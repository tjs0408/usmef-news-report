"""Grounded Korean briefs from JA's explicitly dated Tokyo egg quotation.

The collector remains responsible for checking the requested publication week.
This parser never treats a rolling page URL or another regional table as a date
or as Tokyo's M-size quotation.
"""

from datetime import date
from decimal import Decimal, InvalidOperation
import re
import unicodedata


_NUMBER = r"\d+(?:\.\d+)?"


def native_japan_egg_brief(body: str) -> tuple[str, str] | None:
    """Return an M-size benchmark/arrival brief and its exact Japanese evidence.

    A signed column is the day-on-day change, not a second benchmark. An
    individual size need not move in the same direction as the overall market;
    report its change without asserting a tone for other sizes. The separately
    published market tone remains in the original evidence. All amounts and
    directions must be explicit.
    """
    text = unicodedata.normalize("NFKC", str(body)).replace("−", "-")
    if not re.search(r"鶏卵|たまご", text):
        return None
    announcement = re.search(
        r"(20\d{2})年(\d{1,2})月(\d{1,2})日\([月火水木金土日]\)\s*"
        r"(?:[01]\d|2[0-3]):[0-5]\d\s*発表\b", text,
    )
    if not announcement:
        return None
    try:
        date(*(int(announcement[index]) for index in (1, 2, 3)))
    except ValueError:
        return None
    header = re.search(r"東\s*京\s+高値\s+基準値\s+安値\s+", text)
    if not header:
        return None
    if re.search(r"予定|中止|発表なし|未確定|訂正|誤報", text[announcement.start():header.start()]):
        return None
    table = text[header.end():]
    boundary = re.search(
        r"(?:大\s*阪|名\s*古\s*屋|福\s*岡|札\s*幌)\s+高値", table,
    )
    if boundary:
        table = table[:boundary.start()]
    unit = re.search(r"単位\s*円\s*/\s*kg\b", table, re.I)
    if not unit:
        return None
    table = table[:unit.end()]
    if re.search(
        r"予定|予想|見通し|推定|仮値|参考値|訂正|誤報|未確定|"
        r"発表なし|中止|ではない|でない|ではなく", table,
    ):
        return None
    row = re.search(
        rf"\bM\s+(?P<high>{_NUMBER})\s+(?P<price>{_NUMBER})\s+"
        rf"(?P<change>±0|[+-]{_NUMBER})\s+(?P<low>{_NUMBER})\s+(?:MS\b|市況\b)",
        table,
    )
    arrivals = re.search(rf"入荷量\s+(?P<amount>{_NUMBER})\s*t\b", table)
    if not row or not arrivals:
        return None
    try:
        high, price, low = (Decimal(row[name]) for name in ("high", "price", "low"))
        change = Decimal("0" if row["change"] == "±0" else row["change"])
        if not 0 <= low <= price <= high or price <= 0 or price - change <= 0:
            return None
        if Decimal(arrivals["amount"]) < 0:
            return None
    except InvalidOperation:
        return None
    if change == 0:
        movement = "전일 수준 유지"
    else:
        direction = "상승" if change > 0 else "하락"
        amount = row["change"][1:]
        movement = f"전일비 {amount}엔 {direction}"
    summary = (f"일본 도쿄 계란 M 기준가 kg당 {row['price']}엔, "
               f"{movement}·입하량 {arrivals['amount']}톤 기록")
    # Source values alone are never padded to satisfy the minimum length.
    if not 40 <= len(summary) <= 95:
        return None
    evidence = text[:announcement.end()] + "\n" + text[header.start():header.end()] + table
    return summary, evidence
