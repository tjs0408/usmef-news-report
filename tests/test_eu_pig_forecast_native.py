"""A Commission forecast cannot become an observed or different-species decline."""
import unittest
from unittest.mock import patch

from src import overseas_article_digest as s
from src.article_hwpx_layout import summary_reference_layout
from src.report_brief_style import MAX_ARTICLE_TRACKING


FORECAST = (
    "The European Commission has also forecast lower pig slaughter volumes "
    "in the EU during the second half of 2026 compared with the same period "
    "of the previous year."
)
BODY = (
    "Following the difficult price period experienced across the EU this summer, "
    "many market analysts expect pig numbers to decline more significantly in "
    "the autumn census. " + FORECAST
)


class EUPigForecastNativeTests(unittest.TestCase):
    def tearDown(self):
        s._summarize_report_sentence.cache_clear()

    def test_complete_forecast_is_valid_one_line_without_a_model(self):
        with patch.object(s, "_ollama_generate") as model:
            summary = s._summarize_report_sentence(
                "eu_pork", "EU pig herd declines as sow numbers remain stable", BODY,
            )
        model.assert_not_called()
        self.assertEqual(summary, "유럽집행위원회, 2026년 하반기 EU 돼지 도축량은 전년 동기보다 감소 전망")
        self.assertGreaterEqual(len(summary), 40)
        self.assertTrue(s._valid_brief(summary, "eu_pork", BODY))
        layout = summary_reference_layout(summary, "eu_pork")
        self.assertTrue(layout["withinLineLimit"])
        self.assertGreaterEqual(layout["tracking"], MAX_ARTICLE_TRACKING)

    def test_year_is_captured_from_the_source(self):
        changed = FORECAST.replace("2026", "2028")
        summary = s._native_report_sentence("eu_pork", changed)
        self.assertIn("2028년 하반기", summary)
        self.assertNotIn("2026", summary)
        self.assertTrue(s._valid_brief(summary, "eu_pork", changed))

    def test_forecast_needs_species_period_direction_and_annual_comparison(self):
        for body in (
            FORECAST.replace("has also forecast", "has not forecast"),
            FORECAST.replace("has also forecast", "has observed"),
            FORECAST.replace("lower pig", "higher pig"),
            FORECAST.replace("pig slaughter", "chicken slaughter"),
            FORECAST.replace("slaughter volumes", "herd numbers"),
            FORECAST.replace("second half", "first half"),
            FORECAST.replace("in the EU", "in Brazil"),
            FORECAST.replace("the same period of the previous year", "the previous month"),
            FORECAST.replace(" of 2026", ""),
            "EU pig slaughter decline forecast for 2026",
        ):
            with self.subTest(body=body):
                self.assertIsNone(s._eu_pig_slaughter_forecast_summary(body))

    def test_autumn_herd_decline_alone_is_not_a_slaughter_forecast(self):
        body = BODY.removesuffix(FORECAST)
        self.assertIsNone(s._eu_pig_slaughter_forecast_summary(body))
        self.assertIsNone(s._native_report_sentence("eu_pork", body))

    def test_ordinary_spacing_and_optional_also_preserve_forecast(self):
        changed = FORECAST.replace("also ", "").replace("second half", "second\nhalf")
        self.assertEqual(s._eu_pig_slaughter_forecast_summary(FORECAST),
                         s._eu_pig_slaughter_forecast_summary(changed))


if __name__ == "__main__":
    unittest.main()
