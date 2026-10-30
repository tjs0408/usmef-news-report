"""Inference exhaustion must not hide another verified model-free original.

All original discovery and HTTP are mocked. The real model-budget, date,
country/species, native parser and page-fit checks remain active.
"""
from contextlib import ExitStack
from datetime import date
import unittest
from unittest.mock import patch

from src import livestock_article_draft as collector
from src import overseas_article_digest as digest


DAY = date(2026, 10, 7)
START, END = date(2026, 10, 4), date(2026, 10, 10)
KEY = 'us_egg'
MODEL_BODY = ('US egg prices and supply are discussed in this national market report. '
              'Producers describe their responses to demand and distribution trends. ')
READY_BODY = ('The USDA says 9.203 billion eggs were produced in September, up 6% on the year, '
              'with a 5% increase in the average number of layers to 385.065 million head '
              'and 1% rise in the rate of production per 100 layers.')


def original(name, **changes):
    return {'title': 'US egg prices and supply ' + name,
            'url': 'https://example.org/' + name,
            'publishedDate': date(2026, 10, 6), 'publisher': 'Test publisher',
            'body': MODEL_BODY, 'sourceLanguage': 'en',
            'headlineOnly': False, 'searchResult': False, **changes}


def ready_original(**changes):
    return original('native-monthly-report', title='US egg production monthly report', body=READY_BODY, **changes)


