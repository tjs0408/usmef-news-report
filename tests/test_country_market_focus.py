"""Global-market articles must not replace the requested country's facts."""
import unittest

from src import overseas_article_digest as s
from src.country_market_focus import country_market_context


AUSTRALIA = (
    'The impact has been most visible in Australia, after China’s Safeguard quota '
    'for Australian beef imports was reached in mid-June.\n'
    'This saw Australian beef exports to China fall 71 percent month-over-month '
    'from May to June, with July volumes remaining similarly low.\n'
    'Much of this Australian product has been redirected to alternative destinations, '
    'with Japan, South Korea and the United States recording increases in Australian beef imports.\n'
    'Brazil was expected to hit its Chinese beef import quota in coming days, with '
    'anticipation of reduced access to China already pressuring Brazilian cattle prices lower.\n'
    'Chinese imports from New Zealand rose 66pc year-over-year, while volumes from Canada increased 104pc.\n'
    'Australia\nAustralian beef production continues at a strong pace.\n'
    'Australia’s national weekly slaughter volumes track around 150,000 to 160,000 head per week.'
)


class CountryMarketFocusTests(unittest.TestCase):
    def test_australian_trade_cause_impact_and_destinations_stay_together(self):
        focused = country_market_context('australia', AUSTRALIA)
        for fact in ('Safeguard quota', '71 percent month-over-month', 'redirected to alternative destinations'):
            self.assertIn(fact, focused)
        self.assertIn('Japan, South Korea', focused)
        self.assertNotIn('Brazil', focused)
        self.assertNotIn('104pc', focused)
        self.assertEqual(s._market_fact_excerpt(AUSTRALIA, kind='australia'), focused)
        explanation = s._explanatory_market_excerpt('australia', AUSTRALIA)
        self.assertTrue(explanation is None or 'Brazil' not in explanation)

    def test_denser_foreign_cause_cannot_outrank_us_or_brazil_target(self):
        body = ('Brazilian chicken exports increased as chicken demand rose amid supply shortages and higher prices.\n'
                'United States chicken exports fell 3% after foreign demand weakened.\n'
                'US chicken prices were stable despite the decline in export demand.')
        us = s._market_fact_excerpt(body, kind='us_chicken')
        brazil = s._market_fact_excerpt(body, kind='brazil_chicken')
        self.assertTrue('United States chicken' in us or 'US chicken' in us)
        self.assertNotIn('Brazilian', us)
        self.assertIn('Brazilian chicken', brazil)
        self.assertNotIn('United States', brazil)

    def test_local_sources_without_country_label_keep_existing_original_path(self):
        body = 'The USDA says 194.367 million broiler-type chicks went into meat production.'
        self.assertIsNone(country_market_context('us_chicken', body))
        self.assertIsNone(country_market_context('domestic_chicken', body))
        # An issuing agency is not evidence that a foreign market is the US.
        foreign = 'The USDA reports Brazilian beef production is declining due to weaker cattle supply.'
        self.assertIsNone(country_market_context('us', foreign))

    def test_next_source_correction_is_not_dropped_to_publish_an_earlier_claim(self):
        body = ('Australian beef exports fell 20% after China restricted beef imports. '
                'The bank later corrected this report: those figures were not valid.')
        self.assertIsNone(country_market_context('australia', body))
        self.assertIsNone(s._explanatory_market_excerpt('australia', body))
        self.assertIn('corrected this report', s._market_fact_excerpt(body, kind='australia'))

    def test_country_heading_can_ground_a_following_market_explanation(self):
        body = ('Australia\nAustralian cattle production remains strong.\n'
                'Cattle prices declined due to weaker export demand and higher supplies.\n'
                'Brazil\nBrazilian cattle prices rose after a decline in cattle production.')
        focused = country_market_context('australia', body)
        self.assertIn('Cattle prices declined', focused)
        self.assertNotIn('Brazil', focused)


if __name__ == '__main__':
    unittest.main()
