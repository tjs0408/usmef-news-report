import unittest
from unittest.mock import patch

from src import overseas_article_digest as s
from src.current_week_market_sources import native_tcfa_brief
from src.article_hwpx_layout import summary_reference_layout


BODY = '''TCFA Daily Market Summary - October 19, 2026
USDA BEEF CUT OUT
CH 600/900: $371.58 DN -0.73 SL 600/900: $359.91 UP 6.86
SLAUGHTER
Today: 105,000
'''


class BeefGradeClarityTests(unittest.TestCase):
    def test_current_native_brief_explains_both_grades_market_and_defined_unit(self):
        summary, evidence = native_tcfa_brief(BODY)
        for label in ('초이스 등급', '셀렉트 등급', '쇠고기 도매가격 지표', '100 파운드당'):
            self.assertIn(label, summary)
        self.assertTrue(s._valid_brief(summary, 'us', BODY))
        self.assertEqual(s.brief_validation_reasons(summary, 'us', BODY), [])
        self.assertTrue(summary_reference_layout(summary, 'us')['withinLineLimit'])
        fitted = s._fit_report_summary(summary, 'us', BODY)
        self.assertEqual(fitted, summary)
        self.assertEqual(s._native_source_excerpt(BODY, fitted), evidence)
        with patch.object(s, '_ollama_generate', side_effect=AssertionError('no model needed')):
            self.assertEqual(s._summarize_report_sentence.__wrapped__('us', 'TCFA', BODY), summary)

    def test_all_korean_grade_mentions_are_explicit_and_normalization_is_idempotent(self):
        for phrase in ('쇠고기 초이스 371달러, 셀렉트 359달러 기록',
                       '쇠고기 초이스·셀렉트 가격 보합',
                       '쇠고기 초이스등급·셀렉트급 가격 보합',
                       '쇠고기 초이스 등급·셀렉트 등급 가격 보합'):
            with self.subTest(phrase=phrase):
                normalized = s._normalize_livestock_terms(phrase)
                self.assertIn('초이스 등급', normalized)
                self.assertIn('셀렉트 등급', normalized)
                self.assertEqual(s._normalize_livestock_terms(normalized), normalized)
                self.assertNotIn('등급 등급', normalized)

    def test_english_grade_names_are_translated_but_ordinary_select_is_untouched(self):
        actual = s._normalize_livestock_terms('미국 beef Choice/Select 등급 가격 보합')
        self.assertIn('초이스 등급/셀렉트 등급', actual)
        self.assertEqual(s._normalize_livestock_terms('Select an option'), 'Select an option')
        self.assertEqual(s._normalize_livestock_terms('select beef cuts'), 'select beef cuts')

    def test_grade_subject_particles_follow_korean_grade_noun(self):
        self.assertEqual(s._normalize_livestock_terms('소고기 셀렉트는 보합'), '소고기 셀렉트 등급은 보합')
        self.assertEqual(s._normalize_livestock_terms('소고기 초이스가 상승'), '소고기 초이스 등급이 상승')

    def test_model_rules_request_grade_explanation(self):
        self.assertIn('초이스 등급·셀렉트 등급', s._brief_model_rules('us'))

    def test_usmef_compression_must_not_remove_the_grade_subject(self):
        body = ('Choice/Select 등급 컷아웃 지난주 소고기 초이스 가격은 전주 대비 '
                '1.2% 상승한 371.58달러를 기록했다.')
        summary = s._extract_usmef_source_summary(body)
        self.assertIsNotNone(summary)
        self.assertIn('초이스 등급', summary)
        self.assertIn('셀렉트 등급', summary)

    def test_standard_weight_denominator_cannot_become_herd_or_price_fact(self):
        self.assertTrue(s._supported_measurements('100 파운드당 359.91달러', BODY))
        self.assertFalse(s._supported_measurements('소 100두', BODY))
        self.assertFalse(s._supported_measurements('100달러', BODY))
        other = 'A market report quotes cattle prices of $359.91.'
        self.assertNotIn(100, s._brief_numeric_values(other))


if __name__ == '__main__':
    unittest.main()
