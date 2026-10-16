"""Editorial context must not be displaced by an easy numerical parser."""
from contextlib import ExitStack
from copy import deepcopy
from datetime import date
from threading import Event
import unittest
from unittest.mock import patch

from src import livestock_article_draft as d
from src import overseas_article_digest as s
from tests.test_explanatory_market_summary import (
    BEEF_EXPLANATION, CHICKEN_EXPLANATION, CHICKEN_SUMMARY, HATCHERY, PRODUCTION,
)


START, END, REPORT = date(2026, 10, 11), date(2026, 10, 17), date(2026, 10, 14)
YARDING = "Total cattle yardings for the week achieved 63,163, down 15,587, week on week. "
BRAZIL_EXPORT = ("As exportações brasileiras de carne de frango totalizaram 492,6 mil toneladas "
                 "em agosto de 2026, volume 24,8% superior ao registrado no mesmo mês de 2025. ")


def article(key, name, body, **extra):
    title = {
        "us": "미국 소고기 공급 및 가격동향",
        "australia": "Australian beef supply and prices",
        "us_chicken": "US chicken supply and prices",
        "brazil_chicken": "Brasil frango oferta e preços",
    }[key]
    return {"url": "https://example.org/" + name, "title": title, "publisher": "Test",
            "publishedDate": REPORT, "body": body, "briefBody": "An incomplete original excerpt.",
            "sourceLanguage": "ko" if key == "us" else "pt" if key == "brazil_chicken" else "en",
            "headlineOnly": False, "searchResult": False, **extra}


