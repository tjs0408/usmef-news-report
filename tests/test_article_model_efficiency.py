"""Inference budgets and safe, source-specific correction diagnostics."""
import unittest
from unittest.mock import patch

from src import overseas_article_digest as s


class ArticleModelEfficiencyTests(unittest.TestCase):
    def test_waiting_other_sections_does_not_consume_section_inference_allowance(self):
        budget = s.ArticleModelBudget(max_seconds=45, seconds=8)
        self.assertEqual(budget.remaining_seconds(), 37)
        with patch.object(s, "monotonic", return_value=103):
            budget.run_budget = s.ArticleRunModelBudget(max_seconds=180, started=100)
            self.assertEqual(budget.remaining_seconds(), 37)
        with patch.object(s, "monotonic", return_value=278):
            self.assertEqual(budget.remaining_seconds(), 2)

    def test_global_expired_budget_never_starts_generation(self):
        budget = s.ArticleModelBudget(run_budget=s.ArticleRunModelBudget(max_seconds=2, started=100))
        with patch.object(s, "monotonic", return_value=103), s.article_model_budget(budget), \
                patch.object(s, "_request_json") as request:
            with self.assertRaises(s.ArticleSummaryBudgetExceeded):
                s._ollama_generate("원문 보고서 문구")
        request.assert_not_called()
        self.assertEqual(budget.calls, 0)

    def test_remaining_allowance_limits_request_and_records_model_work(self):
        budget = s.ArticleModelBudget(max_seconds=45, seconds=35)
        payload = {"response": "brief", "prompt_eval_count": 500, "eval_count": 70}
        with s.article_model_budget(budget), patch.object(s, "_request_json", return_value=payload) as request:
            self.assertEqual(s._ollama_generate("compact instruction", num_predict=180), payload)
        self.assertEqual(request.call_args.kwargs["timeout"], 10)
        options = request.call_args.kwargs["body"]["options"]
        self.assertEqual(options["num_predict"], 128)
        self.assertEqual(budget.prompt_tokens, 500)
        self.assertEqual(budget.generated_tokens, 70)

    def test_failure_reason_identifies_wrong_quantity_without_echoing_draft(self):
        source = "US egg prices rose 5% on the year, while egg supply was unchanged."
        draft = "미국 계란의 전국 평균가격은 전년비 50% 상승한 가운데 계란 공급은 보통 수준"
        budget = s.ArticleModelBudget()
        with s.article_model_budget(budget):
            reason = s._record_brief_rejection(draft, "us_egg", source)
        self.assertIn("수치·단위·비교기간·변화 방향 불일치", reason)
        self.assertNotIn("50%", reason)
        self.assertEqual(budget.validation_failures[0]["length"], len(draft))

    def test_short_foreign_summary_uses_only_one_correction(self):
        source = "US egg prices rose 5% on the year. Egg supply was unchanged."
        short = "미국 계란 가격 전년비 5% 상승"
        invalid = "미국 계란 가격 전년비 50% 상승"
        with patch.object(s, "_native_report_sentence", return_value=None), \
                patch.object(s, "_extract_report_facts", return_value=[short]), \
                patch.object(s, "_compose_report_sentence", return_value=invalid) as compose, \
                patch.object(s, "_repair_korean_report_sentence") as repair:
            with self.assertRaises(s.ArticleSummaryValidationError):
                s._summarize_report_sentence.__wrapped__("us_egg", "Egg prices", source)
        compose.assert_called_once()
        repair.assert_not_called()

    def test_conditional_nominalization_never_turns_projection_into_reality(self):
        original = "미국 닭고기 가격 하락세가 이어질 수 있다."
        self.assertEqual(s._normalize_report_sentence(original, "us_chicken"),
                         "미국 닭고기 가격 하락세가 지속 가능성")
        negative = "미국 닭고기 가격 하락세가 이어질 수 없다."
        self.assertEqual(s._normalize_report_sentence(negative, "us_chicken"), negative.rstrip("."))
        necessary = "미국 닭고기 수입품의 원문 확인이 필요가 있다."
        self.assertEqual(s._normalize_report_sentence(necessary, "us_chicken"),
                         "미국 닭고기 수입품의 원문 확인이 필요")


if __name__ == "__main__":
    unittest.main()
