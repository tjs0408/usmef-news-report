"""Offline discovery limits and source-only report recovery safeguards."""
from contextlib import ExitStack
from datetime import date
import unittest
from unittest.mock import patch

from src import livestock_article_draft as d
from src import overseas_article_digest as s


START, END = date(2026, 9, 27), date(2026, 10, 3)
BRIEF = '미국 계란 공급이 회복되면서 산란계 사육 규모와 생산량 변화에 따른 시장 가격 하락세 지속'


def original(name, **updates):
    return {'title': 'US egg prices supply ' + str(name),
            'url': 'https://example.org/' + str(name),
            'publisher': 'Test', 'publishedDate': date(2026, 10, 2),
            'body': 'US egg prices fell as supplies and production recovered. ' * 5,
            'sourceLanguage': 'en', **updates}


class NativeOriginalGuardsTests(unittest.TestCase):
    def test_native_ready_original_retains_full_original_and_prepared_fit(self):
        item = original('ready')
        with patch.object(d, '_relevance', return_value=1), \
             patch.object(s, '_native_report_sentence', return_value=BRIEF) as native, \
             patch.object(s, '_fit_report_summary', return_value=BRIEF) as fit, \
             patch.object(s, '_valid_brief', return_value=True), \
             patch.object(s, '_native_source_excerpt', return_value='actual source passage'), \
             patch.object(s, '_ollama_generate') as infer:
            ready = d._native_ready_original(item, d.SPECS_BY_KEY['us_egg'], START, END)
        self.assertEqual(ready['_nativeReadySummary'], ('us_egg', item['body'], BRIEF))
        self.assertEqual(ready['briefBody'], 'actual source passage')
        self.assertEqual(ready['publishedDate'], item['publishedDate'])
        native.assert_called_once_with('us_egg', item['body'])
        fit.assert_called_once_with(BRIEF, 'us_egg', item['body'])
        infer.assert_not_called()

    def test_unverified_originals_never_become_ready(self):
        invalid = (
            {'publishedDate': date(2026, 9, 26)}, {'publishedDate': None},
            {'searchResult': True}, {'headlineOnly': True}, {'body': 'short'},
            {'url': 'javascript:alert(1)'}, {'originalUrl': 'file:///private'},
        )
        with patch.object(d, '_relevance', return_value=1), \
             patch.object(s, '_native_report_sentence', return_value=BRIEF) as native:
            for updates in invalid:
                with self.subTest(updates=updates):
                    self.assertIsNone(d._native_ready_original(original('bad', **updates),
                                      d.SPECS_BY_KEY['us_egg'], START, END))
        native.assert_not_called()

    def test_domestic_language_and_target_are_rechecked(self):
        spec = d.SPECS_BY_KEY['domestic']
        with patch.object(d, '_relevance', return_value=1), \
             patch.object(s, '_native_report_sentence') as native:
            self.assertIsNone(d._native_ready_original(original('english'), spec, START, END))
            self.assertIsNone(d._native_ready_original(original('wrong-language',
                body='미국 소고기 가격과 공급 변화에 따른 수급 전망을 확인한 기사입니다. ' * 5,
                sourceLanguage='en'), spec, START, END))
        native.assert_not_called()
        with patch.object(d, '_relevance', return_value=-1), \
             patch.object(s, '_native_report_sentence') as native:
            self.assertIsNone(d._native_ready_original(original('wrong-target'),
                              d.SPECS_BY_KEY['us_egg'], START, END))
        native.assert_not_called()

    def test_native_match_still_requires_fit_and_factual_validation(self):
        for native_value, fitted, valid in ((None, None, True), (BRIEF, None, True),
                                             (BRIEF, BRIEF, False)):
            with self.subTest(native=native_value, fitted=fitted, valid=valid), \
                 patch.object(d, '_relevance', return_value=1), \
                 patch.object(s, '_native_report_sentence', return_value=native_value), \
                 patch.object(s, '_fit_report_summary', return_value=fitted), \
                 patch.object(s, '_valid_brief', return_value=valid):
                self.assertIsNone(d._native_ready_original(original('not-ready'),
                                  d.SPECS_BY_KEY['us_egg'], START, END))


