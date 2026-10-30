"""Fail-closed Korean briefs from explicit Japanese egg-news explanations.

These are small source-frame parsers, not a general translation fallback. The
collector must independently verify the original, requested week and Japanese
market. In particular, Japanese-language reporting about another country is not
Japanese market evidence. No national price is inferred from a shop interview.
"""

from __future__ import annotations

import re
import unicodedata

from .report_editorial_selection import japanese_egg_editorial_passages


_PACK_PRICE = re.compile(
    r"卵\((?P<size>LL|MS|M|L|S)1パック\)店頭価格"
    r"(?P<price>\d{1,4}(?:,\d{3})*)円\(前週比±0円\)"
)
_CALM_DEMAND_OUTLOOK = re.compile(
    r"(?:今は|現在は)(?:少し)?需要が落ち着いて(?:います|いる)(?:ので|ため)、?"
    r"(?P<month>\d{1,2})月末(?:頃)?までは?"
    r"この(?:ぐらい|程度)の価格で推移していくのではないかと"
    r"思って(?:います|いる)"
)
_RETAILER = re.compile(r"生鮮食品館|スーパー|小売店|食品館|店主|店長|小売業者")
_RETAIL_LOCATION = re.compile(
    r"(?P<place>名古屋市|札幌市|東京都|北海道)"
    r"[^。！？]{0,80}(?:生鮮食品館|スーパー|小売店|食品館)"
)
_PLACE_KOREAN = {
    "名古屋市": "나고야",
    "札幌市": "삿포로",
    "東京都": "도쿄",
    "北海道": "홋카이도",
}
_COST_DEMAND_OUTLOOK = re.compile(
    r"(?:タマゴ|たまご|鶏卵|卵)の価格は今後、"
    r"(?:トリのエサ代|飼料代|飼料費|えさ代|エサ代)(?:や|・)"
    r"(?:運送代|輸送費|物流費)などの(?:値上げ|上昇)、"
    r"年末の需要期も重なるため、一時的に上昇する可能性がある"
    r"(?:ということです|としています|といいます)"
)
_CONTRADICTORY = re.compile(
    r"誤報|誤り|訂正|撤回|架空|仮定|例えば|たとえば|もしも|"
    r"事実ではない|事実でない|否定|見通しではない|可能性はない|"
    r"可能性がない|落ち着いていない|落ち着いておらず|"
    r"わけではない|とは言えない|とはいえない|といえない|"
    r"ということはない|ということではない|思っていない|思っていません"
)
_OTHER_MARKET = re.compile(
    r"(?:米国|アメリカ|中国|韓国|ブラジル|豪州|オーストラリア|ドイツ|"
    r"欧州|ニュージーランド|台湾)(?:では|での|の|における|市場|国内)"
)
_NON_POULTRY = re.compile(r"魚卵|カジカの卵|イクラ|受精卵|卵巣|ワクチン|卵アレルギー|細胞培養")


def _compact_with_offsets(body: str) -> tuple[str, list[int]]:
    """Match typography-insensitively while retaining exact source offsets."""
    letters: list[str] = []
    offsets: list[int] = []
    for index, character in enumerate(body):
        for normalized in unicodedata.normalize("NFKC", character):
            if normalized.isspace():
                continue
            letters.append(normalized)
            offsets.append(index)
    return "".join(letters), offsets


def _exact_evidence(body: str, offsets: list[int], start: int, end: int) -> str:
    return body[offsets[start]:offsets[end - 1] + 1]


def _safe_context(text: str, start: int, end: int) -> bool:
    # Include attribution and the following denial, but not an earlier fish/rice
    # subsection of a mixed grocery report. Explicit negation never becomes a
    # positive or certain prediction merely because the quoted phrase matches.
    context = text[max(0, start - 90):min(len(text), end + 90)]
    return not (_CONTRADICTORY.search(context)
                or _OTHER_MARKET.search(context)
                or _NON_POULTRY.search(context))


def _retail_outlook(body: str, text: str, offsets: list[int]) -> tuple[str, str] | None:
    egg_blocks = [_compact_with_offsets(passage)[0]
                  for passage in japanese_egg_editorial_passages('', body)]
    for price in _PACK_PRICE.finditer(text):
        # A same-subsection price and attributed forecast are both necessary.
        # Do not join a price from one shop to another article's demand outlook.
        remainder = text[price.end():price.end() + 700]
        boundary = re.search(r"次に|最後に|関連記事|おすすめ記事|タマネギの|キャベツの", remainder)
        if boundary:
            remainder = remainder[:boundary.start()]
        outlook = _CALM_DEMAND_OUTLOOK.search(remainder)
        if not outlook or not _RETAILER.search(remainder[:outlook.start()]):
            continue
        end = price.end() + outlook.end()
        # The reader supplies the FULL original, including other grocery
        # sections. Price and forecast must occupy the same intact egg block;
        # an intervening rice/fish subject cannot donate its demand outlook.
        if not any(text[price.start():end] in block for block in egg_blocks):
            continue
        if not _safe_context(text, price.start(), end):
            continue
        month = int(outlook["month"])
        amount = int(price["price"].replace(",", ""))
        if not 1 <= month <= 12 or amount <= 0:
            continue
        # Retain store scope even if the article contains no usable location.
        # A lone city in navigation or a comparison does not locate this shop.
        start = price.start()
        locations = list(_RETAIL_LOCATION.finditer(text[max(0, start - 650):start]))
        distinct_places = {match["place"] for match in locations}
        prefix = "소매점 측은"
        if len(distinct_places) == 1:
            location = locations[-1]
            location_start = max(0, start - 650) + location.start()
            if _safe_context(text, location_start, end):
                start = location_start
                prefix = _PLACE_KOREAN[location["place"]] + " 소매점은"
        # Keep the causal shop outlook rather than repeating the quote table.
        # Omitting the amount also omits its size/pack denominator; neither can
        # leak into a misleading national or per-kilogram quotation. This
        # short frame preserves room for the source's actual locality at the
        # report's fixed one-line font/spacing limits.
        summary = (
            f"{prefix} 계란 수요 진정에 {month}월 말까지 "
            "현 수준의 판매가격 유지 전망"
        )
        if 40 <= len(summary) <= 95:
            return summary, _exact_evidence(body, offsets, start, end)
    return None


def native_japan_egg_news_brief(body: str) -> tuple[str, str] | None:
    """Return a narrowly supported Korean brief and exact original substring.

    Two explainers are currently supported: a retailer's explicitly unchanged
    pack price plus calming-demand monthly outlook, or a reported possibility
    of temporary egg-price increases from feed/transport costs and year-end
    demand. Unsupported numbers, foreign-market prose, negated forecasts,
    fish roe, and headline-only claims are not converted into ready summaries.
    """
    if not isinstance(body, str) or not body.strip():
        return None
    text, offsets = _compact_with_offsets(body)
    retail = _retail_outlook(body, text, offsets)
    if retail:
        return retail
    for match in _COST_DEMAND_OUTLOOK.finditer(text):
        if not _safe_context(text, match.start(), match.end()):
            continue
        summary = "계란은 사료·운송비 상승과 연말 수요가 겹치며 가격의 일시적 상승 가능성"
        return summary, _exact_evidence(body, offsets, match.start(), match.end())
    return None
