"""The USDA weekly demand metric is not a price or percentage change."""
import unittest
from unittest.mock import patch

from src import overseas_article_digest as s
from src.article_hwpx_layout import summary_reference_layout


CLAUSE = ('The Weekly Shell Egg Demand Indicator, dated October 14, 2026, '
          'stood at 2.80, down 4.7 points from the prior week.')
BODY = ('According to USDA Agricultural Marketing Service, prices in the '
        'October 9 report were lower. ' + CLAUSE +
        ' The productive table egg layer flock was reported at 311,656,981 birds. '
        'The activity index was 13,855, down 0.3 percent.')


class EggDemandIndicatorTests(unittest.TestCase):
    def tearDown(self):
        s._summarize_report_sentence.cache_clear()

    def test_dated_weekly_demand_brief_needs_no_ai_and_fits_one_line(self):
        with patch.object(s, '_ollama_generate') as model:
            summary = s._summarize_report_sentence('us_egg', 'USDA Egg Markets Overview', BODY)
        model.assert_not_called()
        self.assertEqual(summary, '미국 계란의 주간 수요지수는 전주 대비 4.7포인트 낮아진 2.80을 기록')
        self.assertGreaterEqual(len(summary), 40)
        self.assertTrue(s._valid_brief(summary, 'us_egg', BODY), summary)
        self.assertTrue(summary_reference_layout(summary, 'us_egg')['withinLineLimit'], summary)
        self.assertEqual(s._native_source_excerpt(BODY, summary), CLAUSE)
        for unrelated in ('0.3', '13,855', '311,656,981', '가격', '%'):
            self.assertNotIn(unrelated, summary)

    def test_direction_value_and_date_are_source_driven(self):
        changed = BODY.replace('October 14, 2026', 'November 18, 2027').replace(
            'at 2.80, down 4.7', 'at 5.20, up 1.3')
        summary, excerpt = s._us_shell_egg_demand_indicator_fact(changed)
        self.assertIn('1.3포인트 높아진 5.20', summary)
        self.assertIn('November 18, 2027', excerpt)
        self.assertTrue(s._valid_brief(summary, 'us_egg', changed))

    def test_two_adjacent_source_sentences_bind_the_same_named_indicator(self):
        body = ('The weekly Shell Egg Demand Indicator for shell eggs stood at 2.80 as of '
                'October 14, 2026, according to the USDA AMS MyMarketNews report. '
                'The reading was down 4.7 points from the prior week, reflecting an estimate '
                'of shell egg demand calculated from current production and the rate at '
                'which inventory is cleared.')
        summary, excerpt = s._us_shell_egg_demand_indicator_fact(body)
        self.assertIn('전주 대비 4.7포인트 낮아진 2.80', summary)
        self.assertEqual(excerpt, body)
        self.assertTrue(s._valid_brief(summary, 'us_egg', body))
        for altered in (
            body.replace('The reading was', 'A different price was'),
            body.replace('The reading was', 'The forecast reading was'),
            body.replace('The reading was', 'The reading was not'),
            body.replace('The reading was', 'Retail sales declined. The reading was'),
            body.replace('prior week', 'prior month'),
        ):
            with self.subTest(altered=altered):
                self.assertIsNone(s._us_shell_egg_demand_indicator_fact(altered))

    def test_other_metrics_periods_negations_or_units_do_not_qualify(self):
        for body in (
            BODY.replace('USDA Agricultural Marketing Service', 'A retailer'),
            BODY.replace('Shell Egg Demand Indicator', 'Grocery Store Activity Index'),
            BODY.replace('stood at', 'did not stand at'),
            BODY.replace('points from the prior week', 'percent from the prior week'),
            BODY.replace('prior week', 'prior year'),
            BODY.replace('prior week', 'next week'),
            BODY.replace('October 14', 'February 30'),
            BODY.replace('October 14', 'October 40'),
            BODY.replace('down 4.7', 'down 0'),
        ):
            with self.subTest(body=body):
                self.assertIsNone(s._us_shell_egg_demand_indicator_fact(body))

    def test_missing_value_is_not_borrowed_from_later_inventory_or_promotions(self):
        body = ('USDA: The Weekly Shell Egg Demand Indicator, dated October 14, 2026, '
                'was reported. The retail activity index stood at 2.80, down 4.7 points from the prior week.')
        self.assertIsNone(s._us_shell_egg_demand_indicator_fact(body))


if __name__ == '__main__':
    unittest.main()
