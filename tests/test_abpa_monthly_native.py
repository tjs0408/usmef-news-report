"""Typed ABPA monthly export facts; no titles, URLs or model-made quantities."""
from datetime import date
import unittest
from unittest.mock import patch

from src import livestock_article_draft as d
from src import overseas_article_digest as s
from src.article_hwpx_layout import summary_reference_layout


VOLUME = (
    'As exportações brasileiras de carne de frango (considerando todos os produtos, entre in natura e processados) '
    'totalizaram 500,3 mil toneladas em setembro, volume 3,7% superior ao registrado no mesmo mês de 2025, '
    'segundo a Associação Brasileira de Proteína Animal (ABPA).'
)
BODY = 'São Paulo, 7 de outubro de 2026 – ' + VOLUME
EXPECTED = '브라질 9월 닭고기 수출량 전년 동월비 3.7% 증가, 50만 300톤 기록'


class AbpaMonthlyNativeTests(unittest.TestCase):
    def tearDown(self):
        s._summarize_report_sentence.cache_clear()

    def test_complete_monthly_body_is_native_valid_and_one_line(self):
        with patch.object(s, '_ollama_generate') as model:
            summary = s._summarize_report_sentence('brazil_chicken', 'Unnumbered article title', BODY)
        model.assert_not_called()
        self.assertEqual(summary, EXPECTED)
        self.assertTrue(s._valid_brief(summary, 'brazil_chicken', BODY))
        self.assertGreaterEqual(len(summary), 40)
        self.assertTrue(summary_reference_layout(summary, 'brazil_chicken')['withinLineLimit'])
        self.assertEqual(s._numeric_unit_facts(summary), {(500300.0, 'tonne'), (3.7, 'percent')})

    def test_month_tonnage_percent_and_direction_are_captured_dynamically(self):
        changed = BODY.replace('em setembro', 'em agosto').replace('500,3', '321,456')
        changed = changed.replace('3,7%', '8,2%').replace('superior', 'inferior')
        summary = s._native_report_sentence('brazil_chicken', changed)
        for fact in ('8월', '8.2% 감소', '32만 1456톤'):
            self.assertIn(fact, summary)
        self.assertTrue(s._valid_brief(summary, 'brazil_chicken', changed))
        self.assertFalse(s._valid_brief(summary.replace('감소', '증가'), 'brazil_chicken', changed))
        fractional = BODY.replace('500,3', '500,3123')
        self.assertIsNone(s._brazil_chicken_monthly_export_summary(fractional))

    def test_declared_current_year_can_supply_the_absolute_annual_comparison(self):
        explicit = VOLUME.replace('em setembro,', 'em setembro de 2026,')
        self.assertEqual(s._native_report_sentence('brazil_chicken', explicit), EXPECTED)
        self.assertIsNone(s._native_report_sentence('brazil_chicken', VOLUME))
        for wrong in (BODY.replace('mesmo mês de 2025', 'mesmo mês de 2024'),
                      BODY.replace('mesmo mês de 2025', 'mesmo mês de 2026'),
                      BODY.replace('em setembro,', 'em setembro de 2024,'),
                      BODY.replace('7 de outubro', '32 de outubro'),
                      BODY.replace('em setembro', 'em dezembro')):
            with self.subTest(wrong=wrong):
                self.assertIsNone(s._brazil_chicken_monthly_export_summary(wrong))

    def test_currency_other_species_regions_and_negation_do_not_match(self):
        for wrong in (
            BODY.replace('mil toneladas', 'milhões de dólares'),
            BODY.replace('carne de frango', 'carne suína'),
            BODY.replace('exportações brasileiras', 'exportações paranaenses'),
            BODY.replace('totalizaram', 'não totalizaram'),
            BODY.replace('totalizaram', 'poderão totalizar'),
            BODY.replace('no mesmo mês de 2025', 'no mês anterior'),
            BODY.replace('volume 3,7% superior', 'receita 3,7% superior'),
        ):
            with self.subTest(wrong=wrong):
                self.assertIsNone(s._brazil_chicken_monthly_export_summary(wrong))

    def test_revenue_and_state_figures_cannot_replace_national_monthly_facts(self):
        mixed = BODY + (
            ' A receita alcançou US$ 984,2 milhões, resultado 14,7% superior. '
            'O Paraná exportou 199,7 mil toneladas, volume 9,5% superior.'
        )
        self.assertEqual(s._native_report_sentence('brazil_chicken', mixed), EXPECTED)
        for wrong in (EXPECTED.replace('3.7%', '14.7%'),
                      EXPECTED.replace('50만 300톤', '19만 9700톤'),
                      EXPECTED.replace('9월', '10월'),
                      EXPECTED.replace('톤', '달러'),
                      EXPECTED.replace('3.7%', '99%')):
            with self.subTest(wrong=wrong):
                self.assertFalse(s._valid_brief(wrong, 'brazil_chicken', mixed))

    def test_headline_and_calendar_words_alone_are_not_numeric_evidence(self):
        body = 'A Associação discute exportações de frango em setembro, sem divulgar volumes.'
        self.assertIsNone(s._native_report_sentence('brazil_chicken', body))
        self.assertFalse(s._valid_brief(EXPECTED, 'brazil_chicken', body))
        self.assertNotIn(9.0, s._brief_numeric_values(body))

    def test_original_publication_outside_report_week_is_rejected_by_collection(self):
        url = 'https://abpa-br.org/noticias/monthly-chicken-exports/'
        candidate = {'title': 'Exportações brasileiras de carne de frango', 'url': url,
                     'publishedDate': date(2026, 10, 7), 'body': BODY}
        original = {**candidate, 'publishedDate': date(2026, 9, 30)}
        with patch.object(d, '_original_article', return_value=original) as read:
            result = d._choose_original([candidate], d.SPECS_BY_KEY['brazil_chicken'],
                date(2026, 10, 2), date(2026, 10, 8), trusted_country=True)
        self.assertIsNone(result)
        read.assert_called_once()


if __name__ == '__main__':
    unittest.main()
