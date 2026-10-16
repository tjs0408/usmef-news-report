"""Prefer same-source market explanations without losing safe stat fallbacks."""
import unittest
from unittest.mock import patch

from src import overseas_article_digest as s
from src.article_cancellation import ArticleDraftCancelled


PRODUCTION = (
    "지난주 소고기 생산량은 전주 및 전년 대비 각각 8.4%와 12.5% 감소한 "
    "4억 3010만 파운드를 기록했다. "
)
BEEF_EXPLANATION = (
    "미국 소고기 시장은 이민 단속 강화에 따른 가공업체 근로자 결근 증가로 "
    "운송 및 도축 일정에 차질이 발생할 수 있다는 우려가 제기됐다."
)
HATCHERY = (
    "The USDA says 249.839 million broiler-type eggs were set into incubation, "
    "up 2.535 million on the week. "
)
CHICKEN_EXPLANATION = (
    "US chicken prices are under pressure because supplies are ample and "
    "foodservice demand has weakened."
)
CHICKEN_SUMMARY = (
    "미국 닭고기는 공급이 충분한 가운데 외식업체 수요 약화에 따른 가격 하락 압박"
)


class ExplanatoryMarketSummaryTests(unittest.TestCase):
    def setUp(self):
        s._summarize_report_sentence.cache_clear()

    def test_korean_explanatory_issue_precedes_weekly_production_stat_without_model(self):
        body = PRODUCTION + BEEF_EXPLANATION
        with patch.object(s, "_ollama_generate", side_effect=AssertionError("native Korean source needs no model")):
            summary = s._summarize_report_sentence("us", "USMEF 소고기 시장동향", body)
        self.assertIn("이민 단속", summary)
        self.assertIn("차질", summary)
        self.assertNotIn("8.4%", summary)
        self.assertTrue(s._valid_brief(summary, "us", body))

    def test_foreign_explanatory_excerpt_is_not_replaced_by_larger_hatchery_numbers(self):
        body = HATCHERY + CHICKEN_EXPLANATION
        self.assertEqual(s._market_fact_excerpt(body, kind="us_chicken"), CHICKEN_EXPLANATION)
        native = s._native_report_sentence("us_chicken", body)
        self.assertIsNotNone(native)
        self.assertTrue(s._summary_needs_market_context("us_chicken", body, native))
        with patch.object(s, "_ollama_generate", return_value={"response": CHICKEN_SUMMARY}) as generate:
            summary = s._summarize_report_sentence("us_chicken", "US chicken prices", body)
        self.assertEqual(summary, CHICKEN_SUMMARY)
        generate.assert_called_once()
        prompt = generate.call_args.args[0]
        self.assertIn(CHICKEN_EXPLANATION, prompt)
        self.assertNotIn("249839000", prompt)
        self.assertNotIn("2535000", prompt)

    def test_stat_only_source_still_needs_no_model_and_does_not_gain_invented_cause(self):
        with patch.object(s, "_ollama_generate", side_effect=AssertionError("stat fallback is model-free")):
            summary = s._summarize_report_sentence("us_chicken", "US broiler sets", HATCHERY)
        self.assertIn("2억 4983만 9000개", summary)
        self.assertFalse(s._summary_needs_market_context("us_chicken", HATCHERY, summary))
        self.assertNotIn("수요", summary)
        self.assertNotIn("가격", summary)

    def test_failed_translation_keeps_grounded_statistic_without_another_model_budget(self):
        body = HATCHERY + CHICKEN_EXPLANATION
        expected = s._native_report_sentence("us_chicken", body)
        with patch.object(s, "_extract_report_facts", side_effect=s.ArticleSummaryBudgetExceeded("bounded")) as extract:
            actual = s._summarize_report_sentence("us_chicken", "US chicken prices", body)
        self.assertEqual(actual, expected)
        extract.assert_called_once()
        self.assertTrue(s._valid_brief(actual, "us_chicken", body))

    def test_cancellation_is_not_converted_to_a_statistic(self):
        body = HATCHERY + CHICKEN_EXPLANATION
        with patch.object(s, "_extract_report_facts", side_effect=ArticleDraftCancelled("cancelled")):
            with self.assertRaises(ArticleDraftCancelled):
                s._summarize_report_sentence("us_chicken", "US chicken prices", body)

    def test_other_species_and_unlinked_stats_do_not_qualify_as_explanations(self):
        sources = (
            HATCHERY + "US pork prices fell because supplies are ample and demand is weak.",
            HATCHERY + "US chicken production rose 5% and market prices were published in the table.",
            "US chicken and pork prices fell because supplies are ample and demand is weak.",
        )
        for body in sources:
            with self.subTest(body=body):
                self.assertIsNone(s._explanatory_market_excerpt("us_chicken", body))
        self.assertIsNone(s._explanatory_market_excerpt("us_pork", BEEF_EXPLANATION))
        self.assertIsNone(s._explanatory_market_excerpt("domestic_chicken", CHICKEN_EXPLANATION))

    def test_four_local_slots_use_their_language_and_preserve_literal_conditions(self):
        examples = (
            ("us", BEEF_EXPLANATION),
            ("australia", "Australian beef prices are rising because export demand is strong and cattle supplies are limited."),
            ("us_chicken", CHICKEN_EXPLANATION),
            ("brazil_chicken", "Os preços do frango no Brasil subiram devido à recuperação da demanda interna e à oferta limitada."),
        )
        for kind, body in examples:
            with self.subTest(kind=kind):
                self.assertEqual(s._explanatory_market_excerpt(kind, body), body)

    def test_substantive_native_market_summary_does_not_trigger_an_extra_inference(self):
        summary = "미국 닭고기 수요는 보통~양호하고 재고는 적정 수준을 유지하는 가운데 시장 흐름은 안정세"
        self.assertFalse(s._summary_needs_market_context("us_chicken", CHICKEN_EXPLANATION, summary))

    def test_concern_nominalization_preserves_modality_and_never_removes_denial(self):
        native = s._normalize_report_sentence(BEEF_EXPLANATION, "us")
        self.assertTrue(native.endswith("우려"))
        self.assertIn("발생할 수 있다는", native)
        self.assertTrue(s._valid_brief(native, "us", BEEF_EXPLANATION))
        denied = BEEF_EXPLANATION.replace("우려가 제기됐다", "우려가 제기되지 않았다고 부인했다")
        normalized = s._normalize_report_sentence(denied, "us")
        self.assertIn("제기되지 않았다고 부인했다", normalized)
        self.assertFalse(s._valid_brief(normalized, "us", denied))

    def test_two_line_prompt_uses_context_budget_but_single_line_rules_stay_short(self):
        for kind in ("us", "us_chicken"):
            self.assertIn("65~85자", s._brief_model_rules(kind))
        for kind in ("australia", "brazil_chicken", "us_pork", "eu_pork", "domestic_chicken", "domestic_egg"):
            self.assertIn("40~45자", s._brief_model_rules(kind))


if __name__ == "__main__":
    unittest.main()
