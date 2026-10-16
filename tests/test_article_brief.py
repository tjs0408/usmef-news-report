import unittest
from datetime import date
from unittest.mock import patch

from src import overseas_article_digest as digest
from src.report_brief_style import STYLE_EXAMPLES, SUMMARY_LIMITS


class ArticleBriefTests(unittest.TestCase):
    def test_examples_are_complete_short_report_style(self):
        for kind, examples in STYLE_EXAMPLES.items():
            for example in examples:
                self.assertTrue(digest._is_valid_korean_report_sentence(example), example)
                self.assertLessEqual(len(example), SUMMARY_LIMITS[kind])

    def test_no_hard_truncation(self):
        long = "미국 소고기 공급 감소로 가격 상승이 지속되는 가운데 " * 6 + "공급 부족 우려"
        short = "미국 소고기 공급 감소가 이어지는 가운데 공급 감소에 따른 가격 상승세 지속"
        with patch.object(digest, "_summarize_usmef_market_sentence", return_value=long), patch.object(
            digest, "_repair_korean_report_sentence", return_value=short
        ) as repair:
            self.assertEqual(digest._summarize_report_sentence("us", "시장", long), short)
            repair.assert_called_once()

    def test_overlong_retry_is_rejected(self):
        long = "소고기 공급 부족으로 가격 상승 " * 8 + "지속"
        with patch.object(digest, "_summarize_usmef_market_sentence", return_value=long), patch.object(
            digest, "_repair_korean_report_sentence", return_value=long
        ):
            with self.assertRaises(digest.ArticleDigestError):
                digest._summarize_report_sentence("us", "시장", long)

    def test_invented_numeric_value_rejected(self):
        # Content guards must be exercised independently of the new length gate.
        self.assertFalse(digest._brief_content_supported("미국 소고기 가격 15% 상승", "us", "미국 소고기 가격 5% 상승"))
        self.assertTrue(digest._brief_content_supported("미국 소고기 가격 5% 상승", "us", "미국 소고기 가격 5.0% 상승"))
        self.assertTrue(digest._brief_content_supported("호주 소고기 생산량 300만톤 증가", "australia", "Australia beef production increased to 3 million tonnes."))
        self.assertFalse(digest._brief_content_supported("소고기 가격이 상승했다. 수입 감소", "us", "소고기 가격이 상승했다. 수입 감소"))
        self.assertFalse(digest._brief_content_supported("수입 확대에 따른 공급 개선 기대", "us", "수입 확대 발표"))
        self.assertFalse(digest._brief_content_supported("모든 관세가 해제되면서 소고기 수요 증가", "us", "소고기 수입 물량 30만톤의 쿼터 외 관세를 철폐했다."))
        self.assertFalse(digest._brief_content_supported("소고기 생산 증가 증가/지속", "australia", "Beef production is rising."))
        self.assertFalse(digest._brief_content_supported("독일 돼지고기 가격 증가/감소 지속", "eu_pork", "German pig prices fell."))

    def test_complete_translation_does_not_need_second_inference(self):
        fact = "미국 육계용 종란의 입란수는 전주와 비교해 253만 5000개 늘어나 증가세를 기록"
        with patch.object(digest, "_extract_report_facts", return_value=[fact]), patch.object(digest, "_compose_report_sentence") as compose:
            self.assertEqual(digest._summarize_report_sentence("us_chicken", "Broiler sets", "Broiler eggs set increased 2,535,000 eggs on the week."), fact)
            compose.assert_not_called()

    def test_fact_lines_remain_separate_and_invented_number_is_dropped(self):
        payload = {"response": "- 미국 계란 가격 5% 상승\n- 미국 계란 가격 25% 상승\n- 美國 계란 공급 감소"}
        with patch.object(digest, "_ollama_generate", return_value=payload):
            facts = digest._extract_report_facts(audience="미국 계란", title="Egg prices", body="US egg prices rose 5%", headline_only=False, search_result=False)
        self.assertEqual(facts, ["미국 계란 가격 5% 상승"])

    def test_usmef_compaction_preserves_source_quantities_and_complete_sentence(self):
        body = "돼지고기 컷아웃 지난주 돼지고기 컷아웃 가격은 전주 대비 0.4% (-0.01달러) 소폭 하락한 0.87달러로 2024년 2월 이래 최저가를 기록했다. " + "돼지고기 생산량, 도축두수 및 중량 지난주 돼지고기 생산량은 전주(5억 2,720만 파운드) 대비 3.0% 증가했고 전년 대비로도 0.1% 소폭 증가한 5억 4,290만 파운드를 기록했다."
        summary = digest._extract_usmef_source_summary(body, kind="us_pork")
        self.assertIsNotNone(summary)
        self.assertLessEqual(len(summary), SUMMARY_LIMITS["us_pork"])
        self.assertTrue(digest._valid_brief(summary, "us_pork", body))
        self.assertTrue("돼지고기" in summary)
        self.assertFalse(digest._valid_brief("Broiler eggs set 증가", "us_chicken", "Broiler eggs set increased."))
        self.assertTrue(digest._brief_content_supported("소고기 생산량 4억3010만 파운드 기록", "us", "Beef production was 430.1 million pounds."))
        self.assertTrue(digest._brief_content_supported("계란 생산량 253만5000개 증가", "us_egg", "Egg production rose 2.535 million."))

    def test_broiler_statistic_preserves_unit_and_direction_without_model(self):
        text = "The USDA says 249.839 million broiler-type eggs were set into incubation, up 2.535 million on the week."
        with patch.object(digest, "_extract_report_facts") as generate:
            summary = digest._summarize_report_sentence("us_chicken", "USDA broiler sets", text)
            generate.assert_not_called()
        self.assertIn("2억 4983만 9000개", summary)
        self.assertIn("253만 5000개 증가", summary)
        self.assertTrue(digest._valid_brief(summary, "us_chicken", text))
        self.assertIn("감소", digest._extract_broiler_stat_summary(text.replace(", up ", ", down ")))
        self.assertIsNone(digest._extract_broiler_stat_summary("Egg production is forecast to rise."))

    def test_market_excerpt_is_a_fact_not_future_release_calendar(self):
        fact = "The USDA says 249.839 million broiler-type eggs were set into incubation, up 2.535 million on the week."
        body = "Broiler numbers were generally up. " + fact + " The USDA updated annual egg and broiler production estimates are out October 9 th."
        self.assertEqual(digest._market_fact_excerpt(body), fact)
        expanded = digest._literal_foreign_quantities(fact)
        self.assertIn("249839000", expanded)
        self.assertIn("2535000", expanded)
        self.assertEqual(digest._brief_numeric_values(fact), digest._brief_numeric_values(expanded))

    def test_meaningless_article_is_excluded(self):
        self.assertLess(digest._domestic_market_relevance({
            "title": "미국·호주 소고기 등급제 한눈에, 해외축산정보 발간",
            "body": "소고기 수입과 가격을 소개하는 자료집을 발간했다.",
        }), 0)
        self.assertLess(digest._domestic_market_relevance({"title": "미국 소고기 시장 소개", "body": "해외 소고기 시장을 알아본다."}), 0)

    def test_concrete_market_event_selected(self):
        good = {"title": "미국 소고기 수입 확대, 30만톤 관세 면제", "body": "미국은 공급 부족으로 높은 소고기 가격을 낮추기 위해 수입 확대를 추진했다.", "publishedDate": date(2026, 9, 24), "url": "https://example.org/market"}
        bad = {**good, "title": "미국 소고기 등급제 소개", "url": "https://example.org/pr"}
        found = digest._select_beef_search_candidate([bad, good], region_terms=("미국",), require_foreign_context=True, require_supply_price_context=True)
        self.assertEqual(found["url"], good["url"])

    def test_domestic_needs_original_body(self):
        candidate = {"title": "미국 소고기 가격 상승, 수입 확대", "body": "소고기 가격 상승으로 미국이 수입 확대 추진", "publishedDate": date(2026, 9, 24), "url": "https://example.org/news", "headlineOnly": False, "searchResult": True}
        with patch.object(digest, "_search_google_news_rss", return_value=[candidate]), patch.object(digest, "_search_naver_news", return_value=[]), patch.object(digest, "_hydrate_foreign_article", side_effect=lambda item: item):
            self.assertIsNone(digest._find_domestic_beef_article(date(2026, 9, 18), date(2026, 9, 24)))


if __name__ == "__main__":
    unittest.main()
