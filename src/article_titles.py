"""Separate explicitly identified publisher labels from the full headline."""

import re
from urllib.parse import urlsplit


def _publisher_host(value: str) -> str:
    """Accept a URL or the bare domain supplied by news discovery."""
    try:
        host = urlsplit(value if "://" in value else "//" + value).hostname or ""
    except ValueError:
        return ""
    return host.casefold().removeprefix("www.")


def normalize_article_publisher(publisher: str, *, title: str = "", url: str = "") -> str:
    """Canonicalize explicit site branding, not arbitrary bracketed labels.

    The user identifies 인싸잇 as the current article's outlet. Its older domain
    can still be returned by discovery, so require that domain AND the explicit
    headline brand before replacing it. Older, unbranded archive stories retain
    their supplied publisher; an unrelated site cannot claim this brand merely
    by mentioning it in a headline.
    """
    publisher = " ".join(publisher.split())
    if publisher.casefold() == "식품저널 foodnews":
        return "식품저널"
    if publisher.casefold() in {"인싸잇", "인싸it"}:
        return "인싸잇"
    branded = re.match(r"^\s*\[\s*인싸(?:잇|it)\s*\]", title, flags=re.I)
    if branded and any(_publisher_host(value) == "mediawatch.kr" for value in (publisher, url) if value):
        return "인싸잇"
    return publisher


def clean_article_title(title: str, publisher: str, *, url: str = "") -> str:
    """Keep the full headline, dropping matching publisher metadata only.

    A dash inside the actual headline, an unmatched publisher, or a publisher
    mentioned in the sentence is not redundant metadata and stays unchanged.
    Editorial labels such as [특파원 보고] are not publisher names and survive.
    """
    title = " ".join(title.split())
    publisher = " ".join(publisher.split())
    if not publisher:
        publisher = normalize_article_publisher(publisher, title=title, url=url)
        if not publisher:
            return title
    canonical = normalize_article_publisher(publisher, title=title, url=url)
    names = {publisher, canonical}
    if canonical == "인싸잇":
        names.add("인싸it")
        # A prior normalization pass may already have canonicalized the outlet
        # while leaving the discovery domain at the end of the headline.
        if _publisher_host(url) == "mediawatch.kr":
            names.update({"mediawatch.kr", "www.mediawatch.kr"})
    escaped_names = "|".join(re.escape(name) for name in sorted(names, key=len, reverse=True))
    pattern = r"\s+(?:[-–—−]|\|)\s*(?:" + escaped_names + r")\s*$"
    cleaned = re.sub(pattern, "", title, flags=re.I).rstrip()
    cleaned = re.sub(r"^\[\s*(?:" + escaped_names + r")\s*\]\s*", "", cleaned, count=1, flags=re.I).lstrip()
    return cleaned or title


def format_domestic_article_title(title: str) -> str:
    """Use single quotes inside the report's outer headline double quotes.

    This is presentation-only: source metadata and ``clean_article_title``
    retain the exact headline punctuation for evidence and saved drafts.
    Existing apostrophes/single quotes are deliberately left unchanged.
    """
    return title.translate(str.maketrans({quote: "'" for quote in '\"“”„‟＂'}))
