"""Offline public-discovery breadth, bounds, isolation and cancellation."""
from threading import Barrier, Event, Lock
import unittest
from unittest.mock import Mock

from src.article_cancellation import ArticleDraftCancelled, article_cancellation_scope, check_article_cancelled
from src.market_issue_discovery import discover_issue_candidates
from src.publisher_history_discovery import PublicSearchCandidates


def item(name, **updates):
    return {'url': f'https://example.org/{name}', 'title': name, 'body': 'search snippet', **updates}


class MarketIssueDiscoveryTests(unittest.TestCase):
    def call(self, queries=('policy', 'demand', 'disease'), **callbacks):
        supplied = {name: callbacks.get(name, Mock(return_value=[]))
                    for name in ('rss_search', 'web_search', 'bing_search')}
        result = discover_issue_candidates(queries, **supplied)
        return *result, supplied

    def test_all_providers_are_compared_even_when_first_result_exists(self):
        rss, web, bing = (Mock(side_effect=lambda q: [item('rss-' + q)]),
                          Mock(side_effect=lambda q: [item('web-' + q)]),
                          Mock(side_effect=lambda q: [item('bing-' + q)]))
        found, counts, _ = self.call(rss_search=rss, web_search=web, bing_search=bing)
        self.assertEqual([call.args[0] for call in rss.call_args_list], ['policy', 'demand'])
        self.assertEqual([call.args[0] for call in web.call_args_list], ['disease'])
        self.assertEqual([call.args[0] for call in bing.call_args_list], ['demand', 'disease'])
        self.assertEqual(counts['plannedCalls'], 5)
        self.assertEqual(counts['attempts'], 5)
        self.assertEqual(counts['candidateCount'], 5)
        self.assertEqual(len(found), 5)
        self.assertTrue(all(isinstance(value, int) for value in counts.values()))

    def test_zero_one_two_queries_and_duplicate_query_input(self):
        for queries, attempts in (([], 0), (['price'], 3), (['price', 'supply'], 5),
                                   ([' price ', 'price', 'supply', 'ignored'], 5)):
            with self.subTest(queries=queries):
                _, counts, callbacks = self.call(queries)
                self.assertEqual(counts['attempts'], attempts)
                self.assertFalse(any('ignored' in call.args for callback in callbacks.values()
                                     for call in callback.call_args_list))
        _, counts, callbacks = self.call('one query')
        self.assertEqual(counts['attempts'], 3)
        self.assertEqual(callbacks['rss_search'].call_args.args, ('one query',))

    def test_interstitial_and_unavailable_stop_the_provider_without_retry(self):
        rss = Mock(return_value=PublicSearchCandidates(reason='unavailable'))
        web = Mock(return_value=PublicSearchCandidates(reason='interstitial'))
        bing = Mock(side_effect=lambda query: [item('bing-' + query)])
        found, counts, _ = self.call(rss_search=rss, web_search=web, bing_search=bing)
        self.assertEqual(len(found), 2)
        self.assertEqual(rss.call_count, 1)
        self.assertEqual(web.call_count, 1)
        self.assertEqual(bing.call_count, 2)
        self.assertEqual(counts['rssUnavailable'], 1)
        self.assertEqual(counts['rssSkippedQueries'], 1)
        self.assertEqual(counts['webInterstitial'], 1)

    def test_exception_is_isolated_and_sensitive_error_text_is_not_retained(self):
        rss = Mock(side_effect=RuntimeError('secret request header must not be recorded'))
        found, counts, _ = self.call(rss_search=rss, web_search=Mock(return_value=[item('web')]))
        self.assertEqual([candidate['title'] for candidate in found], ['web'])
        self.assertEqual(counts['rssFailures'], 1)
        self.assertEqual(counts['rssSkippedQueries'], 1)
        self.assertNotIn('secret', repr(counts))

    def test_url_validation_fragment_dedup_and_no_input_mutation(self):
        record = item('one', _nativeReadySummary=('fake', 'snippet', 'draft'),
                      briefBody='snippet', sourceExcerpt='snippet', searchResult=False)
        invalid = [{'url': url} for url in ('javascript:alert(1)', 'file:///private',
                                           'https:///empty', 'https://x.invalid:bad/a',
                                           'https://user:password@example.org/a', 'https://example.org/a b',
                                           'https://example.org/a\x00b')]
        invalid += ['not a mapping', {'title': 'missing URL'}]
        found, counts, _ = self.call(['one'], rss_search=Mock(return_value=[record] + invalid),
            web_search=Mock(return_value=[item('duplicate', url='https://EXAMPLE.ORG/one#fragment')]))
        self.assertEqual(len(found), 1)
        self.assertEqual(counts['duplicateUrls'], 1)
        self.assertEqual(counts['invalidCandidates'], len(invalid))
        self.assertTrue(found[0]['searchResult'])
        self.assertTrue(found[0]['headlineOnly'])
        self.assertNotIn('_nativeReadySummary', found[0])
        self.assertNotIn('briefBody', found[0])
        self.assertNotIn('sourceExcerpt', found[0])
        self.assertFalse(record['searchResult'])
        self.assertIn('_nativeReadySummary', record)

    def test_candidate_and_query_response_caps_preserve_provider_breadth(self):
        def results(provider):
            return lambda query: [item(f'{provider}-{query}-{index}') for index in range(200)]
        found, counts, _ = self.call(rss_search=results('rss'), web_search=results('web'), bing_search=results('bing'))
        self.assertEqual(len(found), 60)
        self.assertEqual(counts['attempts'], 5)
        self.assertEqual(counts['candidateLimitReached'], 1)
        self.assertEqual(counts['rssTruncatedResults'], 2)
        self.assertEqual(counts['webTruncatedResults'], 1)
        self.assertEqual(counts['bingTruncatedResults'], 2)
        self.assertEqual({candidate['title'].rsplit('-', 1)[0] for candidate in found},
                         {'rss-policy', 'rss-demand', 'web-disease', 'bing-demand', 'bing-disease'})

    def test_bad_response_shapes_are_not_converted_to_source_records(self):
        for payload in ('html response', {'url': 'https://example.org'}, 99):
            with self.subTest(payload=payload):
                found, counts, _ = self.call(['one'], web_search=Mock(return_value=payload))
                self.assertEqual(found, [])
                self.assertEqual(counts['webInvalidResponses'] + counts['webFailures'], 1)

    def test_providers_overlap_with_at_most_three_workers(self):
        barrier, lock = Barrier(3), Lock()
        active = peak = 0
        def callback(query):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            barrier.wait(timeout=3)
            with lock:
                active -= 1
            return []
        # One query means exactly one call per provider, allowing a no-sleep
        # barrier to prove that they overlap and do not serialize providers.
        self.call(['one'], rss_search=callback, web_search=callback, bing_search=callback)
        self.assertEqual(peak, 3)

    def test_cancelled_before_start_never_calls_a_provider(self):
        event = Event()
        event.set()
        callback = Mock(return_value=[])
        with self.assertRaises(ArticleDraftCancelled), article_cancellation_scope(event):
            self.call(rss_search=callback, web_search=callback, bing_search=callback)
        callback.assert_not_called()

    def test_job_cancellation_reaches_worker_callback_and_propagates(self):
        event = Event()
        def cancelled(query):
            event.set()
            check_article_cancelled()
        with self.assertRaises(ArticleDraftCancelled), article_cancellation_scope(event):
            self.call(rss_search=cancelled)

    def test_explicit_worker_cancellation_is_not_swallowed_as_search_failure(self):
        with self.assertRaises(ArticleDraftCancelled):
            self.call(rss_search=Mock(side_effect=ArticleDraftCancelled('stopped')))


if __name__ == '__main__':
    unittest.main()