class CollectorEditorialContextTests(unittest.TestCase):
    def setUp(self):
        s._summarize_report_sentence.cache_clear()

    def collect_chicken(self, body, *, available=True, request_effect=None, alternatives=()):
        main = article("us_chicken", "main", body, alternatives=list(alternatives))
        events = []
        inference_seen = False
        real_summarize = s._summarize_report_sentence

        def summarize(key, title, source_body):
            nonlocal inference_seen
            self.assertEqual(source_body, body, "collector must retain the full fallback source")
            self.assertFalse(any(e[0] == "completed" for e in events), "bare native completed before context translation")
            inference_seen = True
            return real_summarize(key, title, source_body)

        def request(*args, **kwargs):
            if request_effect:
                raise request_effect
            self.assertIn(CHICKEN_EXPLANATION, kwargs["body"]["prompt"])
            self.assertNotIn("249839000", kwargs["body"]["prompt"])
            return {"response": CHICKEN_SUMMARY}

        with ExitStack() as stack:
            stack.enter_context(patch.object(d, "_usmef_pair", return_value={}))
            stack.enter_context(patch.object(d, "_find_section", side_effect=lambda spec, *_:
                                            main if spec.key == "us_chicken" else None))
            stack.enter_context(patch.object(d, "_search_article", return_value=None))
            stack.enter_context(patch.object(d, "_candidate_links", return_value=[]))
            stack.enter_context(patch.object(s, "_ensure_ollama_ready", return_value={"available": available, "message": "offline"}))
            infer = stack.enter_context(patch.object(s, "_summarize_report_sentence", side_effect=summarize))
            api = stack.enter_context(patch.object(s, "_request_json", side_effect=request))
            result = d.collect_weekly_livestock_report_draft(REPORT, progress=lambda **event:
                events.append((event["sections"]["us_chicken"]["status"], inference_seen)))
        return result["sections"]["us_chicken"], infer, api, events

    def test_all_four_context_candidates_outrank_a_ready_statistic(self):
        examples = (
            ("us", PRODUCTION * 2, BEEF_EXPLANATION + " 미국 소고기 시장의 공급 동향을 함께 살펴봤다."),
            ("australia", YARDING * 2,
             "Australian beef prices are rising because export demand is strong and cattle supplies are limited. Australian beef supplies remain tight."),
            ("us_chicken", HATCHERY,
             CHICKEN_EXPLANATION + " Supplies remain ample in the domestic market."),
            ("brazil_chicken", BRAZIL_EXPORT * 2,
             "Os preços do frango no Brasil subiram devido à recuperação da demanda interna e à oferta limitada. O mercado brasileiro segue atento à oferta."),
        )
        for key, stat, context in examples:
            with self.subTest(key=key):
                rich = article(key, "rich", context)
                main = article(key, "stat", stat, alternatives=[rich])
                original = deepcopy(main)
                self.assertIsNotNone(s._native_report_sentence(key, stat))
                chosen = d._prefer_native_summary_candidate(main, d.SPECS_BY_KEY[key], START, END, True)
                self.assertEqual(chosen["url"], rich["url"])
                self.assertEqual(main, original)
                if key != "us":
                    self.assertNotIn("_nativeReadySummary", chosen)
                offline = d._prefer_native_summary_candidate(main, d.SPECS_BY_KEY[key], START, END, False)
                self.assertEqual(offline["url"], main["url"])
                self.assertIn("_nativeReadySummary", offline)

    def test_context_translation_uses_original_budget_without_premature_completion(self):
        section, infer, api, events = self.collect_chicken(HATCHERY + CHICKEN_EXPLANATION)
        self.assertEqual(section["status"], "completed")
        self.assertEqual(section["summary"], CHICKEN_SUMMARY)
        self.assertEqual(section["diagnostics"]["modelCalls"], 1)
        self.assertEqual(section["retryCount"], 0)
        self.assertEqual(section["diagnostics"]["alternativeAttempts"], 0)
        self.assertEqual(infer.call_count, 1)
        self.assertEqual(api.call_count, 1)
        self.assertTrue(any(status == "summarizing" and not seen for status, seen in events))
        self.assertTrue(all(seen for status, seen in events if status == "completed"))
        self.assertIn(CHICKEN_EXPLANATION, section["article"]["sourceExcerpt"])

    def test_verified_context_translation_precedes_an_equally_rich_model_only_candidate(self):
        from test_current_market_passage_repairs import LIVE_EXPORT
        model_only = article('australia', 'needs-translation',
            'Australian beef prices are rising because export demand is strong and cattle supplies are limited. '
            'Australian cattle supplies remain tight in the domestic market.')
        ready = article('australia', 'ready-context', LIVE_EXPORT)
        model_only['alternatives'] = [ready]
        self.assertTrue(s._explanatory_market_excerpt('australia', model_only['body']))
        self.assertTrue(s._explanatory_market_excerpt('australia', ready['body']))
        with patch.object(s, '_ollama_generate', side_effect=AssertionError('no inference in selection')):
            chosen = d._prefer_native_summary_candidate(
                model_only, d.SPECS_BY_KEY['australia'], START, END, True)
        self.assertEqual(chosen['url'], ready['url'])
        self.assertIn('_nativeReadySummary', chosen)
        self.assertTrue(s._valid_brief(chosen['_nativeReadySummary'][2], 'australia', ready['body']))
        self.assertNotEqual(chosen['briefBody'], ready['briefBody'])
        self.assertIn('Australian', chosen['briefBody'])
        # Without inference/context mode, ordinary primary order is retained
        # when both originals have valid native summaries.
        primary = article('australia', 'primary-context', LIVE_EXPORT, alternatives=[ready])
        offline = d._prefer_native_summary_candidate(primary, d.SPECS_BY_KEY['australia'], START, END, False)
        self.assertEqual(offline['url'], primary['url'])

    def test_just_completed_enrichment_is_reused_before_model_inference(self):
        from test_current_market_passage_repairs import LIVE_EXPORT
        main = article('australia', 'main',
            'Australian beef prices are rising because export demand is strong and cattle supplies are limited. '
            'Australian cattle supplies remain tight in the domestic market.')
        ready = article('australia', 'ready', LIVE_EXPORT)

        def enrich(current, *_args, **_kwargs):
            Event().wait(.03)
            current['_candidateLinkOriginals'] = [ready]
            current['_candidateLinksSearched'] = True
            return []

        with patch.object(d, '_usmef_pair', return_value={}), \
             patch.object(d, '_find_section', side_effect=lambda spec, *_: main if spec.key == 'australia' else None), \
             patch.object(d, '_search_article', return_value=None) as search, \
             patch.object(d, '_candidate_links', side_effect=enrich), \
             patch.object(s, '_ensure_ollama_ready', return_value={'available': True}), \
             patch.object(s, '_request_json', side_effect=AssertionError('existing native original needs no model')) as model:
            result = d.collect_weekly_livestock_report_draft(REPORT)
        section = result['sections']['australia']
        self.assertEqual(section['status'], 'completed')
        self.assertEqual(section['article']['url'], ready['url'])
        self.assertEqual(section['diagnostics']['modelCalls'], 0)
        model.assert_not_called()
        self.assertFalse(any(call.args[0].key == 'australia' for call in search.call_args_list))

    def test_offline_native_statistic_still_completes_without_inference(self):
        body = HATCHERY + CHICKEN_EXPLANATION
        section, infer, api, _ = self.collect_chicken(body, available=False)
        self.assertEqual(section["status"], "completed")
        self.assertEqual(section["summary"], s._native_report_sentence("us_chicken", body))
        self.assertEqual(section["diagnostics"]["modelCalls"], 0)
        self.assertIn("249.839", section["article"]["sourceExcerpt"])
        infer.assert_not_called()
        api.assert_not_called()

    def test_non_native_context_also_receives_full_original_not_the_short_display_excerpt(self):
        body = CHICKEN_EXPLANATION + " US chicken supplies remain ample in the domestic market."
        self.assertIsNone(s._native_report_sentence("us_chicken", body))
        section, infer, api, _ = self.collect_chicken(body)
        self.assertEqual(section["status"], "completed")
        self.assertEqual(section["summary"], CHICKEN_SUMMARY)
        self.assertEqual(section["diagnostics"]["modelCalls"], 1)
        self.assertEqual(infer.call_args.args[2], body)
        self.assertEqual(api.call_count, 1)
        self.assertIn(CHICKEN_EXPLANATION, section["article"]["sourceExcerpt"])

    def test_failed_context_translation_retains_matching_statistical_evidence(self):
        body = HATCHERY + CHICKEN_EXPLANATION
        section, infer, api, _ = self.collect_chicken(body, request_effect=s.ArticleSummaryBudgetExceeded("bounded"))
        self.assertEqual(section["status"], "completed")
        self.assertEqual(section["summary"], s._native_report_sentence("us_chicken", body))
        self.assertEqual(section["diagnostics"]["modelCalls"], 1)
        self.assertEqual(infer.call_count, 1)
        self.assertEqual(api.call_count, 1)
        self.assertIn("249.839", section["article"]["sourceExcerpt"])
        self.assertNotEqual(section["article"]["sourceExcerpt"], CHICKEN_EXPLANATION)

    def test_context_only_failure_can_reuse_an_already_verified_stat_alternative(self):
        body = CHICKEN_EXPLANATION + " US chicken supplies remain ample in the domestic market."
        alternate = article("us_chicken", "stat", HATCHERY)
        section, infer, api, _ = self.collect_chicken(
            body, request_effect=s.ArticleSummaryBudgetExceeded("bounded"), alternatives=[alternate])
        self.assertEqual(section["status"], "completed")
        self.assertEqual(section["article"]["url"], alternate["url"])
        self.assertEqual(section["summary"], s._native_report_sentence("us_chicken", HATCHERY))
        self.assertEqual(section["diagnostics"]["modelCalls"], 1)
        self.assertEqual(infer.call_count, 1)
        self.assertEqual(api.call_count, 1)
        self.assertEqual(section["retryCount"], 1)
        self.assertEqual(section["article"]["publishedDate"], REPORT.isoformat())
        self.assertIn("249.839", section["article"]["sourceExcerpt"])

    def test_invalid_context_candidates_cannot_replace_a_same_week_native_source(self):
        invalid = (
            {"publishedDate": date(2026, 10, 10)},
            {"publishedDate": date(2026, 10, 18)},
            {"url": "javascript:alert(1)"},
            {"originalUrl": "javascript:alert(1)"},
            {"headlineOnly": True},
            {"searchResult": True},
            {"body": "US chicken prices fell because supplies rose."},
            {"title": "Japan chicken supply and prices", "body": CHICKEN_EXPLANATION.replace("US", "Japan") + " Japanese domestic supply remains ample."},
            {"title": "US pork supply and prices", "body": CHICKEN_EXPLANATION.replace("chicken", "pork") + " Pork supplies remain ample."},
        )
        for changes in invalid:
            with self.subTest(changes=changes):
                rich = article("us_chicken", "rich", CHICKEN_EXPLANATION + " Supplies remain ample in the domestic market.")
                rich.update(changes)
                main = article("us_chicken", "stat", HATCHERY, alternatives=[rich])
                chosen = d._prefer_native_summary_candidate(main, d.SPECS_BY_KEY["us_chicken"], START, END, True)
                self.assertEqual(chosen["url"], main["url"])
                self.assertIn("_nativeReadySummary", chosen)


if __name__ == "__main__":
    unittest.main()
