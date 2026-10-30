"""10/19 USDA wording is summarized without retrying a language model."""
import unittest

from src.article_hwpx_layout import summary_reference_layout
from src.overseas_article_digest import _valid_brief
from src.usda_brief_facts import native_usda_brief


# Transcribed from the dated public USDA AMS reports retrieved 2026-10-20.
BROILER = (
    'Daily National Broiler Market-At-A-Glance Agricultural Marketing Service '
    'Oct 19, 2026 Reported for Oct 19, 2026 DOMESTIC MARKET HIGHLIGHTS '
    'WOGs are trending steady to start the week. '
    'Floor stocks are adequate for the moderate demand. '
    'Bone-in breasts and front halves at least steady. B/S breasts are trending weak. '
    'Tenders and wings remain fair with a weak undertone. '
    'Dark meat supplies continue to clear very well. The market is steady to firm. '
    'EXPORT MARKET HIGHLIGHTS Export market is moderate to active. '
    'Source: USDA AMS Livestock, Poultry, and Grain Market News'
)
EGG = (
    'Daily National Shell Egg Index Report (5-day rolling average) '
    'Agricultural Marketing Service Mon Oct 19, 2026 Report for: 10/19/2026 '
    'National FOB shell egg weighted average prices are mostly steady on light test. '
    'Higher values are noted into export channels for Medium. The undertone is steady to weak. '
    'Demand ranges light to occasionally fairly good, best where limited feature activity is planned. '
    'Offerings are moderate to instances available. Supplies remain moderate to fully adequate. '
    'Market activity is slow to at times moderate. '
    'California weighted average delivered prices are lightly tested. '
    'The undertone is steady to barely steady. Demand is reported as light to moderate. '
    'Distributive buying interest is light and as needed only. '
    'Offerings are moderate to instances available. Supplies are moderate. '
    'Market activity is slow to moderate. NEGOTIATED REGIONAL VOLUME MOVEMENT '
    'NATIONAL SHELL EGGS - Caged Cents Per Dozen FOB White Large 28.69 -0.42 '
    'Source: USDA AMS Livestock, Poultry & Grain Market News'
)


