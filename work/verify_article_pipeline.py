"""Opt-in live verification: real dated sources/model, never fixture injection.

Run from the project root with .venv/Scripts/python.exe -X utf8
work/verify_article_pipeline.py 2026-09-04 [2026-10-08 ...]. Receipts contain
public metadata, briefs, counters and validation results. Public originals
are saved separately for independent QA, only in Git-ignored output/.
"""
from __future__ import annotations

from contextlib import ExitStack
from datetime import date, datetime
import json
from pathlib import Path
import sys
from threading import Lock
from time import monotonic
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app  # Normal local .env loading; credentials are never printed.
from src import livestock_article_draft as collector
from src import overseas_article_digest as digest
from src.article_hwpx_layout import summary_reference_layout


def verify(day: date) -> dict:
    originals = {}
    lock = Lock()
    announced = set()

    def remember(value, kind):
        if isinstance(value, dict):
            if value.get('body') and value.get('url'):
                with lock:
                    for field in ('url', 'originalUrl'):
                        if value.get(field):
                            originals[(kind, str(value[field]))] = value
            for key in ('alternatives', '_candidateLinkOriginals'):
                for child in value.get(key, []):
                    remember(child, kind)
        return value

    def observe(name, function):
        def wrapped(*args, **kwargs):
            value = function(*args, **kwargs)
            if isinstance(value, dict) and not value.get('url'):
                for kind, article in value.items():
                    remember(article, kind)
            else:
                spec = args[1] if name in ('_original_article', '_with_selection') else args[0]
                remember(value, spec.key)
            return value
        return wrapped

    def progress(**event):
        for key, section in event.get('sections', {}).items():
            status = section.get('status')
            if status in ('completed', 'summary_error', 'source_error', 'no_article') and (key, status) not in announced:
                announced.add((key, status))
                print(f'{day} {monotonic()-started:.1f}s {key}: {status}', flush=True)
                if status == 'summary_error':
                    print(json.dumps({'section': key, 'error': section.get('summaryError'),
                                      'diagnostics': section.get('diagnostics')}, ensure_ascii=False), flush=True)

    started = monotonic()
    with ExitStack() as stack:
        # These wrappers only retain real returned original text for QA.
        for name in ('_original_article', '_find_section', '_search_article', '_usmef_pair', '_with_selection'):
            stack.enter_context(patch.object(collector, name, observe(name, getattr(collector, name))))
        result = collector.collect_weekly_livestock_report_draft(day, progress=progress)
    result = app._describe_article_outcome(result)
    result['elapsedSeconds'] = round(monotonic() - started, 1)
    result['verification'] = {}
    failures = []
    start, end = map(date.fromisoformat, (result['weekStart'], result['weekEnd']))
    for key, section in result['sections'].items():
        if not section.get('summary'):
            continue
        public = section['article']
        original = originals.get((key, str(public.get('originalUrl')))) or originals.get((key, str(public['url'])))
        if original is None:
            failures.append(f'{key}: selected original missing from QA capture')
            continue
        summary = section['summary']
        reasons = digest.brief_validation_reasons(summary, key, original['body'])
        check = {
            'originalInWeek': start <= original['publishedDate'] <= end,
            'contentValid': not reasons,
            'validationReasons': reasons,
            'layout': summary_reference_layout(summary, key),
            'sourceSelection': collector._selection_profile(original, collector.SPECS_BY_KEY[key],
                trusted_country=not collector.SPECS_BY_KEY[key].domestic),
        }
        result['verification'][key] = check
        if not (check['originalInWeek'] and check['contentValid'] and check['layout']['withinLineLimit']
                and check['sourceSelection'] is not None):
            failures.append((key, check))
    domestic = [section['article'] for key, section in result['sections'].items()
                if collector.SPECS_BY_KEY[key].domestic and section.get('summary')]
    if not all(not collector._same_domestic_article(a, b)
               for index, a in enumerate(domestic) for b in domestic[:index]):
        failures.append('duplicate domestic articles')
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    target = ROOT / 'output' / f'article_pipeline_verified_{day:%Y%m%d}_{stamp}.json'
    result['verificationPassed'] = not failures
    result['verificationFailures'] = failures
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    # Source snapshots are local QA inputs, never production search fallbacks.
    # Retain the original publication date, not the requested week date.
    source_target = ROOT / 'output' / f'article_pipeline_originals_{day:%Y%m%d}_{stamp}.json'
    source_records = []
    seen = set()
    for (kind, _url), original in originals.items():
        identity = kind, original['url']
        if identity in seen:
            continue
        seen.add(identity)
        source_records.append({'kind': kind, **{name: original.get(name) for name in (
            'title', 'url', 'originalUrl', 'publisher', 'publishedDate', 'body', 'briefBody',
            'sourceLanguage', 'sourceCountry', 'searchResult', 'headlineOnly')}})
    source_target.write_text(json.dumps(source_records, ensure_ascii=False, indent=2,
                            default=lambda value: value.isoformat() if isinstance(value, date) else str(value)), encoding='utf-8')
    print(json.dumps({'reportDate': str(day), 'elapsedSeconds': result['elapsedSeconds'],
        'readyCount': result['readyCount'], 'failureCounts': result['failureCounts'],
        'modelCalls': sum(s['diagnostics']['modelCalls'] for s in result['sections'].values()),
        'receipt': str(target)}, ensure_ascii=False), flush=True)
    if failures:
        raise AssertionError(f'Live source/summary QA failed: {failures}')
    return result


if __name__ == '__main__':
    days = [date.fromisoformat(value) for value in sys.argv[1:]]
    if not days:
        raise SystemExit('Specify one or more report dates for live source/model verification.')
    for day in days:
        verify(day)
