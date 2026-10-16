"""A court dismissal must come from body evidence, not a policy headline."""
import unittest
from unittest.mock import patch

from src import overseas_article_digest as s
from src.article_hwpx_layout import summary_reference_layout


DISMISSAL = (
    "A federal judge has dismissed an attempt by the Trump administration to "
    "eliminate Michigan’s cage-free egg law. "
)
RULING = (
    "U.S. District Judge Jane Beckering says the plaintiff failed to establish "
    "standing and dismissed the case for lack of subject-matter jurisdiction."
)
BODY = (
    DISMISSAL
    + "Nancy Barr with the Michigan Allied Poultry Industries (MAPI) tells "
    "Brownfield all eggs produced in the state have been cage-free since at least 2025. "
    + RULING
)


class USEggPolicyNativeTests(unittest.TestCase):
    def tearDown(self):
        s._summarize_report_sentence.cache_clear()

    def test_body_supported_dismissal_is_report_ready_without_a_model(self):
        with patch.object(s, "_ollama_generate") as model:
            summary = s._summarize_report_sentence(
                "us_egg", "Trump administration’s challenge to Michigan cage-free law dismissed", BODY,
            )
        model.assert_not_called()
        self.assertIn("미시간주 계란 케이지 사육 금지법", summary)
        self.assertTrue(summary.endswith("정부 소송 기각"))
        self.assertTrue(s._valid_brief(summary, "us_egg", BODY))
        self.assertGreaterEqual(len(summary), 40)
        self.assertTrue(summary_reference_layout(summary, "us_egg")["withinLineLimit"])
        for unfounded in ("합헌", "승소", "생산 증가", "가격 하락"):
            self.assertNotIn(unfounded, summary)

    def test_headline_or_one_incomplete_clause_cannot_become_a_ruling(self):
        for body in (
            "Trump administration’s challenge to Michigan cage-free law dismissed",
            DISMISSAL,
            RULING,
            "A federal judge will consider an attempt by the Trump administration to "
            "eliminate Michigan’s cage-free egg law. " + RULING,
        ):
            with self.subTest(body=body):
                self.assertIsNone(s._michigan_egg_policy_summary(body))
                self.assertIsNone(s._native_report_sentence("us_egg", body))

    def test_opposite_ruling_or_another_species_does_not_match(self):
        for body in (
            BODY.replace("has dismissed", "has not dismissed"),
            BODY.replace("has dismissed", "may dismiss"),
            BODY.replace("dismissed the case", "did not dismiss the case"),
            BODY.replace("failed to establish standing", "established standing"),
            BODY.replace("egg law", "pork law"),
            BODY.replace("Michigan’s", "California’s"),
            BODY.replace("subject-matter jurisdiction", "policy agreement"),
        ):
            with self.subTest(body=body):
                self.assertIsNone(s._michigan_egg_policy_summary(body))

    def test_apostrophe_and_spacing_do_not_change_the_fact(self):
        body = BODY.replace("Michigan’s", "Michigan's").replace("federal judge", "federal\njudge")
        self.assertEqual(s._michigan_egg_policy_summary(BODY), s._michigan_egg_policy_summary(body))


if __name__ == "__main__":
    unittest.main()
