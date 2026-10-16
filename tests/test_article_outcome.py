"""Explain partial completion without treating finished processing as success."""
import unittest

from app import _describe_article_outcome


class ArticleOutcomeTests(unittest.TestCase):
    def test_failure_categories_and_original_result_are_preserved(self):
        sections = {
            "ready": {"article": {"title": "news"}, "summary": "valid", "status": "completed"},
            "source": {"article": None, "status": "source_error"},
            "none": {"article": None, "status": "no_article"},
            "summary": {"article": {"title": "news"}, "status": "summary_error"},
            "model": {"article": {"title": "news"}, "status": "model_unavailable"},
        }
        original = {"sections": sections, "totalCount": 5, "readyCount": 0, "weekStart": "2026-10-04"}
        result = _describe_article_outcome(original)
        self.assertEqual(result["readyCount"], 1)
        self.assertEqual(result["failureCounts"], {"source": 2, "summary": 1, "model": 1})
        self.assertIn("원문 미확보 2건", result["message"])
        self.assertIn("요약 검증 미완료 1건", result["message"])
        self.assertEqual(original["readyCount"], 0)
        self.assertEqual(result["weekStart"], original["weekStart"])

    def test_full_completion_has_no_misleading_failure_message(self):
        result = _describe_article_outcome({"sections": {"us": {"summary": "valid"}}, "totalCount": 1})
        self.assertIn("1/1건 완료", result["message"])
        self.assertNotIn("미완료", result["message"])
        self.assertEqual(sum(result["failureCounts"].values()), 0)


if __name__ == "__main__":
    unittest.main()