class NativeChooserTests(unittest.TestCase):
    def choose(self, candidates, *, diagnostics=None, ready_at=(), native_only=True):
        def prepared(item, *_args, **_kwargs):
            return {**item, '_nativeReadySummary': ('us_egg', item['body'], BRIEF)} \
                if item['url'] in ready_at else None
        with patch.object(d, '_original_article', side_effect=lambda item, _spec: item) as read, \
             patch.object(d, '_relevance', return_value=1), \
             patch.object(d, '_with_selection', side_effect=lambda item, *_args, **_kwargs: item), \
             patch.object(d, '_native_ready_original', side_effect=prepared):
            result = d._choose_original(candidates, d.SPECS_BY_KEY['us_egg'], START, END,
                                        diagnostics=diagnostics, native_only=native_only)
        return result, read

    def test_native_search_continues_past_three_readable_but_unready_originals(self):
        candidates = [original(i) for i in range(12)]
        diagnostics = {}
        ready, read = self.choose(candidates, diagnostics=diagnostics,
                                  ready_at={candidates[4]['url']})
        self.assertEqual(ready['url'], candidates[4]['url'])
        self.assertEqual(read.call_count, 6)  # bounded parallel batch, not three successful reads
        self.assertEqual(diagnostics['nativeReady'], 1)
        self.assertEqual(diagnostics['originalsChecked'], 6)

    def test_native_search_stops_after_first_ready_parallel_batch(self):
        candidates = [original(i) for i in range(12)]
        ready, read = self.choose(candidates, ready_at={candidates[0]['url']})
        self.assertEqual(ready['url'], candidates[0]['url'])
        self.assertEqual(read.call_count, 3)

    def test_native_original_allowance_is_eighteen(self):
        diagnostics = {}
        ready, read = self.choose([original(i) for i in range(30)], diagnostics=diagnostics)
        self.assertIsNone(ready)
        self.assertEqual(read.call_count, 18)
        self.assertEqual(diagnostics['originalsChecked'], 18)

    def test_native_allowance_is_shared_with_prior_search_stages(self):
        diagnostics = {'originalsChecked': 17}
        ready, read = self.choose([original(i) for i in range(12)], diagnostics=diagnostics)
        self.assertIsNone(ready)
        self.assertEqual(read.call_count, 1)
        self.assertEqual(diagnostics['originalsChecked'], 18)


