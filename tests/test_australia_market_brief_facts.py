"""Rain-forecast cattle retention must not inherit another sale/week's count."""
import unittest

from src.article_hwpx_layout import summary_reference_layout
from src.australia_market_brief_facts import native_australia_market_brief
from src.overseas_article_digest import _valid_brief


# Relevant complete paragraphs of Beef Central's 2026-10-19 original.
BODY = (
    'Rainfall past seven days IN what is shaping as the most influential and widespread '
    'rain event in at least eight months, more than 100mm of rain has fallen across parts '
    'of Queensland, cutting highways and reducing saleyard offerings. '
    'Further good falls have been recorded across northeastern NSW and Central Australia. '
    'The Bureau of Meteorology is forecasting the same system to hang around for the rest of the week. '
    'BOM eight-day forecast Markets volatile '
    'Cattle markets have been highly volatile in recent weeks, particularly for restocker '
    'categories as dry conditions and changing rainfall forecasts have driven sharp weekly movements in supply and demand. '
    'National cattle yardings fell 7pc last week to 54,403 head week-on-week, although the declining '
    'trend had already started the week before as the market anticipated upcoming rain. '
    'A week earlier, weekly saleyards numbers were at +63,000 head, and two weeks earlier '
    '(25 September) above 73,000 head. '
    'Despite the return to a full selling week last week following the public holiday period, '
    'forecast rainfall encouraged some producers to retain stock. '
    'All cattle indicators lifted last week, with gains of up to 11pc for the Restocker Yearling Heifer Indicator. '
    'Saleyards offerings contract Preliminary bookings for Roma show about 3500 head. '
    'Forbes numbers lifted by 600 to 2283 head. '
)


class AustraliaMarketBriefFactsTests(unittest.TestCase):
    def test_actual_source_recovers_a_valid_one_line_nominal_brief(self):
        summary, evidence = native_australia_market_brief(BODY)
        self.assertEqual(summary, '호주 강우 예보에 일부 소 농가 출하 보류, 지난주 출하두수 전주비 7% 감소')
        self.assertIn('54,403 head week-on-week', evidence)
        self.assertIn('forecast rainfall encouraged some producers to retain stock.', evidence)
        self.assertIn('Queensland', evidence)
        self.assertNotIn('63,000', evidence)
        self.assertNotIn('73,000', evidence)
        self.assertNotIn('11%', summary)
        self.assertNotIn('폭우로', summary)
        self.assertGreaterEqual(len(summary), 40)
        self.assertTrue(_valid_brief(summary, 'australia', BODY), summary)
        self.assertTrue(summary_reference_layout(summary, 'australia')['withinLineLimit'])

    def test_rate_count_direction_and_evidence_are_not_fixed_to_this_week(self):
        changed = BODY.replace('fell 7pc last week to 54,403', 'rose 3.5pc last week to 62,800')
        changed = changed.replace('the declining trend', 'the rising trend')
        summary, evidence = native_australia_market_brief(changed)
        self.assertIn('전주비 3.5% 증가', summary)
        self.assertNotIn('7%', summary)
        self.assertIn('62,800 head week-on-week', evidence)
        self.assertNotIn('54,403', evidence)

    def test_observation_forecast_or_retention_negation_cannot_be_replaced(self):
        for phrase in (
            'observed rainfall encouraged some producers to retain stock.',
            'forecast rainfall may encourage some producers to retain stock.',
            'forecast rainfall did not encourage some producers to retain stock.',
            'forecast rainfall encouraged all producers to retain stock.',
            'forecast rainfall encouraged some producers not to retain stock.',
            'forecast rainfall encouraged some producers to retain stock, according to an unconfirmed estimate.',
        ):
            with self.subTest(phrase=phrase):
                body = BODY.replace('forecast rainfall encouraged some producers to retain stock.', phrase)
                self.assertIsNone(native_australia_market_brief(body))

    def test_older_week_daily_estimate_sheep_or_regional_counts_are_not_current_cattle(self):
        for original, changed in (
            ('National cattle yardings', 'National sheep yardings'),
            ('National cattle yardings', 'Queensland cattle yardings'),
            ('National cattle yardings', 'New Zealand National cattle yardings'),
            ('fell 7pc', 'did not fall 7pc'),
            ('fell 7pc', 'are forecast to fall 7pc'),
            ('fell 7pc', 'fell 0pc'),
            ('fell 7pc', 'fell 107pc'),
            ('54,403 head', '0 head'),
            ('7pc last week', '7pc two weeks ago'),
            ('head week-on-week', 'head day-on-day'),
            ('head week-on-week', 'head year-on-year'),
            ('head week-on-week', 'head week-on-week according to an estimate'),
            ('the declining trend', 'the rising trend'),
        ):
            with self.subTest(changed=changed):
                self.assertIsNone(native_australia_market_brief(BODY.replace(original, changed)))

    def test_no_australian_geography_or_foreign_market_context_is_not_accepted(self):
        body = BODY.replace('Queensland', 'New Zealand').replace('Central Australia', 'New Zealand')
        self.assertIsNone(native_australia_market_brief(body))
        body = BODY.replace('Markets volatile ', 'Markets volatile New Zealand markets were discussed. ')
        self.assertIsNone(native_australia_market_brief(body))

    def test_repeated_or_conflicting_national_statistic_is_not_guessed(self):
        extra = 'National cattle yardings rose 8pc last week to 80,000 head week-on-week. '
        body = BODY.replace('Saleyards offerings contract', extra + 'Saleyards offerings contract')
        self.assertIsNone(native_australia_market_brief(body))

    def test_whitespace_empty_and_non_text_handling(self):
        self.assertIsNotNone(native_australia_market_brief(BODY.replace('National cattle', 'National\n cattle')))
        self.assertIsNone(native_australia_market_brief(''))
        self.assertIsNone(native_australia_market_brief(None))


if __name__ == '__main__':
    unittest.main()
