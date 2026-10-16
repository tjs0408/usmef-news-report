"""Minimum-length and nominal-report-style publication regressions, offline."""
import unittest
from unittest.mock import patch

from src import overseas_article_digest as s
from src.report_brief_style import SECTION_AUDIENCES, SUMMARY_LIMITS, SUMMARY_MIN_LENGTH, style_prompt


class ArticleSummaryFormatTests(unittest.TestCase):
    def setUp(self):
        s._summarize_report_sentence.cache_clear()

    def tearDown(self):
        s._summarize_report_sentence.cache_clear()

    def test_all_twelve_sections_require_body_length_not_title_or_prefix(self):
        self.assertEqual(SUMMARY_MIN_LENGTH, 40)
        for kind in SECTION_AUDIENCES:
            product = "돼지고기" if "pork" in kind else "닭고기" if "chicken" in kind else "계란" if "egg" in kind else "소고기"
            short = f"{product} 수입 확대 정책의 추가 검토"
            complete = f"미국 {product} 수입 확대 정책을 둘러싼 논의가 이어지는 가운데 정부가 추가 검토"
            with self.subTest(kind=kind):
                self.assertTrue(s._brief_content_supported(short, kind, short))
                self.assertFalse(s._valid_brief(short, kind, short))
                self.assertTrue(s._valid_brief(complete, kind, complete))
                self.assertFalse(s._valid_brief(" " * 40 + short, kind, short))
                self.assertFalse(s._valid_brief("-(현지동향) " + short, kind, short))
                self.assertIn(f"40~{SUMMARY_LIMITS[kind]}자", style_prompt(kind))

    def test_39_rejected_and_40_accepted_without_padding(self):
        minimum = "미국 소고기 수입 확대 정책과 시장 상황을 확인하는 가운데 정부가 재검토"
        short = minimum.replace("재검토", "검토")
        self.assertEqual(len(minimum), 40)
        self.assertEqual(len(short), 39)
        self.assertTrue(s._valid_brief(minimum, "domestic", minimum))
        self.assertFalse(s._valid_brief(short, "domestic", minimum))
        self.assertFalse(s._valid_brief(short + " ", "domestic", minimum))

    def test_known_predicates_become_nominal_without_new_outlook(self):
        cases = {
            "미국 소고기 가격은 상승세를 이어간다.": "미국 소고기 가격은 상승세 지속",
            "계란 수입 확대 가능성을 시사한다.": "계란 수입 확대 가능성을 시사",
            "일본 계란 생산량 회복을 전망한다.": "일본 계란 생산량 회복을 전망",
            "미국 돼지고기 수입 확대를 검토하고 있다.": "미국 돼지고기 수입 확대를 검토",
            "닭고기 공급은 회복될 것으로 예상된다.": "닭고기 공급은 회복될 것으로 예상",
        }
        for before, after in cases.items():
            self.assertEqual(s._normalize_report_sentence(before, "domestic"), after)
        self.assertNotIn("전망", s._normalize_report_sentence("미국 소고기 가격은 상승세를 이어간다.", "domestic"))

    def test_all_sections_normalize_and_reject_finite_endings(self):
        for kind in SECTION_AUDIENCES:
            with self.subTest(kind=kind):
                self.assertEqual(s._normalize_report_sentence("공급 감소로 가격 상승세를 이어간다.", kind),
                                 "공급 감소로 가격 상승세 지속")
                self.assertEqual(s._normalize_report_sentence("출하 감소로 공급이 축소되었습니다.", kind),
                                 "출하 감소로 공급이 축소")
                product = "돼지고기" if "pork" in kind else "닭고기" if "chicken" in kind else "계란" if "egg" in kind else "소고기"
                prose = f"미국 {product} 수입 확대 정책을 둘러싼 논의가 이어지는 가운데 정부가 추가 검토한다."
                self.assertFalse(s._valid_brief(prose, kind, prose))
                nominal = s._normalize_report_sentence(prose, kind)
                self.assertTrue(s._valid_brief(nominal, kind, prose))

    def test_negation_conditionals_and_unknown_verbs_are_not_reinterpreted(self):
        for sentence in ("돼지고기 수입 확대를 검토하지 않았다.", "계란 수급 개선을 시사하지 않는다.",
                         "소고기 가격이 상승할 것이다.", "닭고기 수입 확대는 검토할 수도 있다.",
                         "계란 공급 감소는 사실이 아니다."):
            self.assertEqual(s._normalize_report_sentence(sentence, "domestic"), sentence.rstrip("."))

    def test_domestic_finite_prose_cannot_be_published(self):
        for kind in ("domestic", "domestic_pork", "domestic_chicken", "domestic_egg"):
            product = "소고기" if kind == "domestic" else "돼지고기" if "pork" in kind else "닭고기" if "chicken" in kind else "계란"
            draft = f"미국 {product} 수입 확대 정책을 둘러싼 논의가 이어지는 가운데 정부가 추가 검토한다."
            self.assertFalse(s._valid_brief(draft, kind, draft))
            normalized = s._normalize_report_sentence(draft, kind)
            self.assertTrue(s._valid_brief(normalized, kind, draft))

    def test_minimum_is_checked_again_after_verb_shortens(self):
        draft = "미국 소고기 수입 확대 정책을 확인하는 가운데 미국 정부가 추가 검토한다."
        self.assertGreaterEqual(len(draft), 40)
        self.assertLess(len(s._normalize_report_sentence(draft, "domestic")), 40)
        complete = "미국 소고기 수입 확대 정책을 확인하는 가운데 미국 정부가 추가적인 검토"
        with patch.object(s, "_native_report_sentence", return_value=None), \
             patch.object(s, "_extract_report_facts", return_value=[draft]), \
             patch.object(s, "_compose_report_sentence", return_value=draft) as compose, \
             patch.object(s, "_repair_korean_report_sentence", return_value=complete) as repair:
            self.assertEqual(s._summarize_report_sentence("domestic", "정책 검토", draft), complete)
            compose.assert_called_once()
            repair.assert_called_once()

    def test_short_translation_is_recomposed_not_directly_published(self):
        short = "미국 육계 종란 입란수 전주비 253만5000개 증가"
        complete = "미국 육계용 종란의 입란수는 전주와 비교해 253만 5000개 늘어나 증가세를 기록"
        body = "Broiler eggs set increased 2,535,000 eggs on the week."
        with patch.object(s, "_native_report_sentence", return_value=None), \
             patch.object(s, "_extract_report_facts", return_value=[short]), \
             patch.object(s, "_compose_report_sentence", return_value=complete) as compose:
            self.assertEqual(s._summarize_report_sentence("us_chicken", "Broiler sets", body), complete)
            compose.assert_called_once()

    def test_short_retry_is_not_padded_or_hard_truncated(self):
        body = "미국 소고기 공급 감소로 가격 상승세가 지속되고 있다. 미국 소고기 생산량도 감소했다."
        short = "미국 소고기 공급 감소로 가격 상승 지속"
        with patch.object(s, "_native_report_sentence", return_value=None), \
             patch.object(s, "_summarize_usmef_market_sentence", return_value=short), \
             patch.object(s, "_repair_korean_report_sentence", return_value=short):
            with self.assertRaises(s.ArticleDigestError):
                s._summarize_report_sentence("us", "공급 감소", body)

    def test_korean_domestic_article_skips_unnecessary_translation(self):
        complete = "미국 소고기 수입 확대 정책을 둘러싼 논의가 이어지는 가운데 정부가 추가 검토"
        with patch.object(s, "_native_report_sentence", return_value=None), \
             patch.object(s, "_extract_report_facts") as translate, \
             patch.object(s, "_compose_report_sentence", return_value=complete):
            self.assertEqual(s._summarize_report_sentence("domestic", "정책 논의", complete), complete)
            translate.assert_not_called()

    def test_failed_translation_repairs_from_original_not_invented_facts(self):
        body = "US egg prices rose 5% on the year. Egg supply was unchanged from the previous year."
        wrong = "미국 계란 가격이 전년비 50% 상승했으며 계란 공급은 30% 증가"
        correct = "미국 계란 가격은 전년비 5% 상승했고 계란 공급은 전년과 비교해 비슷한 수준을 유지"
        with patch.object(s, "_native_report_sentence", return_value=None), \
             patch.object(s, "_extract_report_facts", return_value=[wrong]), \
             patch.object(s, "_compose_report_sentence", return_value=wrong), \
             patch.object(s, "_repair_korean_report_sentence", return_value=correct) as repair:
            self.assertEqual(s._summarize_report_sentence("us_egg", "Egg prices", body),
                             s.compact_report_summary(correct, "us_egg", source=body, target=40))
            self.assertEqual(repair.call_args.kwargs["facts"], [s._market_fact_excerpt(body)])
            self.assertNotIn(wrong, repair.call_args.kwargs["facts"])

    def test_translated_facts_cannot_invent_an_outlook(self):
        body = "US egg prices rose 5% on the year."
        response = "미국 계란 가격은 전년비 5% 상승했고 앞으로도 계란 가격의 상승세가 이어질 것으로 전망"
        with patch.object(s, "_ollama_generate", return_value={"response": response}):
            with self.assertRaises(s.ArticleDigestError):
                s._extract_report_facts(kind="us_egg", audience="미국 계란", title="Egg prices", body=body,
                                        headline_only=False, search_result=False)

    def test_unknown_finite_ending_gets_source_based_repair(self):
        body = "미국 소고기 수입 확대 정책을 둘러싼 논의가 이어지는 가운데 정부가 추가 검토에 들어갔다."
        complete = "미국 소고기 수입 확대 정책을 둘러싼 논의가 이어지는 가운데 정부가 추가 검토"
        with patch.object(s, "_native_report_sentence", return_value=None), \
             patch.object(s, "_extract_report_facts", return_value=[body]), \
             patch.object(s, "_compose_report_sentence", return_value=body), \
             patch.object(s, "_repair_korean_report_sentence", return_value=complete) as repair:
            self.assertEqual(s._summarize_report_sentence("domestic", "정책 논의", body), complete)
            repair.assert_called_once()

    def test_native_rule_with_too_little_context_is_not_completed(self):
        body = "鶏卵の平均価格は過去最高を更新。"
        self.assertIsNotNone(s._grounded_market_statistic("japan_egg", body))
        self.assertIsNone(s._native_report_sentence("japan_egg", body))

    def test_legacy_domestic_route_uses_same_gate(self):
        with patch.object(s, "_summarize_report_sentence", return_value="validated") as summary:
            s._summarize_with_ollama(s.ARTICLE_GROUPS["pork"], "title", "body")
            summary.assert_called_once_with("domestic_pork", "title", "body")

    def test_long_enough_summary_still_cannot_invent_quantity_or_outlook(self):
        body = "미국 소고기 수입 확대 정책을 둘러싼 논의가 이어지는 가운데 정부가 추가 검토"
        invented = "미국 소고기 수입 확대 정책을 둘러싼 논의로 수입 물량은 30만톤 증가할 것으로 전망"
        self.assertGreaterEqual(len(invented), 40)
        self.assertFalse(s._valid_brief(invented, "domestic", body))


if __name__ == "__main__":
    unittest.main()
