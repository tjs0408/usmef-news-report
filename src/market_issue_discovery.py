"""Compare a small, fixed set of public searches before choosing an article.

This module only returns discovery candidates. Search dates, country/species,
publisher text, factual grounding and summary layout belong to the caller's
original reader/selection pipeline. No model, API credentials, fixed article
URLs or fallback publication dates are used here.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from itertools import islice, zip_longest
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .article_cancellation import ArticleDraftCancelled, check_article_cancelled, map_article_tasks


MAX_DISCOVERY_QUERIES = 3
MAX_DISCOVERY_CANDIDATES = 60
MAX_DISCOVERY_WORKERS = 3
_MAX_QUERY_RESULTS = 60
_COUNTERS = ('Attempts', 'Collected', 'Interstitial', 'Unavailable', 'Failures',
             'Empty', 'SkippedQueries', 'TruncatedResults', 'InvalidResponses')
_MISSING = object()


def _queries(values: Iterable[str]) -> list[str]:
    if isinstance(values, str):
        values = [values]
    result = []
    # Only the policy's first three queries are in scope; do not consume an
    # arbitrary generator to find more work after that bound.
    for value in islice(values, MAX_DISCOVERY_QUERIES):
        if not isinstance(value, str):
            continue
        query = ' '.join(value.split())
        if query and query not in result:
            result.append(query)
    return result


def _identity(value: Any) -> str | None:
    if (not isinstance(value, str) or not value
            or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value)):
        return None
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname
                or parsed.username is not None or parsed.password is not None):
            return None
        # Validate malformed/out-of-range ports before passing the URL along.
        parsed.port
    except (TypeError, ValueError):
        return None
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(),
                       parsed.path or '/', parsed.query, ''))


def discover_issue_candidates(queries: Iterable[str], *, rss_search: Callable[[str], Any],
                              web_search: Callable[[str], Any],
                              bing_search: Callable[[str], Any]
                              ) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Run at most five public requests with at most three provider workers.

    RSS uses the first two queries, web the last, and Bing the last two. A
    provider reporting interstitial/unavailable (or raising an ordinary error)
    is not retried; other providers still contribute. Cancellation propagates
    to every worker through the existing job-scoped executor helpers.

    Diagnostics are integer counters only. ``Collected`` means discovery
    records read (before URL validation/dedup), never verified originals.
    """
    check_article_cancelled()
    selected_queries = _queries(queries)
    diagnostics = {provider + counter: 0 for provider in ('rss', 'web', 'bing') for counter in _COUNTERS}
    diagnostics.update(plannedCalls=0, attempts=0, candidateCount=0,
                       duplicateUrls=0, invalidCandidates=0, candidateLimitReached=0)
    if not selected_queries:
        return [], diagnostics
    plan = (
        ('rss', rss_search, selected_queries[:2]),
        ('web', web_search, selected_queries[-1:]),
        ('bing', bing_search, selected_queries[-2:]),
    )
    diagnostics['plannedCalls'] = sum(len(items) for _, _, items in plan)

    def run_provider(task):
        provider, callback, provider_queries = task
        counters = {provider + counter: 0 for counter in _COUNTERS}
        batches = []
        for index, query in enumerate(provider_queries):
            check_article_cancelled()
            counters[provider + 'Attempts'] += 1
            try:
                found = callback(query)
                check_article_cancelled()
                reason = getattr(found, 'discovery_reason', '')
                if reason in ('interstitial', 'unavailable'):
                    counters[provider + ('Interstitial' if reason == 'interstitial' else 'Unavailable')] += 1
                    counters[provider + 'SkippedQueries'] += len(provider_queries) - index - 1
                    break
                if found is None:
                    records = []
                elif isinstance(found, (str, bytes, Mapping)):
                    counters[provider + 'InvalidResponses'] += 1
                    records = []
                else:
                    records = list(islice(iter(found), _MAX_QUERY_RESULTS + 1))
                if len(records) > _MAX_QUERY_RESULTS:
                    counters[provider + 'TruncatedResults'] += 1
                    records = records[:_MAX_QUERY_RESULTS]
            except ArticleDraftCancelled:
                raise
            except Exception:
                # No exception text is retained: it can contain request URLs
                # or response details. Failed providers cannot hide others.
                counters[provider + 'Failures'] += 1
                counters[provider + 'SkippedQueries'] += len(provider_queries) - index - 1
                break
            counters[provider + 'Collected'] += len(records)
            counters[provider + 'Empty'] += int(not records)
            batches.append(records)
        return counters, batches

    batches = []
    with ThreadPoolExecutor(max_workers=MAX_DISCOVERY_WORKERS,
                            thread_name_prefix='market-issue-search') as executor:
        for counters, provider_batches in map_article_tasks(executor, run_provider, plan):
            diagnostics.update(counters)
            batches.extend(provider_batches)
    check_article_cancelled()

    candidates = []
    seen = set()
    # Give every topic/provider a chance rather than filling all 60 slots from
    # whichever search returned first. Stable ordering also makes QA repeatable.
    for row in zip_longest(*batches, fillvalue=_MISSING):
        for record in row:
            if record is _MISSING:
                continue
            check_article_cancelled()
            if not isinstance(record, Mapping) or not (identity := _identity(record.get('url'))):
                diagnostics['invalidCandidates'] += 1
                continue
            if identity in seen:
                diagnostics['duplicateUrls'] += 1
                continue
            seen.add(identity)
            if len(candidates) >= MAX_DISCOVERY_CANDIDATES:
                diagnostics['candidateLimitReached'] = 1
                continue
            candidate = dict(record)
            # These are search snippets, even if a callback accidentally
            # carried cached preparation flags. Only the original reader may
            # turn them into evidence and mark them verified afterwards.
            for field in ('_nativeReadySummary', 'briefBody', 'sourceExcerpt'):
                candidate.pop(field, None)
            candidate.update(searchResult=True, headlineOnly=True)
            candidates.append(candidate)
    diagnostics['attempts'] = sum(diagnostics[provider + 'Attempts'] for provider in ('rss', 'web', 'bing'))
    diagnostics['candidateCount'] = len(candidates)
    return candidates, diagnostics
