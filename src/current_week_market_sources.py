"""Read a dated public market release when current-week news discovery fails.

The TCFA market page is a rolling public report, not an article archive.  Only
the date printed inside its market-summary block establishes publication; no
requested date, surrounding page date or previous-week value is substituted.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
import re
from typing import Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


TCFA_MARKET_URL = "https://www.tcfa.org/market.html"
# The named USDA BEEF CUT OUT series uses dollars per 100 lb (cwt),
# even when TCFA's short quotation block omits the denominator.
# Official series definition, not an inferred quantity from this week's data:
# https://www.ams.usda.gov/sites/default/files/media/LMRBoxedBeefCutoutsUserGuide.pdf
_MONTHS = {
    name: number for number, name in enumerate(
        ("January", "February", "March", "April", "May", "June", "July",
         "August", "September", "October", "November", "December"), 1)
}
_SUMMARY_HEADER = re.compile(
    r"^TCFA Daily Market Summary\s*[-–—]\s*"
    r"(?P<month>[A-Za-z]+)\s+(?P<day>\d{1,2}),\s*(?P<year>20\d{2})\s*$",
    re.I,
)
_NUMBER = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"


def _header_date(line: str) -> date | None:
    match = _SUMMARY_HEADER.fullmatch(line.strip())
    if not match:
        return None
    month = _MONTHS.get(match["month"].title())
    if not month:
        return None
    try:
        return date(int(match["year"]), month, int(match["day"]))
    except ValueError:
        return None


def _tcfa_summary(html: str, start: date, end: date) -> dict[str, Any] | None:
    """Extract only a complete dated summary, excluding navigation and ads."""
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    page_text = soup.get_text(" ", strip=True)
    if ("Texas Cattle Feeders Association" not in title
            or not re.search(r"Amarillo,?\s+Texas\s+\d{5}", page_text, re.I)):
        return None  # the known US publisher must establish the country
    summaries: list[tuple[date, str]] = []
    for element in soup.select("pre"):
        # Scripts or injected widgets inside <pre> are not market evidence.
        for unwanted in element.select("script, style, iframe, nav, aside"):
            unwanted.decompose()
        body = element.get_text("\n", strip=True).replace("\xa0", " ")
        lines = body.splitlines()
        published = _header_date(lines[0]) if lines else None
        if not published or not start <= published <= end:
            continue
        if not all(re.search(pattern, body, re.I | re.M) for pattern in (
                r"^USDA\s+BEEF\s+CUT\s+OUT\b",
                r"\bCH\s+600/900:\s*\$\d+(?:\.\d+)?\b",
                r"\bSL\s+600/900:\s*\$\d+(?:\.\d+)?\b",
                r"^SLAUGHTER\b", r"\bToday:\s*\d[\d,]*\b")):
            continue
        # A very large block is not the short, public daily summary expected.
        if not 150 <= len(body) <= 12000:
            continue
        summaries.append((published, body))
    if not summaries:
        return None
    published, body = max(summaries, key=lambda item: item[0])
    return {
        "title": f"TCFA Daily Market Summary — {published:%B %d, %Y}",
        "body": body,
        "briefBody": body,
        "publishedAt": published,
        "publishedDate": published,
        "url": TCFA_MARKET_URL,
        "publisher": "Texas Cattle Feeders Association",
        "language": "en",
        "country": "US",
        "sourceLanguage": "en",
        "sourceCountry": "US",
        "sourceMethod": "official",
        "headlineOnly": False,
        "searchResult": False,
    }


def fetch_current_market_source(kind: str, start: date, end: date) -> dict[str, Any] | None:
    """Fetch the public TCFA US-beef summary, with no guessed archive URLs.

    Network errors, an unavailable report, an unrelated redirect or a date
    outside the requested week all return None.  Other species never request
    TCFA.  The caller remains responsible for cancellation and summarization.
    """
    if kind != "us" or not isinstance(start, date) or not isinstance(end, date) or start > end:
        return None
    try:
        response = requests.get(TCFA_MARKET_URL, timeout=(3, 6))
        response.raise_for_status()
        resolved = urlparse(response.url)
        if (resolved.scheme != "https" or resolved.hostname not in ("tcfa.org", "www.tcfa.org")
                or resolved.path != "/market.html"):
            return None
        html = response.text
        if len(html) > 2_000_000:
            return None
    except (requests.RequestException, ValueError):
        return None
    return _tcfa_summary(html, start, end)


def native_tcfa_brief(body: str) -> tuple[str, str] | None:
    """Render the named USDA series with grade labels and its defined unit.

    The USDA boxed-beef cutout definition supplies the 100-lb denominator.
    Neither an unstated comparison period nor a live-cattle price is inferred.
    The caller verifies publication week separately.
    """
    lines = str(body).splitlines()
    if not lines or _header_date(lines[0]) is None:
        return None
    heading = re.search(r"^USDA\s+BEEF\s+CUT\s+OUT\b[^\n]*", body, re.I | re.M)
    if heading is None:
        return None
    cutout = body[heading.end():]
    cutout = re.split(r"^CARCASS\s+EQUIVALENT\s+INDEX\b|^SLAUGHTER\b|^Hide\s*&\s*Offal\b",
                     cutout, maxsplit=1, flags=re.I | re.M)[0]
    readings = []
    evidence_lines = []
    for grade, label in (("CH", "초이스"), ("SL", "셀렉트")):
        matches = list(re.finditer(
            rf"\b{grade}\s+600/900:\s*\$(?P<price>{_NUMBER})"
            rf"\s+(?P<direction>UP|DN)\s+(?P<change>[+-]?{_NUMBER})"
            r"(?=\s|$)", cutout, re.I))
        if len(matches) != 1:
            return None  # conflicting or repeated observations are ambiguous
        match = matches[0]
        try:
            price = Decimal(match["price"].replace(",", ""))
            change = Decimal(match["change"].replace(",", ""))
        except InvalidOperation:
            return None
        direction = match["direction"].upper()
        if price <= 0 or (direction == "UP" and change < 0) or (direction == "DN" and change > 0):
            return None
        if change == 0:
            readings.append(f"{label} 등급 {match['price']}달러로 보합")
        else:
            action = "상승" if direction == "UP" else "하락"
            magnitude = match["change"].lstrip("+-")
            readings.append(f"{label} 등급 {match['price']}달러로 {magnitude}달러 {action}")
        evidence_lines.append(match.group(0))
    summary = "미국 쇠고기 도매가격 지표(100 파운드당)는 " + ", ".join(readings)
    if not 40 <= len(summary) <= 95:
        return None
    evidence = lines[0] + "\n" + heading.group(0) + "\n" + "\n".join(evidence_lines)
    return summary, evidence
