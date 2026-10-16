"""Brazil native summaries require body facts, not dubious headline statistics."""
import unittest
from unittest.mock import patch

from src import overseas_article_digest as s
from src.article_hwpx_layout import summary_reference_layout


PENDING_EXPORTS = (
    "As exportações de frango e mel do Brasil para a União Europeia ainda dependem de etapas administrativas, "
    "apesar da avaliação sanitária favorável. O governo brasileiro busca acelerar a liberação dos embarques "
    "ao mercado europeu. As compras poderão ser retomadas no curto prazo, após a conclusão dos procedimentos "
    "burocráticos. A avaliação favorável para aves e mel, isoladamente, não autoriza novos embarques."
)


class BrazilNativeSourceGuardTests(unittest.TestCase):
    def tearDown(self):
        s._summarize_report_sentence.cache_clear()

    def test_completed_pending_trade_body_is_native_and_keeps_approval_requirement(self):
        with patch.object(s, '_ollama_generate') as model:
            summary = s._summarize_report_sentence('brazil_chicken',
                'Frango e mel brasileiros aguardam decisão da União Europeia para retomada das exportações',
                PENDING_EXPORTS)
        model.assert_not_called()
        self.assertTrue(s._valid_brief(summary, 'brazil_chicken', PENDING_EXPORTS))
        self.assertTrue(summary_reference_layout(summary, 'brazil_chicken')['withinLineLimit'])
        self.assertIn('위생 평가 긍정적이나', summary)
        # At -20 the fuller original formulation can fit without contraction;
        # both forms must retain the pending administrative approval condition.
        self.assertRegex(summary, r'재개(?:에|는|에 남은|는 남은) 행정 절차 완료 필요')
        self.assertNotIn('재개 확정', summary)

    def test_headline_tonnes_and_percent_are_not_article_body_evidence(self):
        headline = '브라질 닭고기 수출 151만톤, 전분기비 2.2% 증가하며 역대 최대 기록'
        body = 'A reportagem discute exportações de carne de frango do Brasil, sem informar volume ou comparação.'
        self.assertIsNone(s._native_report_sentence('brazil_chicken', body))
        self.assertFalse(s._brief_content_supported(headline, 'brazil_chicken', body))

    def test_quarter_headline_does_not_activate_an_unapproved_statistic_rule(self):
        # The selected CPG candidate had a misleading source hyperlink. Its
        # body is deliberately not given a new auto-publication rule here.
        body = (
            'As exportações de frango do Brasil alcançaram 1,51 milhão de toneladas entre julho e setembro de 2026, '
            'o maior volume trimestral registrado na série histórica da Secretaria de Comércio Exterior, iniciada em 1997. '
            'O resultado representou avanço de 2,2% sobre os três meses imediatamente anteriores.'
        )
        self.assertIsNone(s._grounded_market_statistic('brazil_chicken', body))
        self.assertIsNone(s._native_report_sentence('brazil_chicken', body))

    def test_currency_and_unstated_month_or_comparison_never_become_tonnes(self):
        bodies = (
            'O Brasil exportou 984,2 milhões de dólares de carne de frango em setembro, alta de 14,7% em um ano.',
            'A receita das exportações brasileiras de frango alcançou US$ 984,2 milhões, avanço de 14,7%.',
            'O Brasil exportou 500,3 mil toneladas de carne de frango, alta de 3,7% em um ano.',
            'O Brasil exportou 500,3 mil toneladas de carne de frango em setembro, alta de 3,7%.',
            'O Brasil exportou 500,3 mil toneladas de carne de frango em setembro, alta de 3,7% em um mês.',
            'O Paraná exportou 500,3 mil toneladas de carne de frango em setembro, alta de 3,7% em um ano.',
            'O Brasil exportou 500,3 mil toneladas de carne suína em setembro, alta de 3,7% em um ano.',
        )
        for body in bodies:
            with self.subTest(body=body):
                self.assertIsNone(s._grounded_market_statistic('brazil_chicken', body))


if __name__ == '__main__':
    unittest.main()
