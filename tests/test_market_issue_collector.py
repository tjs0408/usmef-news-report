"""Bounded issue comparison, final-source input and ready-source recovery.

No network or real model calls. Date/country/species ranking is exercised where
possible; model response/fit are controlled only to isolate collector flow.
"""
from contextlib import ExitStack
from copy import deepcopy
from datetime import date
import unittest
from unittest.mock import patch

from src import livestock_article_draft as collector
from src import overseas_article_digest as digest
from src.article_cancellation import ArticleDraftCancelled
from src.market_issue_selection import FOREIGN_MARKET_KINDS


DAY = date(2026, 10, 7)
START, END = date(2026, 10, 4), date(2026, 10, 10)
KEY = 'us_egg'
BASE_BODY = ('US egg production was 9 billion, up 6% from last year. '
             'US egg inventories reached 30 million dozen. Weekly egg production is reported here.')
ISSUE_PASSAGE = ('US egg supplies fell due to bird flu, pushing retail egg prices higher. '
                 'US egg producers face a reduced flock and recovery may take several months.')
ISSUE_BODY = ('US egg wholesale prices were $3.20 per dozen.\n' + ISSUE_PASSAGE)
NATIVE = '미국 계란 생산량은 전년보다 증가한 가운데 주간 공급량과 재고 수준을 함께 기록'
ISSUE_SUMMARY = '미국 계란 공급은 조류인플루엔자에 따른 산란계 감소로 부족해져 소매가격 상승'


def article(name, *, title='US egg weekly production', body=BASE_BODY, **extra):
    return {'title': title, 'body': body, 'url': 'https://example.org/' + name,
            'publisher': 'Verified source', 'publishedDate': date(2026, 10, 6),
            'sourceLanguage': 'en', 'searchResult': False, 'headlineOnly': False, **extra}


def issue_article(**extra):
    values = {'title': 'US egg supplies tighten as disease disrupts farms', 'body': ISSUE_BODY, **extra}
    return article('issue', **values)


