"""A mixed red-meat/poultry forecast must keep its broiler direction."""
import unittest
from unittest.mock import patch

from src import overseas_article_digest as digest
from src.article_hwpx_layout import summary_reference_layout


BROWNFIELD_FORECAST = (
    "USDA has trimmed its 2026 red meat production projections while increasing "
    "expectations for poultry. "
    "Broiler production is pegged at 49.72 billion pounds, 100 million higher "
    "based on slaughter, hatchery, and weight data, with an average price of "
    "$1.189 per pound, a gain of a tenth of a cent, and minimal supply and "
    "demand adjustments."
)


class BrownfieldBroilerForecastTests(unittest.TestCase):
    def tearDown(self):
        digest._summarize_report_sentence.cache_clear()

    def test_native_summary_uses_broiler_revision_and_shows_both_source_sentences(self):
        with patch.object(digest, "_ollama_generate") as model:
            summary = digest._summarize_report_sentence(
                "us_chicken", "Red meat production expected to fall, poultry to rise",
                BROWNFIELD_FORECAST,
            )
        model.assert_not_called()
        self.assertIn("2026년 육계 생산 전망치", summary)
        self.assertIn("497억 2000만 파운드", summary)
        self.assertTrue(summary.endswith("상향"), summary)
        self.assertNotIn("하향", summary)
        self.assertTrue(40 <= len(summary) <= digest.SUMMARY_LIMITS["us_chicken"])
        self.assertTrue(summary_reference_layout(summary, "us_chicken")["withinLineLimit"])
        self.assertTrue(digest._valid_brief(summary, "us_chicken", BROWNFIELD_FORECAST))
        evidence = digest._native_source_excerpt(BROWNFIELD_FORECAST, summary)
        self.assertIn("2026 red meat", evidence)
        self.assertIn("Broiler production", evidence)

    def test_rejects_red_meat_cut_or_supply_expansion_attached_to_chicken(self):
        bad = "미국 USDA는 2026년 닭고기 생산 예상치를 줄이고, 닭고기 수급 확대를 예상"
        lead_only = BROWNFIELD_FORECAST.split(". ", 1)[0] + "."
        for source in (BROWNFIELD_FORECAST, lead_only):
            with self.subTest(source=source):
                self.assertFalse(digest._valid_brief(bad, "us_chicken", source))
        self.assertFalse(digest._brief_content_supported(
            "미국 USDA는 2026년 닭고기 생산 전망치를 상향",
            "us_chicken", lead_only,
        ))
        self.assertFalse(digest._brief_content_supported(
            "미국 USDA는 2026년 육계 생산 전망치를 하향", "us_chicken", BROWNFIELD_FORECAST,
        ))
        self.assertFalse(digest._brief_content_supported(
            "미국 USDA는 닭고기 수급 확대를 예상", "us_chicken", BROWNFIELD_FORECAST,
        ))

    def test_year_quantity_and_direction_follow_changed_source(self):
        changed = (BROWNFIELD_FORECAST.replace("2026", "2027")
                   .replace("49.72", "48.19").replace("higher", "lower"))
        summary = digest._native_report_sentence("us_chicken", changed)
        self.assertIn("2027년", summary)
        self.assertIn("481억 9000만 파운드", summary)
        self.assertTrue(summary.endswith("하향"), summary)
        self.assertNotIn("2026", summary)
        self.assertNotIn("497억", summary)
        self.assertTrue(digest._valid_brief(summary, "us_chicken", changed))
        self.assertTrue(summary_reference_layout(summary, "us_chicken")["withinLineLimit"])


if __name__ == "__main__":
    unittest.main()