class UsdaCurrentFactsTests(unittest.TestCase):
    def test_current_broiler_uses_only_complete_domestic_sentences(self):
        summary, evidence = native_usda_brief('us_chicken', BROILER)
        self.assertIn('통닭 시장은 주 초 보합', summary)
        self.assertIn('재고는 보통 수요에 적정 수준', summary)
        self.assertIn('전체 시장은 보합~강세', summary)
        self.assertIn('The market is steady to firm.', evidence)
        self.assertNotIn('Export', evidence)
        self.assertNotIn('수출', summary)
        self.assertNotIn('주간비', summary)
        self.assertGreaterEqual(len(summary), 40)
        self.assertLessEqual(len(summary), 95)
        self.assertTrue(_valid_brief(summary, 'us_chicken', BROILER), summary)
        self.assertTrue(summary_reference_layout(summary, 'us_chicken')['withinLineLimit'])

    def test_current_egg_keeps_hedges_test_and_supply_range(self):
        summary, evidence = native_usda_brief('us_egg', EGG)
        self.assertIn('전국 FOB 가중평균가 대체로 보합(거래 제한)', summary)
        self.assertIn('공급 보통~충분 수준', summary)
        self.assertIn('Supplies remain moderate to fully adequate.', evidence)
        self.assertNotIn('Medium', evidence)
        self.assertNotIn('California', evidence)
        self.assertNotIn('상승', summary)
        self.assertNotIn('28.69', summary)
        self.assertNotIn('전일비', summary)
        self.assertNotIn('전주비', summary)
        self.assertGreaterEqual(len(summary), 40)
        self.assertLessEqual(len(summary), 95)
        self.assertTrue(_valid_brief(summary, 'us_egg', EGG), summary)
        self.assertTrue(summary_reference_layout(summary, 'us_egg')['withinLineLimit'])

    def test_broiler_movement_and_demand_are_source_driven(self):
        body = BROILER.replace('trending steady to start', 'trending lower to start')
        body = body.replace('moderate demand', 'light demand').replace('market is steady to firm.', 'market is steady to weak.')
        summary, _ = native_usda_brief('us_chicken', body)
        self.assertIn('주 초 하락', summary)
        self.assertIn('약한 수요', summary)
        self.assertIn('전체 시장은 보합~약세', summary)
        self.assertNotIn('강세', summary)

    def test_egg_direction_and_independent_supply_qualifier_are_dynamic(self):
        body = EGG.replace('mostly steady on light test', 'about lower on light test')
        body = body.replace('Supplies remain moderate', 'Supplies are generally moderate')
        summary, _ = native_usda_brief('us_egg', body)
        self.assertIn('대체로 하락(거래 제한)', summary)
        self.assertIn('공급 대체로 보통~충분 수준', summary)
        self.assertNotIn('상승', summary)

    def test_broiler_does_not_infer_estimates_comparison_periods_or_negation(self):
        mutations = (
            ('WOGs are trending steady', 'WOGs are not trending steady'),
            ('WOGs are trending steady', 'WOGs are expected to trend steady'),
            ('to start the week.', 'from the prior week.'),
            ('to start the week.', 'from the previous day.'),
            ('Floor stocks are adequate', 'Floor stocks are not adequate'),
            ('Floor stocks are adequate', 'Floor stocks are expected to be adequate'),
            ('The market is steady to firm.', 'The market is not steady to firm.'),
            ('The market is steady to firm.', 'The market is estimated steady to firm.'),
            ('The market is steady to firm.', 'The market is steady to firm, up 3%.'),
        )
        for original, changed in mutations:
            with self.subTest(changed=changed):
                self.assertIsNone(native_usda_brief('us_chicken', BROILER.replace(original, changed)))

    def test_broiler_no_region_export_or_conflicting_statement_leakage(self):
        for body in (
            BROILER.replace('DOMESTIC MARKET HIGHLIGHTS', 'EXPORT MARKET HIGHLIGHTS'),
            BROILER.replace('Floor stocks are adequate', 'California Floor stocks are adequate'),
            BROILER.replace('The market is steady to firm.', 'EXPORT MARKET HIGHLIGHTS The market is steady to firm.'),
            BROILER.replace('The market is steady to firm.', 'The market is steady to firm. The market is weak.'),
            BROILER.replace('Floor stocks are adequate', 'Floor stocks are adequate for yesterday. Floor stocks are adequate'),
        ):
            with self.subTest(body=body):
                self.assertIsNone(native_usda_brief('us_chicken', body))

    def test_egg_no_region_export_or_conflicting_supply_borrowing(self):
        for replacement in (
            'Supplies are not moderate to fully adequate.',
            'Supplies are expected to remain moderate to fully adequate.',
            'Supplies remain moderate to fully adequate in California.',
            'California supplies remain moderate to fully adequate.',
            'Export supplies remain moderate to fully adequate.',
            'Supplies remain moderate to fully adequate from the previous week.',
            'Supplies remain moderate to fully adequate, down 3% from yesterday.',
            'Supplies remain moderate to fully adequate. Supplies are light.',
            'Supplies remain moderate to fully adequate. Supplies are moderate.',
            'Offerings remain moderate to fully adequate.',
            'NATIONAL SHELL EGGS - Caged Supplies remain moderate to fully adequate.',
        ):
            with self.subTest(replacement=replacement):
                self.assertIsNone(native_usda_brief('us_egg', EGG.replace('Supplies remain moderate to fully adequate.', replacement)))

    def test_egg_no_estimated_or_negated_or_wrong_period_price(self):
        for phrase in (
            'not mostly steady on light test', 'expected to be mostly steady on light test',
            'mostly steady on light test compared with the prior week',
            'mostly steady on light test compared with the prior day',
            'mostly steady on light test, up 3%', 'mostly steady on heavy test',
        ):
            with self.subTest(phrase=phrase):
                self.assertIsNone(native_usda_brief('us_egg', EGG.replace('mostly steady on light test', phrase)))

    def test_exact_evidence_normalizes_pdf_whitespace_only(self):
        body = BROILER.replace('Floor stocks are adequate', 'Floor\n  stocks are adequate')
        self.assertIsNotNone(native_usda_brief('us_chicken', body))
        self.assertIsNotNone(native_usda_brief('us_egg', EGG.replace('prices are mostly', 'prices\n are  mostly')))

    def test_unhandled_sections_and_empty_body_fail_closed(self):
        for kind, body in (('us', BROILER), ('us_pork', EGG), ('us_egg', ''), ('us_chicken', None)):
            with self.subTest(kind=kind, body=body):
                self.assertIsNone(native_usda_brief(kind, body))


if __name__ == '__main__':
    unittest.main()