class MarketIssueCollectorTests(unittest.TestCase):
    def test_every_foreign_baseline_gets_one_comparison_even_if_already_native_or_contextual(self):
        for kind in FOREIGN_MARKET_KINDS:
            with self.subTest(kind=kind):
                original = article(kind, _nativeReadySummary=(kind, BASE_BODY, NATIVE))
                before = deepcopy(original)
                with patch.object(collector, '_search_article', return_value=None) as search, \
                     patch.object(collector, '_relevance', return_value=10):
                    selected = collector._broaden_editorial_candidate(
                        original, collector.SPECS_BY_KEY[kind], START, END)
                    again = collector._broaden_editorial_candidate(
                        selected, collector.SPECS_BY_KEY[kind], START, END)
                self.assertEqual(search.call_count, 1)
                self.assertTrue(search.call_args.kwargs['editorial'])
                self.assertEqual(search.call_args.args[1:], (START, END))
                self.assertIn(original['url'], search.call_args.kwargs['exclude_urls'])
                self.assertEqual(selected['url'], original['url'])
                self.assertTrue(selected['_issueComparisonDone'])
                self.assertTrue(selected['_candidateLinksSearched'])
                self.assertEqual(again, selected)
                self.assertEqual(original, before)

    def test_domestic_sections_do_not_receive_foreign_issue_scan(self):
        for kind in ('domestic', 'domestic_pork', 'domestic_chicken', 'domestic_egg'):
            original = article(kind)
            with patch.object(collector, '_search_article') as search:
                selected = collector._broaden_editorial_candidate(
                    original, collector.SPECS_BY_KEY[kind], START, END)
            self.assertIs(selected, original)
            search.assert_not_called()

    def test_optional_scan_failure_preserves_original_and_records_counter(self):
        original = article('baseline')
        with patch.object(collector, '_search_article', side_effect=RuntimeError('upstream')), \
             patch.object(collector, '_relevance', return_value=10):
            selected = collector._broaden_editorial_candidate(
                original, collector.SPECS_BY_KEY[KEY], START, END)
        self.assertEqual(selected['url'], original['url'])
        self.assertEqual(selected['_searchDiagnostics']['issueScanFailures'], 1)
        self.assertTrue(selected['_issueComparisonDone'])
        self.assertNotIn('upstream', str(selected))

    def test_same_tier_substantive_issue_beats_ready_statistic(self):
        main = article('baseline', alternatives=[issue_article()], _issueComparisonDone=True)
        spec = collector.SPECS_BY_KEY[KEY]
        self.assertEqual(collector._selection_profile(main, spec)[0], 0)
        self.assertEqual(collector._selection_profile(main['alternatives'][0], spec)[0], 0)
        with patch.object(digest, '_native_report_sentence', side_effect=lambda _kind, body:
                          NATIVE if body == BASE_BODY else None), \
             patch.object(digest, '_fit_report_summary', side_effect=lambda value, *_: value), \
             patch.object(digest, '_valid_brief', return_value=True):
            selected = collector._prefer_native_summary_candidate(main, spec, START, END, True)
        self.assertEqual(selected['url'], issue_article()['url'])
        self.assertNotIn('_nativeReadySummary', selected)
        self.assertEqual(selected['alternatives'][0]['url'], main['url'])

    def test_stale_future_snippet_and_invalid_original_cannot_replace_baseline(self):
        cases = (
            {'publishedDate': date(2026, 10, 3)},
            {'publishedDate': date(2026, 10, 11)},
            {'searchResult': True}, {'headlineOnly': True},
            {'url': 'javascript:alert(1)'}, {'originalUrl': 'javascript:alert(1)'},
            {'body': 'US eggs rise due to supply shortages.'},
        )
        for changes in cases:
            with self.subTest(changes=changes):
                main = article('baseline')
                other = issue_article(**changes)
                with patch.object(collector, '_search_article', return_value=other):
                    chosen = collector._broaden_editorial_candidate(
                        main, collector.SPECS_BY_KEY[KEY], START, END)
                self.assertEqual(chosen['url'], main['url'])
                self.assertEqual(chosen['publishedDate'], main['publishedDate'])
                self.assertEqual(chosen['alternatives'], [])

    def test_comparison_pool_is_bounded_and_keeps_designated_fallback(self):
        baseline = article('baseline')
        issues = [article('issue-' + str(index), title='US egg disease supply and prices',
                          body=ISSUE_BODY + ' Producer observation ' + str(index)) for index in range(7)]
        with patch.object(collector, '_search_article', return_value={**issues[0], 'alternatives': issues[1:]}):
            chosen = collector._broaden_editorial_candidate(
                baseline, collector.SPECS_BY_KEY[KEY], START, END)
        pool = [chosen] + chosen['alternatives']
        self.assertLessEqual(len(pool), 5)
        self.assertIn(baseline['url'], {item['url'] for item in pool})
        self.assertNotEqual(chosen['url'], baseline['url'])
        self.assertTrue(all(item['_issueComparisonDone'] and item['_candidateLinksSearched'] for item in pool))
        self.assertEqual(chosen['_searchDiagnostics']['issueComparedOriginals'], 5)

    def test_richer_issue_cannot_jump_above_stronger_relevance_tier(self):
        lower = issue_article(title='Trade and farm policy review')
        main = article('baseline', alternatives=[lower], _issueComparisonDone=True)
        spec = collector.SPECS_BY_KEY[KEY]
        self.assertEqual(collector._selection_profile(main, spec)[0], 0)
        self.assertEqual(collector._selection_profile(lower, spec)[0], 1)
        with patch.object(collector, '_search_article', return_value=lower):
            broadened = collector._broaden_editorial_candidate(
                {**main, '_issueComparisonDone': False}, spec, START, END)
        self.assertEqual(broadened['url'], main['url'])
        with patch.object(digest, '_native_report_sentence', side_effect=lambda _kind, body:
                          NATIVE if body == BASE_BODY else None), \
             patch.object(digest, '_fit_report_summary', side_effect=lambda value, *_: value), \
             patch.object(digest, '_valid_brief', return_value=True):
            selected = collector._prefer_native_summary_candidate(main, spec, START, END, True)
        self.assertEqual(selected['url'], main['url'])
        self.assertEqual(selected['_nativeReadySummary'][2], NATIVE)

    def collect(self, *, available=True, fail_issue=False, issue_has_native=True):
        baseline = article('baseline')
        issue = issue_article()
        calls = []

        def search(spec, *_args, **kwargs):
            if spec.key == KEY and kwargs.get('editorial'):
                return issue
            return None

        def summarize(kind, title, body):
            calls.append((kind, title, body))
            self.assertEqual(kind, KEY)
            self.assertEqual(title, issue['title'])
            self.assertNotIn('$3.20', body)
            self.assertIn('bird flu', body)
            self.assertIn('retail egg prices higher', body)
            self.assertIn(body, issue['body'])
            if fail_issue:
                digest._ollama_generate('bounded test request')
                digest._ollama_generate('bounded test repair')
                raise digest.ArticleSummaryValidationError('controlled invalid translation')
            return ISSUE_SUMMARY

        def native(_kind, body):
            # The issue original also contains a parsed daily quote. It must
            # not publish that quote in place of its stronger actual issue.
            return NATIVE if body == BASE_BODY or issue_has_native and body == ISSUE_BODY else None

        with ExitStack() as stack:
            stack.enter_context(patch.object(collector, '_usmef_pair', return_value={}))
            stack.enter_context(patch.object(collector, '_find_section', side_effect=lambda spec, *_:
                                            baseline if spec.key == KEY else None))
            search_mock = stack.enter_context(patch.object(collector, '_search_article', side_effect=search))
            stack.enter_context(patch.object(collector, '_candidate_links', return_value=[]))
            stack.enter_context(patch.object(digest, '_ensure_ollama_ready',
                return_value={'available': available, 'message': 'offline' if not available else 'available'}))
            stack.enter_context(patch.object(digest, '_native_report_sentence', side_effect=native))
            stack.enter_context(patch.object(digest, '_fit_report_summary', side_effect=lambda value, *_: value))
            stack.enter_context(patch.object(digest, '_valid_brief', return_value=True))
            summary_mock = stack.enter_context(patch.object(digest, '_summarize_report_sentence', side_effect=summarize))
            request = stack.enter_context(patch.object(digest, '_request_json', return_value={'response': 'controlled'}))
            stack.enter_context(patch.object(digest, '_download_soup', side_effect=AssertionError('no network')))
            stack.enter_context(patch.object(digest, '_download_html', side_effect=AssertionError('no network')))
            result = collector.collect_weekly_livestock_report_draft(DAY)
        editorial_calls = [call for call in search_mock.call_args_list
                           if call.args[0].key == KEY and call.kwargs.get('editorial')]
        self.assertEqual(len(editorial_calls), 1)
        return result['sections'][KEY], calls, summary_mock, request

    def test_only_final_issue_passage_not_its_daily_quote_reaches_summarizer(self):
        section, calls, summary, request = self.collect()
        self.assertEqual(section['status'], 'completed')
        self.assertEqual(section['article']['url'], issue_article()['url'])
        self.assertEqual(section['summary'], ISSUE_SUMMARY)
        self.assertEqual(len(calls), 1)
        self.assertEqual(summary.call_count, 1)
        request.assert_not_called()

    def test_offline_model_preserves_valid_native_fallback_without_inference(self):
        section, calls, summary, request = self.collect(available=False)
        self.assertEqual(section['status'], 'completed')
        self.assertEqual(section['summary'], NATIVE)
        self.assertEqual(calls, [])
        summary.assert_not_called()
        request.assert_not_called()

    def test_failed_issue_translation_reuses_baseline_native_within_same_model_budget(self):
        section, calls, summary, request = self.collect(fail_issue=True, issue_has_native=False)
        self.assertEqual(section['status'], 'completed')
        self.assertEqual(section['article']['url'], article('baseline')['url'])
        self.assertEqual(section['summary'], NATIVE)
        self.assertEqual(len(calls), 1)
        self.assertEqual(summary.call_count, 1)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(section['diagnostics']['modelCalls'], 2)
        self.assertEqual(section['diagnostics']['alternativeAttempts'], 1)

    def test_failed_issue_translation_can_keep_its_own_valid_native_without_research(self):
        section, calls, summary, request = self.collect(fail_issue=True)
        self.assertEqual(section['status'], 'completed')
        self.assertEqual(section['article']['url'], issue_article()['url'])
        self.assertEqual(section['summary'], NATIVE)
        self.assertEqual(len(calls), 1)
        self.assertEqual(summary.call_count, 1)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(section['diagnostics']['modelCalls'], 2)
        self.assertEqual(section['sourceDiagnostics']['issueSummaryFallback'], 1)

    def test_cancellation_is_not_converted_to_optional_scan_failure(self):
        with patch.object(collector, '_search_article', side_effect=ArticleDraftCancelled('cancel')):
            with self.assertRaises(ArticleDraftCancelled):
                collector._broaden_editorial_candidate(article('baseline'),
                    collector.SPECS_BY_KEY[KEY], START, END)


if __name__ == '__main__':
    unittest.main()
