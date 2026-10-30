import unittest

from src.article_failure_details import summary_failure_details
from src import overseas_article_digest as s


class ArticleFailureDetailsTests(unittest.TestCase):
    def test_retry_budget_is_not_misreported_as_a_provider_quota(self):
        result = summary_failure_details(s.ArticleSummaryBudgetExceeded("로컬 AI 요약 호출 횟수 제한"), {
            "modelCalls": 2,
            "validationReasons": [{"length": 39, "reasons": ["최소 40자 미달(39자)"]},
                                  {"length": 89, "reasons": ["최대 80자 초과(89자)"]}],
        })
        self.assertEqual(result["summaryErrorCode"], "summary_repair_limit")
        self.assertIn("교정 2회", result["summaryError"])
        self.assertIn("서비스 이용 한도 오류는 아닙니다", result["summaryError"])
        self.assertIn("최대 80자 초과", result["summaryError"])
        self.assertEqual(len(result["failureReasons"]), 2)

    def test_layout_and_validation_errors_remain_distinct(self):
        layout = summary_failure_details(s.ArticleSummaryLayoutError("허용 한 줄 초과"), {})
        validation = summary_failure_details(s.ArticleSummaryValidationError("원문 수치 불일치"), {})
        self.assertEqual(layout["summaryErrorCode"], "summary_layout")
        self.assertEqual(validation["summaryErrorCode"], "summary_validation")
        self.assertEqual(layout["summaryError"], "허용 한 줄 초과")


if __name__ == "__main__":
    unittest.main()
