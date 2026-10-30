"""USDA's qualified national prices and adequate supply ranges stay scoped."""
import unittest
from unittest.mock import patch

from src import overseas_article_digest as s
from src.article_hwpx_layout import summary_reference_layout


NATIONAL_BLOCK = (
    'National FOB shell egg weighted average prices are about steady to lower. '
    'The undertone is steady to weak. Demand is generally reported as light to moderate, '
    'occasionally fairly good into retail channels where limited feature activity is planned. '
    'Offerings are moderate to instances available. Supplies are moderate to fully adequate. '
    'Market activity is slow to moderate. '
    'California weighted average delivered prices are lightly tested. '
    'The undertone is steady to barely steady. Demand remains light to moderate at best. '
    'Distributive buying interest is light. Offerings are moderate to at times available. '
    'Supplies are moderate. Market activity is slow to moderate.'
)


class NationalEggHedgedSupplyTests(unittest.TestCase):
    def tearDown(self):
        s._summarize_report_sentence.cache_clear()

    def test_real_failed_national_block_recovers_without_ai(self):
        with patch.object(s, '_ollama_generate') as model:
            summary = s._summarize_report_sentence('us_egg', 'Daily National Shell Egg Index Report', NATIONAL_BLOCK)
        model.assert_not_called()
        self.assertIn('가격은 대체로 보합~하락', summary)
        self.assertIn('공급은 보통~충분 수준', summary)
        self.assertGreaterEqual(len(summary), 40)
        self.assertTrue(s._valid_brief(summary, 'us_egg', NATIONAL_BLOCK), summary)
        self.assertTrue(summary_reference_layout(summary, 'us_egg')['withinLineLimit'], summary)

    def test_price_and_supply_qualifiers_are_independent(self):
        for movement, translation in (
            ('steady to lower', '보합~하락'), ('steady to higher', '보합~상승'),
            ('steady', '보합'), ('higher', '상승'), ('lower', '하락'),
        ):
            for about in ('', 'about '):
                for qualified in ('', 'generally ', 'mostly '):
                    with self.subTest(movement=movement, about=about, qualified=qualified):
                        body = (f'National FOB shell egg weighted average prices are {about}{movement}. '
                                f'Supplies are {qualified}moderate to fully adequate.')
                        summary = s._national_shell_egg_market_summary(body)
                        if about and qualified:
                            self.assertIn(f'가중평균가격 대략 {translation},', summary)
                            self.assertIn('공급 대체로 보통~충분 수준', summary)
                        else:
                            self.assertIn(f"가격은 {'대체로 ' if about else ''}{translation}", summary)
                            self.assertIn(f"공급은 {'대체로 ' if qualified else ''}보통~충분 수준", summary)
                        self.assertTrue(s._valid_brief(summary, 'us_egg', body), summary)
                        self.assertTrue(summary_reference_layout(summary, 'us_egg')['withinLineLimit'], summary)

    def test_range_is_not_flattened_or_borrowed_from_a_region(self):
        price = 'National FOB shell egg weighted average prices are about steady to lower. '
        for supply in (
            'Supplies are not moderate to fully adequate.',
            'Supplies are moderate to fully adequate in California.',
            'Supplies are light. California supplies are moderate to fully adequate.',
            '\n\nSupplies are moderate to fully adequate.',
            'California weighted average delivered prices are steady. Supplies are moderate to fully adequate.',
            'Offerings are moderate to fully adequate.',
            'Supplies are moderate to fully adequate. Supplies are light.',
            'Supplies are moderate to fully adequate. Supplies are moderate.',
            'Supplies are fully adequate to heavy.',
        ):
            with self.subTest(supply=supply):
                self.assertIsNone(s._national_shell_egg_market_summary(price + supply))

    def test_about_qualifier_also_fits_plain_moderate_supply(self):
        for movement in ('steady to lower', 'steady to higher', 'steady', 'lower', 'higher'):
            for qualifier in ('', 'mostly ', 'generally ', 'largely '):
                body = (f'National FOB shell egg weighted average prices are about {movement}. '
                        f'Supplies are {qualifier}moderate.')
                with self.subTest(movement=movement, qualifier=qualifier):
                    summary = s._national_shell_egg_market_summary(body)
                    self.assertGreaterEqual(len(summary), 40)
                    self.assertTrue(s._valid_brief(summary, 'us_egg', body), summary)
                    self.assertTrue(summary_reference_layout(summary, 'us_egg')['withinLineLimit'], summary)
                    self.assertIn('대략' if qualifier else '대체로', summary)
                    self.assertIn('보통 수준', summary)
                    self.assertNotIn('충분', summary)

    def test_price_negation_and_unrecognized_qualifiers_are_not_accepted(self):
        for movement in ('not about steady to lower', 'not lower', 'about not lower', 'reportedly lower'):
            with self.subTest(movement=movement):
                body = f'National FOB shell egg weighted average prices are {movement}. Supplies are moderate to fully adequate.'
                self.assertIsNone(s._national_shell_egg_market_summary(body))

    def test_actual_direction_is_not_fixed_to_the_failed_weeks_wording(self):
        body = NATIONAL_BLOCK.replace('about steady to lower.', 'about steady to higher.')
        summary = s._national_shell_egg_market_summary(body)
        self.assertIn('대체로 보합~상승', summary)
        self.assertNotIn('보합~하락', summary)
        self.assertIn('보통~충분 수준', summary)


if __name__ == '__main__':
    unittest.main()
