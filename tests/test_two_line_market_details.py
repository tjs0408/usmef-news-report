"""Select a supported single market issue in one-line Australia/Brazil briefs."""
import unittest
from src import overseas_article_digest as s
from src.article_hwpx_layout import summary_reference_layout
from test_current_market_passage_repairs import LIVE_EXPORT, COMPETITION


class TwoLineMarketDetailsTests(unittest.TestCase):
    def test_live_export_costs_only_come_from_the_explicit_same_market_clause(self):
        costs = (' Those prices continue to test Indonesian importers, who face higher freight costs, '
                 'weak economic conditions, reduced buying power from a weaker rupiah and concerns about price limits.')
        body = LIVE_EXPORT + costs
        summary = s._australian_live_export_demand_summary(body)
        self.assertIn('호주 생우 수출 감소', summary)
        self.assertIn('인도네시아 구매 확대 전망', summary)
        self.assertNotIn('루피아', summary)
        self.assertIn('확대 전망', summary)
        self.assertTrue(s._valid_brief(summary, 'australia', body))
        layout = summary_reference_layout(summary, 'australia')
        self.assertTrue(layout['withinLineLimit'])
        self.assertEqual(1, layout['estimatedLines'])
        for changed in (costs.replace('higher freight', 'lower freight'),
                        costs.replace('weaker rupiah', 'stronger rupiah'),
                        costs.replace('Indonesian', 'Brazilian')):
            self.assertNotIn('루피아', s._australian_live_export_demand_summary(LIVE_EXPORT + changed))

    def test_competition_growth_keeps_source_year_period_scale_and_modality(self):
        body = COMPETITION.replace('9%.', '9% só no primeiro semestre de 2026, além das exportações no mesmo período.')
        summary = s._brazil_chicken_competition_outlook_summary(body)
        self.assertIn('2026년 상반기 닭고기 생산 9% 증가', summary)
        self.assertIn('경쟁국 부상 가능성', summary)
        self.assertNotIn('수출 감소', summary)
        self.assertTrue(s._valid_brief(summary, 'brazil_chicken', body))
        self.assertTrue(summary_reference_layout(summary, 'brazil_chicken')['withinLineLimit'])
        changed = body.replace('9%', '6,5%').replace('2026', '2025')
        summary = s._brazil_chicken_competition_outlook_summary(changed)
        self.assertIn('2025년 상반기 닭고기 생산 6.5%', summary)
        self.assertTrue(s._valid_brief(summary, 'brazil_chicken', changed))
        self.assertNotIn('상반기', s._brazil_chicken_competition_outlook_summary(COMPETITION))


if __name__ == '__main__':
    unittest.main()
