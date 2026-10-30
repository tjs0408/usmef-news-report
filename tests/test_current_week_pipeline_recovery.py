"""Current-week parser, publication-gate and collector recovery integration.

All sources are local fixtures: no requests or real model inference is allowed.
"""
from contextlib import ExitStack
from datetime import date
from threading import Event
import unittest
from unittest.mock import patch

from src import livestock_article_draft as d, overseas_article_digest as s
from src.article_hwpx_layout import summary_reference_layout
from src.australia_market_brief_facts import native_australia_market_brief
from src.japan_egg_brief_facts import native_japan_egg_brief
from src.korean_trade_brief_facts import native_korean_trade_brief
from src.usda_brief_facts import native_usda_brief

from test_australia_market_brief_facts import BODY as AU_BODY
from test_japan_current_facts import BODY as JP_BODY
from test_korean_trade_brief_facts import EGG as KR_EGG, PORK as KR_PORK
from test_usda_current_facts import BROILER, EGG as US_EGG


DAY = date(2026, 10, 20)
KR_CONTEXT = '국내 언론은 해외 교역과 관련한 별도 거래 사실을 취재해 보도했다. '
CASES = (
    ('us_chicken', 'Daily National Broiler Market-At-A-Glance', BROILER,
     lambda body: native_usda_brief('us_chicken', body)),
    ('us_egg', 'Daily National Shell Egg Index Report', US_EGG,
     lambda body: native_usda_brief('us_egg', body)),
    ('australia', 'Widespread rain hits Qld and cuts highways, more forecast this week', AU_BODY,
     native_australia_market_brief),
    ('japan_egg', 'JA全農たまご 鶏卵相場（東京）', JP_BODY, native_japan_egg_brief),
    ('domestic_pork', '제주 돼지고기 싱가포르·몽골 수출시장 다변화', KR_CONTEXT * 2 + KR_PORK,
     lambda body: native_korean_trade_brief('domestic_pork', body)),
    ('domestic_egg', '브라질산 계란 수입단가 국정감사 지적', KR_CONTEXT * 2 + KR_EGG,
     lambda body: native_korean_trade_brief('domestic_egg', body)),
)


def original(key, title, body, **extra):
    return {
        'url': 'https://example.org/original/' + key,
        'title': title, 'publisher': '공개 원문 검증 매체', 'body': body,
        'briefBody': '원문 첫 문장만 담아 핵심 둘째 문장이 누락된 짧은 편집 발췌.',
        'publishedDate': DAY, 'sourceLanguage': d.SPECS_BY_KEY[key].language,
        'sourceCountry': d.SPECS_BY_KEY[key].country,
        'searchResult': False, 'headlineOnly': False,
        '_candidateLinksSearched': True, **extra,
    }


