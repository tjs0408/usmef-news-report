"""Competition projections retain source growth, export capacity and dissent."""
import unittest
from unittest.mock import patch

from src import overseas_article_digest as s
from src.article_hwpx_layout import summary_reference_layout


GROWTH = ("No primeiro semestre de 2026, a produção chinesa de carne de frango cresceu mais de 9% "
          "em relação ao mesmo período do ano passado. ")
BACKGROUND = ("O avanço ocorre depois de uma expansão próxima de 7% em 2025, segundo informações do Rabobank. ")
CAUSE = ("O crescimento da oferta, superior ao ritmo de consumo interno, deixou mais carne disponível para exportação. ")
OUTLOOK = ("Chenjun Pan, especialista em proteínas animais do Rabobank, avalia que o país asiático poderá se tornar "
           "um concorrente relevante do Brasil, especialmente em mercados onde preço, disponibilidade e logística "
           "influenciam diretamente as decisões dos compradores. ")
COUNTERPOINT = ("Já o presidente da Associação Brasileira de Proteína Animal (ABPA), Ricardo Santin, apresenta uma "
                "avaliação menos preocupante e não considera que o avanço chinês necessariamente represente perda "
                "de mercado para os exportadores brasileiros.")
BODY = GROWTH + BACKGROUND + CAUSE + OUTLOOK + COUNTERPOINT


class BrazilChickenCompetitionContextTests(unittest.TestCase):
    def setUp(self):
        s._summarize_report_sentence.cache_clear()

    def tearDown(self):
        s._summarize_report_sentence.cache_clear()

    def test_growth_rate_and_competition_possibility_fit_one_line_without_model(self):
        with patch.object(s, "_ollama_generate", side_effect=AssertionError("typed passage needs no inference")):
            summary = s._summarize_report_sentence("brazil_chicken", "China chicken and Brazil competition", BODY)
        for phrase in ("2026년 상반기", "닭고기 생산 9% 초과 증가", "브라질 경쟁국 부상 가능성"):
            self.assertIn(phrase, summary)
        self.assertNotIn("수출 증가", summary)
        self.assertNotIn("시장 상실 확정", summary)
        self.assertNotIn("7%", summary)
        self.assertTrue(s._valid_brief(summary, "brazil_chicken", BODY))
        self.assertFalse(s._summary_needs_market_context("brazil_chicken", BODY, summary))
        self.assertTrue(40 <= len(summary) <= 50)
        layout = summary_reference_layout(summary, "brazil_chicken")
        self.assertEqual(layout["estimatedLines"], 1)
        self.assertTrue(layout["withinLineLimit"])
        self.assertGreaterEqual(layout["tracking"], -20)
        evidence = s._native_source_excerpt(BODY, summary)
        for passage in (GROWTH.strip(), CAUSE.strip(), "poderá se tornar", COUNTERPOINT):
            self.assertIn(passage, evidence)

    def test_changed_percent_year_and_decimal_separator_are_taken_from_the_production_clause(self):
        body = BODY.replace("2026", "2028").replace("mais de 9%", "mais de 6,5%")
        fact = s._brazil_chicken_expansion_competition_fact(body)
        self.assertIsNotNone(fact)
        self.assertIn("2028년 상반기", fact[0])
        self.assertIn("6.5% 초과 증가", fact[0])
        self.assertNotIn("2025년", fact[0])
        self.assertNotIn("7%", fact[0])
        self.assertTrue(s._valid_brief(fact[0], "brazil_chicken", body))

    def test_exact_increase_never_becomes_more_than_that_increase(self):
        exact = BODY.replace("mais de 9%", "9%")
        summary = s._brazil_chicken_competition_outlook_summary(exact)
        self.assertIn("9% 증가", summary)
        self.assertNotIn("9% 초과", summary)
        self.assertTrue(s._valid_brief(summary, "brazil_chicken", exact))

    def test_missing_counterpoint_is_not_invented_or_replaced_by_a_market_loss(self):
        body = BODY.replace(COUNTERPOINT, "")
        summary = s._brazil_chicken_competition_outlook_summary(body)
        self.assertIsNotNone(summary)
        self.assertNotIn("ABPA", summary)
        self.assertIn("경쟁국 부상 가능성", summary)
        self.assertNotIn("시장 상실", summary)
        reversed_opinion = BODY.replace("não considera", "considera")
        self.assertNotIn("ABPA 신중론", s._brazil_chicken_competition_outlook_summary(reversed_opinion))

    def test_wrong_product_direction_units_period_modality_and_causal_relation_are_rejected(self):
        invalid = (
            BODY.replace("produção chinesa de carne de frango", "produção chinesa de carne suína"),
            BODY.replace("cresceu mais de 9%", "caiu mais de 9%"),
            BODY.replace("9%", "9 mil toneladas"),
            BODY.replace("No primeiro semestre", "No segundo semestre"),
            BODY.replace("em relação ao mesmo período do ano passado", "em relação ao mês passado"),
            BODY.replace("superior ao ritmo de consumo interno", "inferior ao ritmo de consumo interno"),
            BODY.replace("deixou mais carne disponível", "não deixou mais carne disponível"),
            BODY.replace("poderá se tornar", "não poderá se tornar"),
            BODY.replace("poderá se tornar", "será"),
            BODY.replace(CAUSE, ""),
            "A instituição negou o relato como falso. " + BODY,
        )
        for body in invalid:
            with self.subTest(body=body):
                self.assertIsNone(s._brazil_chicken_expansion_competition_fact(body))

    def test_another_species_between_statistic_and_cause_cannot_supply_the_link(self):
        mixed = BODY.replace(CAUSE, "A carne suína foi analisada em outra seção. " + CAUSE)
        self.assertIsNone(s._brazil_chicken_expansion_competition_fact(mixed))

    def test_no_loss_or_percentage_unit_can_be_inferred_from_the_capacity_phrase(self):
        fact = s._brazil_chicken_expansion_competition_fact(BODY)
        self.assertIsNotNone(fact)
        self.assertNotIn("9%의 수출", fact[0])
        self.assertNotIn("9톤", fact[0])
        self.assertFalse(s._valid_brief(fact[0].replace("9%", "9톤"), "brazil_chicken", BODY))
        self.assertFalse(s._valid_brief(fact[0].replace("9%", "51%"), "brazil_chicken", BODY))


if __name__ == "__main__":
    unittest.main()
