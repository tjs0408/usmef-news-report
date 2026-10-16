"""Hatchery explanation must be one typed, explicitly connected source fact."""
import unittest
from unittest.mock import patch

from src import overseas_article_digest as s
from src.article_hwpx_layout import summary_reference_layout
from test_weekly_hatchery_german_recovery import HATCHERY_EGGS


class BroilerContextSummaryTests(unittest.TestCase):
    def tearDown(self):
        s._summarize_report_sentence.cache_clear()

    def test_same_sentence_cause_both_periods_and_exact_counts_need_no_model(self):
        with patch.object(s, '_ollama_generate', side_effect=AssertionError('typed source needs no model')):
            summary = s._summarize_report_sentence('us_chicken', 'Broiler sets', HATCHERY_EGGS)
        self.assertIn('산란계 수 증가로 전년비 3% 늘었으나', summary)
        self.assertIn('전주비 21만 5000개 감소', summary)
        self.assertIn('2억 4530만 4000개', summary)
        self.assertTrue(s._valid_brief(summary, 'us_chicken', HATCHERY_EGGS))
        self.assertFalse(s._summary_needs_market_context('us_chicken', HATCHERY_EGGS, summary))
        layout = summary_reference_layout(summary, 'us_chicken')
        self.assertTrue(layout['withinLineLimit'])
        self.assertEqual(2, layout['estimatedLines'])

    def test_changed_values_and_direction_are_source_driven(self):
        changed = HATCHERY_EGGS.replace('245.304', '240.118').replace('215,000', '312,000').replace('rising 3%', 'rising 5.7%')
        summary = s._broiler_hatchery_context_summary(changed)
        self.assertIn('전년비 5.7%', summary)
        self.assertIn('31만 2000개 감소', summary)
        self.assertIn('2억 4011만 8000개', summary)
        self.assertTrue(s._valid_brief(summary, 'us_chicken', changed))
        increased = changed.replace('falling 312,000', 'rising 312,000')
        summary = s._broiler_hatchery_context_summary(increased)
        self.assertIn('전주비 31만 2000개 증가', summary)
        self.assertNotIn('늘었으나', summary)
        self.assertNotIn('  ', summary)

    def test_no_invented_cause_or_cross_sentence_period_binding(self):
        cases = (
            HATCHERY_EGGS.replace('thanks to a larger number of laying hens', ''),
            HATCHERY_EGGS.replace('thanks to', 'not thanks to'),
            HATCHERY_EGGS.replace('a larger number', 'a smaller number'),
            HATCHERY_EGGS.replace('laying hens', 'pigs'),
            HATCHERY_EGGS.replace('but rising 3%', 'but falling 3%'),
            HATCHERY_EGGS.replace('broiler-type eggs', 'turkey eggs'),
            HATCHERY_EGGS.replace('from the previous week', 'from the previous year'),
            HATCHERY_EGGS.replace('were set', 'will be set'),
            HATCHERY_EGGS.replace(', but rising', '. Other data were rising'),
        )
        for body in cases:
            with self.subTest(body=body):
                self.assertIsNone(s._broiler_hatchery_context_summary(body))


if __name__ == '__main__':
    unittest.main()