class PostBudgetNativeRecoveryTests(unittest.TestCase):
    def collect(self, candidate, *, links_completed=False, failed_alternate=False, fitting=True,
                error_type=digest.ArticleSummaryValidationError):
        """Fail two bounded model calls, then allow only a native recovery."""
        main = original('main-model-only', _candidateLinksSearched=links_completed)
        if failed_alternate:
            main['alternatives'] = [original('second-model-only', body=MODEL_BODY + ' Another independent original.')]
        actual_native = digest._native_report_sentence
        actual_fit = digest._fit_report_summary
        request_budgets = []

        def request(*_args, **_kwargs):
            request_budgets.append(digest._article_model_budget.get())
            return {'response': 'not a publishable source-grounded draft'}

        def fail_summary(_kind, _title, _body):
            # Model calls are accounted by the actual production budget, but
            # no HTTP escapes this harness. With an alternate, exhaust one
            # call on each original to exercise the later exhaustion branch.
            for _ in range(1 if failed_alternate else 2):
                digest._ollama_generate('bounded mock summary')
            raise error_type('요약 검증 미완료: 원문 근거 또는 지면 길이 불일치')

        def search(spec, _start, _end, **kwargs):
            if spec.key == KEY and kwargs.get('native_only'):
                self.assertEqual((_start, _end), (START, END))
                self.assertIn(main['url'], kwargs['exclude_urls'])
                if failed_alternate:
                    self.assertIn(main['alternatives'][0]['url'], kwargs['exclude_urls'])
                diagnostics = kwargs.get('diagnostics')
                if diagnostics is not None:
                    diagnostics.update(candidates=3, originalsChecked=1)
                return candidate
            return None

        def fit(summary, kind, body):
            if body == READY_BODY and not fitting:
                return None
            return actual_fit(summary, kind, body)

        with ExitStack() as stack:
            stack.enter_context(patch.object(collector, '_usmef_pair', return_value={}))
            stack.enter_context(patch.object(collector, '_find_section', side_effect=lambda spec, *_:
                                            main if spec.key == KEY else None))
            # Isolate the optional-link job: it neither performs a network
            # search nor populates a ready original for recovery by accident.
            stack.enter_context(patch.object(collector, '_candidate_links', return_value=[]))
            search_mock = stack.enter_context(patch.object(collector, '_search_article', side_effect=search))
            stack.enter_context(patch.object(digest, '_ensure_ollama_ready', return_value={'available': True}))
            stack.enter_context(patch.object(digest, '_native_report_sentence', side_effect=lambda kind, body:
                                            actual_native(kind, body) if body == READY_BODY else None))
            stack.enter_context(patch.object(digest, '_fit_report_summary', side_effect=fit))
            request_mock = stack.enter_context(patch.object(digest, '_request_json', side_effect=request))
            summarize_mock = stack.enter_context(patch.object(digest, '_summarize_report_sentence', side_effect=fail_summary))
            result = collector.collect_weekly_livestock_report_draft(DAY)
        native_searches = [call for call in search_mock.call_args_list
                           if call.args[0].key == KEY and call.kwargs.get('native_only')]
        ordinary_searches = [call for call in search_mock.call_args_list
                             if call.args[0].key == KEY and not call.kwargs.get('native_only')
                             and not call.kwargs.get('editorial')]
        comparison_searches = [call for call in search_mock.call_args_list
                               if call.args[0].key == KEY and call.kwargs.get('editorial')]
        self.assertEqual(len(native_searches), 1)
        self.assertEqual(len(comparison_searches), 1)
        self.assertEqual(comparison_searches[0].args[1:3], (START, END))
        self.assertEqual(ordinary_searches, [], 'budget exhaustion cannot reopen model-only discovery')
        self.assertEqual(request_mock.call_count, 2)
        self.assertIs(request_budgets[0], request_budgets[1])
        self.assertEqual(request_budgets[0].calls, 2)
        self.assertEqual(request_budgets[0].max_calls, 2)
        self.assertEqual(request_budgets[0].max_seconds, 45)
        section = result['sections'][KEY]
        self.assertEqual(section['diagnostics']['modelCalls'], 2)
        self.assertEqual(section['sourceDiagnostics']['nativeRecoverySearches'], 1)
        return section, summarize_mock, native_searches

    def test_exhausted_primary_recovers_a_new_original_without_more_inference(self):
        candidate = ready_original()
        section, summarize, _ = self.collect(candidate)
        self.assertEqual(section['status'], 'completed')
        self.assertEqual(section['article']['url'], candidate['url'])
        self.assertEqual(section['article']['publishedDate'], '2026-10-06')
        self.assertEqual(section['sourceDiagnostics']['nativeRecoveryReady'], 1)
        self.assertEqual(summarize.call_count, 1)
        self.assertTrue(digest._valid_brief(section['summary'], KEY, READY_BODY))
        self.assertIn('9.203 billion', section['article']['sourceExcerpt'])

    def test_completed_optional_link_search_does_not_disable_budget_free_recovery(self):
        section, summarize, _ = self.collect(ready_original(), links_completed=True)
        self.assertEqual(section['status'], 'completed')
        self.assertEqual(summarize.call_count, 1)
        self.assertEqual(section['sourceDiagnostics']['nativeRecoveryReady'], 1)

    def test_last_call_spent_on_an_alternate_still_allows_one_native_search(self):
        section, summarize, _ = self.collect(ready_original(), links_completed=True, failed_alternate=True)
        self.assertEqual(section['status'], 'completed')
        self.assertEqual(summarize.call_count, 2)
        self.assertEqual(section['sourceDiagnostics']['nativeRecoveryReady'], 1)

    def test_layout_failure_after_two_calls_allows_only_native_ready_recovery(self):
        for failed_alternate in (False, True):
            with self.subTest(failed_alternate=failed_alternate):
                candidate = ready_original()
                section, summarize, _ = self.collect(candidate, links_completed=True,
                    failed_alternate=failed_alternate, error_type=digest.ArticleSummaryLayoutError)
                self.assertEqual(section['status'], 'completed')
                self.assertEqual(section['article']['url'], candidate['url'])
                self.assertEqual(section['article']['publishedDate'], '2026-10-06')
                self.assertEqual(summarize.call_count, 2 if failed_alternate else 1)
                self.assertEqual(section['diagnostics']['modelCalls'], 2)
                self.assertEqual(section['sourceDiagnostics']['nativeRecoveryReady'], 1)
                self.assertTrue(digest._valid_brief(section['summary'], KEY, READY_BODY))

    def test_layout_failure_cannot_publish_an_unfitting_native_match(self):
        section, summarize, _ = self.collect(ready_original(), links_completed=True,
            fitting=False, error_type=digest.ArticleSummaryLayoutError)
        self.assertEqual(section['status'], 'summary_error')
        self.assertIsNone(section.get('summary'))
        self.assertEqual(summarize.call_count, 1)
        self.assertEqual(section['sourceDiagnostics']['nativeRecoveryReady'], 0)

    def test_stale_future_wrong_species_and_unverified_recovery_are_not_completed(self):
        wrong_product = original('wrong-product', title='US pork production report',
                                 body='US pork production increased as hog supplies and slaughter recovered. ' * 3)
        cases = [ready_original(publishedDate=date(2026, 10, 3)),
                 ready_original(publishedDate=date(2026, 10, 11)), wrong_product,
                 ready_original(searchResult=True), ready_original(headlineOnly=True)]
        for candidate in cases:
            with self.subTest(candidate=candidate):
                section, summarize, _ = self.collect(candidate, links_completed=True)
                self.assertEqual(section['status'], 'summary_error')
                self.assertIsNone(section.get('summary'))
                self.assertEqual(summarize.call_count, 1)
                self.assertEqual(section['sourceDiagnostics']['nativeRecoveryReady'], 0)

    def test_native_parser_match_without_page_fit_is_not_completed_or_researched(self):
        section, summarize, _ = self.collect(ready_original(), links_completed=True, fitting=False)
        self.assertEqual(section['status'], 'summary_error')
        self.assertIsNone(section.get('summary'))
        self.assertEqual(summarize.call_count, 1)
        self.assertEqual(section['sourceDiagnostics']['nativeRecoveryReady'], 0)

    def test_empty_native_search_is_attempted_once_without_another_model_call(self):
        section, summarize, _ = self.collect(None, links_completed=True)
        self.assertEqual(section['status'], 'summary_error')
        self.assertEqual(summarize.call_count, 1)
        self.assertEqual(section['sourceDiagnostics']['nativeRecoveryReady'], 0)


if __name__ == '__main__':
    unittest.main()