class NativeSearchTests(unittest.TestCase):
    def empty_searches(self, stack):
        stack.enter_context(patch.object(s, '_search_google_news_rss', return_value=[]))
        stack.enter_context(patch.object(s, '_search_naver_news', return_value=[]))
        stack.enter_context(patch.object(d, '_public_bing_candidates', return_value=[]))
        stack.enter_context(patch.object(d, '_public_google_candidates', return_value=[]))
        stack.enter_context(patch.object(d, 'cited_media_queries', return_value=()))

    def test_native_search_shares_eighteen_originals_across_query_stages(self):
        first = [original('first-' + str(i), title='미국 소고기 가격 ' + str(i)) for i in range(6)]
        later = [original('later-' + str(i), title='중국 소고기 수입 ' + str(i)) for i in range(25)]
        initial = {'소고기 관세', '중국 소고기 수입', '미국 소고기 공급'}
        diagnostics = {}
        with patch.object(s, '_search_naver_news', side_effect=lambda query, *_args:
                          first if query in initial else later) as search, \
             patch.object(d, 'cited_media_queries', return_value=('reference query',)), \
             patch.object(d, '_original_article', side_effect=lambda item, _spec: item) as read, \
             patch.object(d, '_relevance', return_value=1), \
             patch.object(d, '_native_ready_original', return_value=None), \
             patch.object(d, '_public_bing_candidates') as bing, \
             patch.object(d, '_public_google_candidates') as google:
            result = d._search_article(d.SPECS_BY_KEY['domestic'], START, END,
                                       diagnostics=diagnostics, native_only=True)
        self.assertIsNone(result)
        self.assertEqual(read.call_count, 18)
        self.assertEqual(diagnostics['originalsChecked'], 18)
        self.assertEqual({call.args[0] for call in search.call_args_list[:3]}, initial)
        bing.assert_not_called()
        google.assert_not_called()

    def test_native_search_does_not_return_unchecked_special_early_sources(self):
        for key, helper in (('us', '_official_market_article'),
                            ('us_pork', '_local_market_site_article'),
                            ('us_egg', '_preferred_site_article')):
            with self.subTest(key=key), ExitStack() as stack:
                self.empty_searches(stack)
                special = stack.enter_context(patch.object(d, helper, return_value=original('unready')))
                self.assertIsNone(d._search_article(d.SPECS_BY_KEY[key], START, END, native_only=True))
                special.assert_not_called()

    def test_safras_dynamic_feed_retains_selected_week_and_original_source(self):
        feed_url = 'https://safras.com.br/commodity/frango/feed/'
        xml = '''<rss><channel>
            <item><title>Brasil frango preços e oferta</title>
              <link>https://safras.com.br/current-chicken-market/</link>
              <pubDate>Fri, 02 Oct 2026 10:00:00 GMT</pubDate></item>
            <item><title>Brasil frango preços antigos</title>
              <link>https://safras.com.br/previous-week/</link>
              <pubDate>Fri, 25 Sep 2026 10:00:00 GMT</pubDate></item>
            <item><title>Brasil frango preços foreign</title>
              <link>https://other.example/unverified/</link>
              <pubDate>Fri, 02 Oct 2026 10:00:00 GMT</pubDate></item>
        </channel></rss>'''
        with patch.object(s, '_download_html', return_value=xml) as feed, \
             patch.object(d, '_original_article', side_effect=lambda item, _spec:
                          {**item, 'body': 'Brasil frango preços e oferta no mercado. ' * 6}) as read, \
             patch.object(d, '_relevance', return_value=1), \
             patch.object(d, '_with_selection', side_effect=lambda item, *_args, **_kwargs: item), \
             patch.object(s, '_native_report_sentence', return_value=BRIEF), \
             patch.object(s, '_fit_report_summary', return_value=BRIEF), \
             patch.object(s, '_valid_brief', return_value=True), \
             patch.object(s, '_native_source_excerpt', return_value='actual publisher original'), \
             patch.object(s, '_search_google_news_rss') as search, \
             patch.object(s, '_download_soup') as listing:
            result = d._search_article(d.SPECS_BY_KEY['brazil_chicken'], START, END)
        feed.assert_called_once_with(feed_url)
        read.assert_called_once()
        self.assertEqual(result['url'], 'https://safras.com.br/current-chicken-market/')
        self.assertEqual(result['publishedDate'], date(2026, 10, 2))
        self.assertEqual(result['publisher'], 'SAFRAS & Mercado')
        self.assertIn('_nativeReadySummary', result)
        search.assert_not_called()
        listing.assert_not_called()

    def test_unready_safras_feed_does_not_bypass_ordinary_discovery(self):
        xml = '''<rss><channel><item><title>Brasil frango preços e oferta</title>
            <link>https://safras.com.br/readable-but-unready/</link>
            <pubDate>Fri, 02 Oct 2026 10:00:00 GMT</pubDate></item></channel></rss>'''
        with ExitStack() as stack:
            self.empty_searches(stack)
            stack.enter_context(patch.object(s, '_download_html', return_value=xml))
            stack.enter_context(patch.object(s, '_download_soup', side_effect=s.ArticleDigestError('offline')))
            stack.enter_context(patch.object(d, '_original_article', return_value=None))
            stack.enter_context(patch.object(d, '_native_ready_original', return_value=None))
            search = stack.enter_context(patch.object(s, '_search_google_news_rss', return_value=[]))
            self.assertIsNone(d._search_article(d.SPECS_BY_KEY['brazil_chicken'], START, END))
        self.assertGreater(search.call_count, 0)


class RelatedFallbackTierTests(unittest.TestCase):
    def test_management_guide_and_pork_led_chicken_quote_are_related_not_direct(self):
        examples = (
            ('australia', 'Best practice guide to help producers prepare cattle for feedlots'),
            ('brazil_chicken', 'Carcaça suína fica abaixo do frango no mercado brasileiro'),
        )
        for key, title in examples:
            with self.subTest(key=key), \
                 patch.object(d, '_independent_market_passages', return_value=['independent target fact']), \
                 patch.object(d, '_strict_relevance', return_value=10):
                profile = d._selection_profile(original(key, title=title), d.SPECS_BY_KEY[key])
            self.assertEqual(profile[0], 2)
            self.assertIn('보완', profile[2])

    def test_price_reporting_with_guide_word_is_not_demoted(self):
        with patch.object(d, '_independent_market_passages', return_value=['cattle price fact']), \
             patch.object(d, '_strict_relevance', return_value=10):
            profile = d._selection_profile(original('market', title='Cattle prices guide Australian exports'),
                                           d.SPECS_BY_KEY['australia'])
        self.assertEqual(profile[0], 0)


if __name__ == '__main__':
    unittest.main()
