"""Typed foreign per-egg purchase/landed costs, not political claim summaries."""

import unittest
from unittest.mock import patch

from src import overseas_article_digest as s
from src.article_hwpx_layout import summary_reference_layout


LANDED = (
    "정부는 브라질 현지에서 계란을 개당 178원에 구입했지만, "
    "항공운임과 관세 등을 포함한 총수입단가가 1천464원으로 늘면서 "
    "'세금 낭비' 논란이 불거졌습니다."
)


class EggLandedCostTests(unittest.TestCase):
    def test_verified_unit_prices_and_cost_inclusion_complete_without_model(self):
        with patch.object(s, "_ollama_generate") as model:
            summary = s._summarize_report_sentence.__wrapped__("domestic_egg", "title", LANDED)
        model.assert_not_called()
        self.assertEqual(summary, "브라질 계란 개당 구입가 178원, 항공운임·관세 포함 총수입단가 1464원 수준")
        self.assertTrue(s._valid_brief(summary, "domestic_egg", LANDED))
        self.assertGreaterEqual(len(summary), 40)
        self.assertLessEqual(len(summary), 80)
        layout = summary_reference_layout(summary, "domestic_egg")
        self.assertTrue(layout["oneLine"])
        self.assertEqual(layout["tracking"], 0)
        self.assertEqual(s._native_source_excerpt(LANDED, summary), LANDED)
        for opinion in ("낭비", "허위", "혈세", "특혜", "논란"):
            self.assertNotIn(opinion, summary)

    def test_country_and_thousands_are_dynamic_exact_prices(self):
        changed = LANDED.replace("브라질", "태국").replace("178원", "219원").replace("1천464원", "2천157원")
        summary = s._native_report_sentence("domestic_egg", changed)
        self.assertIn("태국 계란", summary)
        self.assertIn("219원", summary)
        self.assertIn("2157원", summary)
        self.assertNotIn("브라질", summary)
        self.assertNotIn("1464", summary)
        self.assertTrue(s._valid_brief(summary, "domestic_egg", changed))
        for rendered in ("1464", "1,464", "1천 464"):
            body = LANDED.replace("1천464", rendered)
            self.assertIn("1464원", s._korean_egg_landed_unit_cost_summary(body))
        decimal = LANDED.replace("178원", "178.5원").replace("1천464원", "1464.25원")
        self.assertIn("178.5원", s._korean_egg_landed_unit_cost_summary(decimal))
        self.assertIn("1464.25원", s._korean_egg_landed_unit_cost_summary(decimal))

    def test_unstated_origins_units_costs_and_opposite_direction_are_rejected(self):
        invalid = (
            LANDED.replace("브라질 현지", "현지"),
            LANDED.replace("브라질 현지", "한국 현지"),
            LANDED.replace("계란", "닭고기"),
            LANDED.replace("개당", "kg당"),
            LANDED.replace("개당", "판당"),
            LANDED.replace("개당 ", ""),
            LANDED.replace("178원", "약 178원"),
            LANDED.replace("178원", "178달러"),
            LANDED.replace("1천464원", "1천464달러"),
            LANDED.replace("1천464원", "1만464원"),
            LANDED.replace("1천464원", "1천1464원"),
            LANDED.replace("1천464원", "178원"),
            LANDED.replace("1천464원", "146원"),
            LANDED.replace("항공운임과 관세", "사료비와 관세"),
            LANDED.replace("항공운임과 관세", "항공운임"),
            LANDED.replace("포함한", "제외한"),
            LANDED.replace("총수입단가", "총수입비용"),
            LANDED.replace("총수입단가가", "미국산 계란의 총수입단가가"),
            LANDED.replace("늘면서", "줄면서"),
            LANDED.replace("늘면서", "늘지 않으면서"),
            LANDED.replace("불거졌습니다.", "불거졌다는 내용은 사실이 아니라고 정정했습니다."),
        )
        for body in invalid:
            with self.subTest(body=body):
                self.assertIsNone(s._korean_egg_landed_unit_cost_summary(body))

    def test_price_and_costs_cannot_be_joined_across_clauses_or_articles(self):
        for body in (
            LANDED.replace("구입했지만, 항공운임", "구입했다. 항공운임"),
            LANDED.replace("구입했지만, 항공운임", "구입했지만, 닭고기의 항공운임"),
            LANDED.replace("구입했지만, 항공운임", "구입했지만, 미국산 계란의 항공운임"),
            "정부는 브라질 현지에서 계란을 개당 178원에 구입했다. "
            "미국산 계란은 항공운임과 관세 등을 포함한 총수입단가가 1천464원으로 늘면서 논란이 됐다.",
        ):
            with self.subTest(body=body):
                self.assertIsNone(s._korean_egg_landed_unit_cost_summary(body))
        self.assertIsNone(s._grounded_market_statistic("domestic_pork", LANDED))
        self.assertIsNone(s._grounded_market_statistic("domestic_chicken", LANDED))


if __name__ == "__main__":
    unittest.main()