class CurrentWeekPipelineRecoveryTests(unittest.TestCase):
    def setUp(self):
        s._summarize_report_sentence.cache_clear()

    def tearDown(self):
        s._summarize_report_sentence.cache_clear()

    def test_real_native_modules_survive_summary_validation_fit_and_evidence_dispatch(self):
        with patch.object(s, '_ollama_generate', side_effect=AssertionError('native fact must not invoke AI')) as model:
            for key, title, body, parser in CASES:
                with self.subTest(key=key):
                    native, evidence = parser(body)
                    self.assertEqual(s._native_report_sentence(key, body), native)
                    self.assertTrue(s._valid_brief(native, key, body), s.brief_validation_reasons(native, key, body))
                    summary = s._summarize_report_sentence(key, title, body)
                    self.assertTrue(s._valid_brief(summary, key, body), summary)
                    self.assertTrue(summary_reference_layout(summary, key)['withinLineLimit'], summary)
                    self.assertEqual(s._native_source_excerpt(body, native), evidence)
                    self.assertGreaterEqual(len(summary), 40)
                    self.assertNotIn('요약 호출 횟수', summary)
            model.assert_not_called()

    def test_collector_passes_full_original_not_truncated_editorial_brief_to_summarizer(self):
        articles = {key: original(key, title, body) for key, title, body, _ in CASES}
        original_native = s._native_report_sentence
        summarized = {}

        def summarize(key, title, body, *_args, **_kwargs):
            # Exercise the real fact parsers after observing the collector's
            # public summarizer arguments, with discovery/preselection disabled.
            self.assertEqual(body, articles[key]['body'])
            self.assertNotEqual(body, articles[key]['briefBody'])
            summarized[key] = body
            native = original_native(key, body)
            self.assertIsNotNone(native, key)
            self.assertTrue(s._valid_brief(native, key, body), key)
            return s._fit_report_summary(native, key, body)

        with ExitStack() as stack:
            stack.enter_context(patch.object(d, '_usmef_pair', return_value={}))
            stack.enter_context(patch.object(d, '_find_section', side_effect=lambda spec, *_:
                                            articles.get(spec.key)))
            stack.enter_context(patch.object(d, '_search_article', return_value=None))
            stack.enter_context(patch.object(d, '_candidate_links', return_value=[]))
            # Discovery is already mocked as verified. Keep this test focused
            # on the summarizer input contract, not adaptive topic ranking.
            stack.enter_context(patch.object(d, '_relevance', side_effect=lambda candidate, spec, **_:
                                            10 if candidate.get('url') == articles.get(spec.key, {}).get('url') else -1))
            stack.enter_context(patch.object(s, '_ensure_ollama_ready', return_value={'available': True}))
            # Force this test through the actual summarizer call site instead
            # of completing directly in the native preselection fast path.
            stack.enter_context(patch.object(s, '_native_report_sentence', return_value=None))
            stack.enter_context(patch.object(s, '_summarize_report_sentence', side_effect=summarize))
            model = stack.enter_context(patch.object(s, '_request_json', side_effect=AssertionError('no model or HTTP')))
            download = stack.enter_context(patch.object(s, '_download_soup', side_effect=AssertionError('no source HTTP')))
            result = d.collect_weekly_livestock_report_draft(DAY)

        self.assertEqual(set(summarized), set(articles))
        self.assertEqual(result['readyCount'], len(articles))
        for key in articles:
            with self.subTest(key=key):
                section = result['sections'][key]
                self.assertEqual(section['status'], 'completed', section)
                self.assertEqual(section['diagnostics']['modelCalls'], 0)
                self.assertEqual(section['article']['url'], articles[key]['url'])
        model.assert_not_called()
        download.assert_not_called()

    def test_collector_recovers_from_late_native_original_after_both_model_calls_are_spent(self):
        primary = original('domestic_pork', '미국 돼지고기 수급 현지 취재',
                           '미국 돼지고기 공급과 수요 및 가격 추이를 살펴본 현지 시장 취재 기사다. ' * 5,
                           url='https://example.org/pork-primary')
        alternate = original('domestic_pork', '제주 돼지고기 싱가포르·몽골 수출',
                             KR_CONTEXT * 2 + KR_PORK, url='https://example.org/pork-recovery')
        summary_started = Event()
        tried = []

        def links(candidate, spec, *_args, **kwargs):
            if spec.key == 'domestic_pork' and kwargs.get('search_missing') is not False:
                if not summary_started.wait(timeout=2):
                    raise AssertionError('collector never reached the primary summarizer')
                candidate['_candidateLinkOriginals'] = [alternate]
            return []

        def summarize(key, title, body, *_args, **_kwargs):
            tried.append(title)
            self.assertEqual(title, primary['title'], 'native recovery must not require a third summarizer call')
            summary_started.set()
            s._ollama_generate('failed source draft')
            s._ollama_generate('failed source repair')
            raise s.ArticleSummaryValidationError('both generated drafts failed')

        with ExitStack() as stack:
            stack.enter_context(patch.object(d, '_usmef_pair', return_value={}))
            stack.enter_context(patch.object(d, '_find_section', side_effect=lambda spec, *_:
                                            primary if spec.key == 'domestic_pork' else None))
            stack.enter_context(patch.object(d, '_search_article', return_value=None))
            stack.enter_context(patch.object(d, '_candidate_links', side_effect=links))
            stack.enter_context(patch.object(d, '_relevance', side_effect=lambda candidate, spec, **_:
                                            10 if spec.key == 'domestic_pork' else -1))
            stack.enter_context(patch.object(s, '_ensure_ollama_ready', return_value={'available': True}))
            stack.enter_context(patch.object(s, '_summarize_report_sentence', side_effect=summarize))
            request = stack.enter_context(patch.object(s, '_request_json', return_value={'response': '짧음'}))
            result = d.collect_weekly_livestock_report_draft(DAY)
        section = result['sections']['domestic_pork']
        self.assertEqual(section['status'], 'completed', section)
        self.assertEqual(section['article']['url'], alternate['url'])
        self.assertEqual(section['diagnostics']['modelCalls'], 2)
        self.assertEqual(section['diagnostics']['alternativeAttempts'], 1)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(tried, [primary['title']])
        self.assertTrue(s._valid_brief(section['summary'], 'domestic_pork', alternate['body']))
        self.assertIn('싱가포르', section['article']['sourceExcerpt'])

    def test_two_call_budget_remains_bounded_but_does_not_block_native_recovery(self):
        for key, title, body, _ in CASES:
            with self.subTest(key=key):
                budget = s.ArticleModelBudget(max_calls=2)
                with s.article_model_budget(budget), patch.object(s, '_request_json', return_value={'response': '짧음'}) as request:
                    s._ollama_generate('first unsuccessful attempt')
                    s._ollama_generate('second unsuccessful attempt')
                    with self.assertRaises(s.ArticleSummaryBudgetExceeded):
                        s._ollama_generate('third model call is still prohibited')
                    summary = s._summarize_report_sentence(key, title, body)
                    self.assertTrue(s._valid_brief(summary, key, body), summary)
                    self.assertEqual(budget.calls, 2)
                    self.assertEqual(request.call_count, 2)

    def test_budget_error_from_editorial_attempt_falls_back_to_valid_native_source(self):
        # The wrapper's recovery must work even if an editorial attempt fails
        # before returning a sentence; it must not reset the exhausted budget.
        for key, title, body, _ in CASES:
            with self.subTest(key=key):
                budget = s.ArticleModelBudget(max_calls=2, calls=2)
                with s.article_model_budget(budget), \
                     patch.object(s, '_summarize_report_sentence_content', side_effect=s.ArticleSummaryBudgetExceeded('two calls spent')), \
                     patch.object(s, '_request_json', side_effect=AssertionError('cannot exceed two calls')) as request:
                    summary = s._summarize_report_sentence(key, title, body)
                self.assertTrue(s._valid_brief(summary, key, body), summary)
                self.assertEqual(budget.calls, 2)
                request.assert_not_called()


if __name__ == '__main__':
    unittest.main()
