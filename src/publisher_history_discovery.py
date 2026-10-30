"""Bounded, date-aware discovery through publishers' advertised public surfaces.

These are discovery records only. The collector still reads each original and
checks its publication week, language, country and commodity before summarizing.
No Google redirect-token decoding, authentication or browser challenge handling.
"""
from __future__ import annotations

from datetime import date, datetime
import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

from .article_cancellation import cancellable_lock, check_article_cancelled
from .runtime_cache import ttl_cache


HISTORY_TIMEOUT_SECONDS = 5
HISTORY_RESPONSE_LIMIT = 2_000_000
# Permanent publisher taxonomy, advertised in public shell-egg article
# breadcrumbs. The older broad table-eggs category omits this commodity feed.
INDEXBOX_SHELL_EGG_NEWS_URL = (
    "https://www.indexbox.io/blog/product/"
    "birds__eggs_in_shell__fresh_not_for_incubation_of_fowls_of_the_species_gallus_domesticus_domestic_hens/")
SEARCH_TERMS = {
    "beef": ("cattle", "beef"), "pork": ("pig", "pork"),
    "chicken": ("broiler", "poultry"), "egg": ("egg",),
}


class PublicSearchCandidates(list):
    """List-compatible records carrying a non-secret empty-response reason."""
    def __init__(self, values=(), *, reason: str = ""):
        super().__init__(values)
        self.discovery_reason = reason


def _same_host(first: str, second: str) -> bool:
    return bool(urlparse(first).hostname) and (
        (urlparse(first).hostname or "").lower().removeprefix("www.")
        == (urlparse(second).hostname or "").lower().removeprefix("www."))


class _HistoryUnavailable(RuntimeError):
    pass


@ttl_cache(seconds=300, maxsize=96)
def _cached_public_json(url: str) -> list[dict[str, Any]]:
    """One public request; 401/403 are terminal, never retried by another route."""
    from .overseas_article_digest import PUBLIC_USER_AGENT, _HTTP_SLOTS
    check_article_cancelled()
    try:
        with cancellable_lock(_HTTP_SLOTS):
            with urlopen(Request(url, headers={"User-Agent": PUBLIC_USER_AGENT,
                                              "Accept": "application/json"}),
                         timeout=HISTORY_TIMEOUT_SECONDS) as response:
                # Do not accept a redirect to an unrelated login or proxy host.
                if not _same_host(response.geturl(), url):
                    raise _HistoryUnavailable()
                raw = response.read(HISTORY_RESPONSE_LIMIT + 1)
        if len(raw) > HISTORY_RESPONSE_LIMIT:
            raise _HistoryUnavailable()
        payload = json.loads(raw)
    except (HTTPError, URLError, OSError, ValueError, UnicodeError):
        raise _HistoryUnavailable() from None
    check_article_cancelled()
    if not isinstance(payload, list):
        raise _HistoryUnavailable()
    return payload


def _public_json(url: str) -> list[dict[str, Any]] | None:
    # A short transient outage must not poison the next user-initiated run.
    # Successful results (including a genuine empty result) remain cached.
    try:
        return _cached_public_json(url)
    except _HistoryUnavailable:
        return None


