import unittest
from unittest.mock import patch

from src import overseas_article_digest as s
from src.article_hwpx_layout import summary_reference_layout
from src.us_poultry_supply_frames import native_us_poultry_supply_brief as native
from src.report_editorial_native import editorial_native_brief


EGG = ('2026 egg production continues to outpace 2025. The USDA says 9.203 billion eggs were produced '
       'in September, up 6% on the year, with a 5% increase in the average number of layers to '
       '385.065 million head and 1% rise in the rate of production per 100 layers.')
CHICKEN = ('Daily National Broiler Market-At-A-Glance Agricultural Marketing Service '
           'DOMESTIC MARKET HIGHLIGHTS WOGs are trending steady. Floor stocks are adequate. '
           'Demand is about moderate. Bone-in breasts and front halves are mixed; demand is fair to moderate. '
           'The market is overall steady. EXPORT MARKET HIGHLIGHTS Export market is moderate to active. '
           'Source: USDA AMS Atlanta, Georgia')


class UsPoultrySupplyFramesTests(unittest.TestCase):
    def test_source_frames_are_complete_without_ai_and_retain_evidence(self):
        for kind, body in (('us_egg', EGG), ('us_chicken', CHICKEN)):
            with self.subTest(kind=kind), patch.object(s, '_ollama_generate', side_effect=AssertionError('no inference')):
                summary, evidence = native(kind, body)
                self.assertTrue(s._valid_brief(summary, kind, body), s.brief_validation_reasons(summary, kind, body))
                self.assertTrue(summary_reference_layout(summary, kind)['withinLineLimit'])
                self.assertGreaterEqual(len(summary), 40)
                # The primary pipeline now prefers the same source's explicit
                # layer/rate context over a bare total when that frame fits.
                expected = editorial_native_brief(kind, body) or summary
                self.assertEqual(s._summarize_report_sentence.__wrapped__(kind, 'market report', body), expected)
                self.assertTrue(s._valid_brief(expected, kind, body))
                self.assertEqual(s._native_source_excerpt(body, summary), evidence)

    def test_egg_period_quantity_direction_are_dynamic_and_not_layer_counts(self):
        summary, _ = native('us_egg', EGG)
        self.assertIn('9월 계란 생산량', summary)
        self.assertIn('전년 동월보다 6% 증가', summary)
        self.assertIn('92억 300만개', summary)
        self.assertNotIn('385', summary)
        changed, _ = native('us_egg', EGG.replace('9.203 billion', '8.125 billion').replace('September', 'August')
                            .replace('up 6%', 'down 3%'))
        self.assertIn('8월', changed)
        self.assertIn('81억 2500만개', changed)
        self.assertIn('3% 감소', changed)

    def test_egg_does_not_infer_country_period_quantity_or_observed_production(self):
        for body in (EGG.replace('says 9.203', 'says approximately 9.203'),
                     EGG.replace('eggs were produced', 'eggs might be produced'),
                     EGG.replace('eggs were produced', 'chicks were produced'),
                     EGG.replace('in September', 'in Canada during September'),
                     EGG.replace('on the year', 'on the month'),
                     EGG + ' This report was corrected as incorrect.',
                     EGG.replace('9.203 billion', '0 billion')):
            with self.subTest(body=body):
                self.assertIsNone(native('us_egg', body))

    def test_broiler_cannot_inherit_export_outlook_or_foreign_market(self):
        for body in (CHICKEN.replace('WOGs are trending steady.', 'WOGs are not trending steady.'),
                     CHICKEN.replace('Demand is about moderate.', 'Demand is weak.'),
                     CHICKEN.replace('Floor stocks are adequate.', 'Floor stocks are expected to be adequate.'),
                     CHICKEN.replace('Atlanta, Georgia', 'Toronto, Canada'),
                     CHICKEN.replace('Export market is moderate to active.', 'Export market is expected to be moderate to active.')):
            with self.subTest(body=body):
                self.assertIsNone(native('us_chicken', body))

    def test_other_cuts_weak_demand_does_not_negate_the_overall_market(self):
        body = CHICKEN.replace('The market is overall steady.',
            'Tenders and wings are not getting much attention rating barely steady. The market is overall steady.')
        self.assertIsNotNone(native('us_chicken', body))
        excerpt = s._market_fact_excerpt(body, kind='us_chicken')
        self.assertNotIn('Agricultural Marketing Service', excerpt)
        self.assertIn('EXPORT MARKET HIGHLIGHTS', excerpt)


if __name__ == '__main__':
    unittest.main()
