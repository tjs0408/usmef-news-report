"""Public original clause variants must not trigger two failing AI retries."""
import unittest
from unittest.mock import patch

from src import overseas_article_digest as s
from src.article_hwpx_layout import summary_reference_layout


# Original public market-release clauses, retrieved 2026-10-15 from:
# https://www.lwk-rlp.de/markt-statistik/marktbericht/marktbericht/schlachtschweine
GERMAN_MARKET = (
    "Das Angebot am Schlachtschweinemarkt weitet sich saisontypisch weiter aus, "
    "steigenden Schlachtgewichte tragen hierzu bei. Die Nachfrage am Fleischmarkt "
    "bleibt dagegen verhalten, es baut sich Angebotsdruck auf. Für die laufende "
    "Woche wird von stabilen Preisen ausgegangen."
)
# https://brownfieldagnews.com/news/broilers-see-continued-push-from-demand-expectations/
HATCHERY_PLACEMENTS = (
    "The USDA says 190.295 million broiler-type chicks were placed into meat "
    "production, up 1.115 million on the week and 1% higher on the year."
)
HATCHERY_EGGS = (
    "245.304 million broiler-type eggs were set into incubators last week, "
    "falling 215,000 from the previous week, but rising 3% from a year ago "
    "thanks to a larger number of laying hens."
)


class WeeklyHatcheryGermanRecoveryTests(unittest.TestCase):
    def tearDown(self):
        s._summarize_report_sentence.cache_clear()

    def test_both_failed_sections_complete_natively_without_ai(self):
        for kind, body in (('eu_pork', GERMAN_MARKET),
                           ('us_chicken', HATCHERY_PLACEMENTS + ' ' + HATCHERY_EGGS)):
            with self.subTest(kind=kind), patch.object(s, '_ollama_generate') as model:
                summary = s._summarize_report_sentence(kind, 'Original market report', body)
                model.assert_not_called()
                self.assertTrue(40 <= len(summary) <= s.SUMMARY_LIMITS[kind])
                self.assertTrue(s._valid_brief(summary, kind, body), summary)
                self.assertEqual(s.brief_validation_reasons(summary, kind, body), [])
                self.assertTrue(summary_reference_layout(summary, kind)['withinLineLimit'])
                self.assertFalse(summary.endswith('다'))

    def test_german_translation_preserves_supply_demand_and_weekly_forecast(self):
        summary = s._native_report_sentence('eu_pork', GERMAN_MARKET)
        for fact in ('독일 돼지 공급', '계절적 확대', '수요 부진', '이번 주 가격 보합 전망'):
            self.assertIn(fact, summary)
        self.assertNotIn('가격 하락', summary)
        self.assertNotIn('전년', summary)

    def test_german_rule_needs_every_same_release_clause_without_negation(self):
        for original, changed in (
            ('Schlachtschweinemarkt', 'Rindermarkt'),
            ('weitet sich saisontypisch weiter aus', 'weitet sich saisontypisch nicht aus'),
            ('bleibt dagegen verhalten', 'bleibt dagegen nicht verhalten'),
            ('stabilen Preisen', 'fallenden Preisen'),
            ('laufende Woche', 'kommende Monate'),
            ('wird von', 'wird nicht von'),
            ('ausgegangen.', 'ausgegangen wird nicht.'),
        ):
            with self.subTest(changed=changed):
                self.assertIsNone(s._german_slaughter_pig_market_summary(GERMAN_MARKET.replace(original, changed)))

    def test_incubator_count_separates_weekly_fall_and_annual_rise_with_source_cause(self):
        summary = s._native_report_sentence('us_chicken', HATCHERY_EGGS)
        self.assertIn('전주비 21만 5000개 감소', summary)
        self.assertIn('2억 4530만 4000개', summary)
        self.assertIn('산란계 수 증가로 전년비 3% 늘었으나', summary)
        self.assertNotIn('전주비 3%', summary)
        self.assertTrue(s._supported_measurements(summary, HATCHERY_EGGS))
        self.assertFalse(s._supported_measurements(summary.replace('개', '마리'), HATCHERY_EGGS))

    def test_placement_change_inherits_animals_only_from_its_own_clause(self):
        summary = s._native_report_sentence('us_chicken', HATCHERY_PLACEMENTS)
        self.assertIn('111만 5000마리 늘어', summary)
        self.assertIn('1억 9029만 5000마리', summary)
        self.assertTrue(s._supported_measurements(summary, HATCHERY_PLACEMENTS))
        self.assertNotIn((1115000.0, 'items'), s._numeric_unit_facts(HATCHERY_PLACEMENTS))
        self.assertFalse(s._supported_measurements(summary.replace('마리', '개'), HATCHERY_PLACEMENTS))

    def test_changed_totals_delta_scale_and_direction_are_not_hardcoded(self):
        changed = (HATCHERY_EGGS.replace('245.304', '240.118')
                   .replace('falling 215,000', 'rising 312 thousand'))
        summary = s._native_report_sentence('us_chicken', changed)
        self.assertIn('31만 2000개 증가', summary)
        self.assertIn('2억 4011만 8000개', summary)
        changed = HATCHERY_PLACEMENTS.replace('190.295', '188.506').replace('up 1.115', 'down 2.245')
        summary = s._native_report_sentence('us_chicken', changed)
        self.assertIn('224만 5000마리 줄어', summary)
        self.assertIn('1억 8850만 6000마리', summary)
        self.assertTrue(s._valid_brief(summary, 'us_chicken', changed))

    def test_future_annual_wrong_species_and_fractional_counts_are_not_typed(self):
        for body in (
            HATCHERY_EGGS.replace('previous week', 'previous year'),
            HATCHERY_EGGS.replace('broiler-type eggs', 'turkey eggs'),
            HATCHERY_EGGS.replace('were set', 'will be set'),
            HATCHERY_EGGS.replace('215,000', '0.5'),
            HATCHERY_PLACEMENTS.replace('on the week', 'on the year'),
            HATCHERY_PLACEMENTS.replace('chicks', 'hens'),
            'Chick placements grew. up 1.115 million on the week.',
        ):
            with self.subTest(body=body):
                self.assertEqual(s._broiler_hatchery_weekly_facts(body), [])
                self.assertIsNone(s._extract_broiler_stat_summary(body))


if __name__ == '__main__':
    unittest.main()