def public_history_candidates(page: BeautifulSoup, page_url: str, *, species: str,
                              language: str, publisher: str, start: date, end: date,
                              diagnostics: dict[str, int] | None = None) -> list[dict[str, Any]]:
    """At most two dated queries against a WordPress API advertised by this page.

    The API's original post ``date`` is used, not ``modified`` or an RSS refresh
    timestamp. External links, protected posts and out-of-week dates are refused.
    A failed/unauthorized public endpoint stops this host immediately.
    """
    advertised = page.select_one('link[rel="https://api.w.org/"][href]')
    if not advertised:
        return []
    root = urljoin(page_url, str(advertised.get("href", "")))
    if urlparse(root).scheme != "https" or not _same_host(root, page_url):
        return []
    terms = ("frango", "avicultura") if language == "pt" and species == "chicken" else SEARCH_TERMS.get(species, ())
    results: dict[str, dict[str, Any]] = {}
    for term in terms[:2]:
        check_article_cancelled()
        filters = {"after": f"{start.isoformat()}T00:00:00",
                           "before": f"{end.isoformat()}T23:59:59",
                           "search": term, "per_page": 30, "orderby": "date", "order": "desc",
                           "_fields": "link,title,date,excerpt,content"}
        parts = urlparse(root)
        advertised_query = parse_qs(parts.query)
        if 'rest_route' in advertised_query:
            # Some publishers explicitly advertise WordPress's ordinary
            # query-form route rather than a /wp-json/ permalink root.
            filters['rest_route'] = advertised_query['rest_route'][0].rstrip('/') + '/wp/v2/posts'
            url = urlunparse(parts._replace(query=urlencode(filters), fragment=''))
        elif parts.query:
            break  # unknown advertised endpoint, not a guessed private route
        else:
            url = root.rstrip("/") + "/wp/v2/posts?" + urlencode(filters)
        if diagnostics is not None:
            diagnostics["publisherArchiveRequests"] = diagnostics.get("publisherArchiveRequests", 0) + 1
        posts = _public_json(url)
        if posts is None:
            if diagnostics is not None:
                diagnostics["publisherArchiveUnavailable"] = diagnostics.get("publisherArchiveUnavailable", 0) + 1
            break
        for post in posts:
            if not isinstance(post, dict):
                continue
            href = str(post.get("link", ""))
            try:
                published = datetime.fromisoformat(str(post.get("date", "")).replace("Z", "+00:00")).date()
            except ValueError:
                continue
            title, excerpt, content = (post.get(key, {}) for key in ("title", "excerpt", "content"))
            if (not all(isinstance(value, dict) for value in (title, excerpt, content))
                    or excerpt.get("protected") or content.get("protected")
                    or not start <= published <= end or not _same_host(href, page_url)
                    or urlparse(href).scheme not in ("http", "https")):
                continue
            text = lambda value: BeautifulSoup(str(value.get("rendered", "")), "html.parser").get_text(" ", strip=True)
            headline = text(title)
            if len(headline) < 8:
                continue
            results[href] = {"title": headline, "url": href, "publishedDate": published,
                             "publisher": publisher, "body": (text(content) or text(excerpt))[:3500],
                             "sourceLanguage": language, "discoveryMethod": "publisher_archive"}
        # A useful date-bound batch need not run a second synonym search.
        if results:
            break
    if diagnostics is not None:
        diagnostics["publisherArchiveCandidates"] = diagnostics.get("publisherArchiveCandidates", 0) + len(results)
    return list(results.values())


def public_month_search_urls(page: BeautifulSoup, page_url: str, *, species: str,
                             language: str, start: date, end: date) -> list[str]:
    """Normal public WP month+search pages, never an alternative private API.

    Available only when the page advertises WordPress and a same-host GET search
    form. A week spans at most two calendar months. Original dates are still
    filtered to the exact selected week by the normal listing/original reader.
    """
    if not page.select_one('link[rel="https://api.w.org/"][href]'):
        return []
    form = next((form for form in page.select("form")
                 if str(form.get("method", "get")).lower() == "get"
                 and form.select_one('input[name="s"]')
                 and _same_host(urljoin(page_url, str(form.get("action") or page_url)), page_url)), None)
    if form is None:
        return []
    action = urljoin(page_url, str(form.get("action") or page_url)).split("?", 1)[0]
    term = "frango" if language == "pt" and species == "chicken" else SEARCH_TERMS.get(species, ("",))[0]
    months = {(start.year, start.month), (end.year, end.month)}
    return [action + "?" + urlencode({"s": term, "m": f"{year:04}{month:02}"})
            for year, month in sorted(months, reverse=True)]


def public_next_listing_url(page: BeautifulSoup, page_url: str) -> str | None:
    """Read an advertised next arrow/number, including ordinary ``?page=2``.

    No invented page URLs, private pagination endpoint or last-page jump.
    """
    current = (parse_qs(urlparse(page_url).query).get("page") or ["1"])[0]
    try:
        expected = int(current) + 1
    except ValueError:
        expected = 2
    for link in page.select('.pagination a[href], nav[aria-label*="agination"] a[href]'):
        href = urljoin(page_url, str(link.get("href", "")))
        label = link.get_text(" ", strip=True)
        if not _same_host(href, page_url) or href == page_url:
            continue
        target = (parse_qs(urlparse(href).query).get("page") or [""])[0]
        if target == str(expected) and label in (str(expected), ">", "»", "›", "Next"):
            return href
    return None
