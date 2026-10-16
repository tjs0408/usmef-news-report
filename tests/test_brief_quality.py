"""Regression cases for the user's Sept 24 screenshot; no external services."""
import unittest
from datetime import date
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

from src import livestock_article_draft as d
from src import overseas_article_digest as s


class BriefQualityTests(unittest.TestCase):
    def test_incubation_sentence_survives_extraction_and_is_translated_exactly(self):
        body = "The USDA says 247.786 million broiler-type eggs went into incubation, an increase of 2.564 million on the week, and up 2% on the year."
        excerpt = d._species_excerpt(body, d.SPECS_BY_KEY['us_chicken'])
        self.assertEqual(excerpt, body)
        result = s._native_report_sentence('us_chicken', excerpt)
        self.assertIn('2억 4778만 6000개', result)
        self.assertIn('256만 4000개 증가', result)
        self.assertFalse(s._is_valid_korean_report_sentence('미국 닭 가etting이 줄어들었다.'))
        self.assertTrue(s._is_valid_korean_report_sentence('EU의 돼지고기 가격은 상승'))

    def test_eu_slaughter_and_pork_price_do_not_reverse_direction(self):
        body = "Pig slaughterings in the European Union rose by 1.6% in the first half of 2026 compared to the same period of the previous year. Denmark recorded the strongest increase. From January to June, 8.3% more pigs were slaughtered there than in the first half of 2025. In its short-term outlook, the EU Commission expects a decline in the number of pigs slaughtered in the second half of 2026 compared to the previous year."
        result = s._native_report_sentence('eu_pork', body)
        self.assertIn('1.6% 증가', result)
        self.assertNotIn('8.3%', result)
        self.assertIn('감소 전망', result)
        body = '돼지고기 컷아웃 지난주 돼지고기 컷아웃 가격은 전주 대비 4.5%(-0.04달러) 하락한 0.88달러를 기록했다.'
        result = s._native_report_sentence('us_pork', body)
        self.assertIn('4.5% 하락한 0.88달러', result)
        self.assertFalse(s._valid_brief(result.replace('하락', '상승'), 'us_pork', body))

    def test_historical_week_search_pages_without_widening_dates(self):
        recent = [{"title": "미국 계란 가격 상승", "originallink": f"https://example.org/new/{i}",
                   "pubDate": "Wed, 30 Sep 2026 08:00:00 +0900"} for i in range(100)]
        target = {"title": "미국 계란 공급 감소", "originallink": "https://example.org/week",
                  "pubDate": "Mon, 21 Sep 2026 08:00:00 +0900"}
        old = {**target, "originallink": "https://example.org/old", "pubDate": "Thu, 17 Sep 2026 08:00:00 +0900"}
        with patch.object(s, "_request_json", side_effect=[{"items": recent}, {"items": [target, old]}]) as request:
            found = s._search_naver_news_api("미국 계란", date(2026, 9, 18), date(2026, 9, 24), "test", "test")
        self.assertEqual([item["url"] for item in found], [target["originallink"]])
        self.assertEqual([parse_qs(urlparse(call.args[0]).query)["start"] for call in request.call_args_list], [["1"], ["101"]])

    def test_publisher_ai_summary_is_not_original_reporting(self):
        html = '<html lang="ko"><time datetime="2026-09-24"></time><h1>백악관 쇠고기 수입 정책 검토</h1><article><section id="aiSummary" class="ai-summary">AI 핵심 요약: 쇠고기 수입 철회가 확정됐다.</section><div id="news-contents"><p>미국 백악관은 쇠고기 수입 확대 조치의 축소를 검토 중이다.</p><p>미국의 쇠고기 가격 인하를 위해 수입을 늘렸으나 농가의 반대가 커지고 있다.</p><p>미국 무역대표부는 소비자 쇠고기 가격을 낮추기 위해 정책 철회에 반대했다.</p></div></article></html>'
        with patch.object(s, "_download_soup", return_value=BeautifulSoup(html, "html.parser")):
            original = d._original_article({"url": "https://example.org/news"}, d.SPECS_BY_KEY["domestic"])
        self.assertNotIn("확정", original["body"])
        self.assertGreater(d._relevance(original, d.SPECS_BY_KEY["domestic"]), 0)

    def test_tentative_import_policy_keeps_review_not_realized_effect(self):
        body = '백악관이 지난 8월 확대했던 외국산 저지방 쇠고기의 수입 물량을 축소하거나 철회하는 방안을 검토 중인 것으로 알려졌다.'
        summary = s._native_report_sentence('domestic', body)
        self.assertIn('축소·철회를 검토', summary)
        self.assertNotIn('감소했다', summary)
        denied = body.replace('검토 중인', '검토하지 않았다고 부인한')
        self.assertIsNone(s._grounded_market_statistic('domestic', denied))
        preserved = s._native_report_sentence('domestic', denied)
        self.assertTrue(preserved is None or '검토하지' in preserved)

    def test_public_publisher_search_form_finds_specific_broiler_story(self):
        spec = d.SPECS_BY_KEY["us_chicken"]
        index = BeautifulSoup('<form method="get" action="https://www.brownfieldagnews.com/"><input name="s"></form>', "html.parser")
        result = BeautifulSoup('<div><h2><a href="/news/broiler">Broiler sets increased on week</a></h2><time datetime="2026-09-23"></time></div>', "html.parser")
        downloaded = []
        def get_page(url):
            downloaded.append(url)
            return result if "s=broiler" in url else index
        with patch.object(s, "_download_soup", side_effect=get_page), patch.object(d, "_choose_original", return_value={"ok": True}) as choose:
            d._preferred_site_article(spec, date(2026,9,18), date(2026,9,24))
        self.assertIn("https://www.brownfieldagnews.com/?s=broiler", downloaded)
        self.assertIn("Broiler sets increased on week", [item["title"] for item in choose.call_args.args[0]])

    def test_price_is_not_a_headcount_or_a_different_period(self):
        body = "The national cattle yarding lifted 4% week-on-week (WoW) to 72,529 head."
        correct = s._native_report_sentence("australia", body)
        self.assertIn("출하두수", correct)
        self.assertIn("7만 2529두", correct)
        self.assertTrue(s._valid_brief(correct, "australia", body))
        for wrong in ("호주 소 판매가는 전주비 4% 상승한 72,529마리를 기록", "호주 소 출하두수는 전년비 4% 증가한 72,529두를 기록", "호주 소 출하두수는 전주비 4% 감소한 72,529두를 기록"):
            self.assertFalse(s._brief_content_supported(wrong, "australia", body), wrong)

    def test_egg_quantity_and_direction_are_bound_to_the_original_fact(self):
        body = "9.43 billion eggs were produced last month, rising 5% on the year."
        correct = s._native_report_sentence("us_egg", body)
        self.assertIn("94억 3000만개", correct)
        self.assertTrue(s._valid_brief(correct, "us_egg", body))
        self.assertFalse(s._valid_brief(correct.replace("증가", "감소"), "us_egg", body))
        self.assertFalse(s._valid_brief(correct.replace("전년비", "전주비"), "us_egg", body))
        self.assertFalse(s._valid_brief(correct.replace("만개", "만마리"), "us_egg", body))

    def test_ocr_headings_and_cumulative_clause_are_not_the_brief(self):
        body = "돼지고기생산량, 도축두수및중량 지난주 돼지고기 생산량은 노동절(Labor Day, 9월 7일) 휴일이 포함되었던 전주 대비 9.7%증가했으나 전년 대비로는 4.3% 감소한 5억 2,850만 파운드를 기록했고,2026 년누계 기준으로는 2025년 대비 0.5%증가했다."
        result = s._native_report_sentence("us_pork", body)
        self.assertIsNotNone(result)
        self.assertNotIn("도축두수", result)
        self.assertNotIn("누계", result)
        self.assertIn("5억 2,850만", result)

    def test_korean_court_ruling_is_not_an_overseas_egg_event(self):
        article = {"title": "산란계협회 계란 가격정보 처분 집행정지", "body": "한국 법원은 국내 계란 가격정보 공개를 허용했다. 계란 수급과 공급 부족 문제를 고려했다. 미국과 일본도 계란가격을 공개한다."}
        self.assertLess(d._relevance(article, d.SPECS_BY_KEY["domestic_egg"]), 0)
        article = {"title": "공급 부족에 계란 가격 급등", "body": "미국의 계란 공급 감소로 계란가격이 10% 상승했다. 미국 산란계 사육두수 감소가 계란 공급에 영향을 주고 있다."}
        self.assertGreater(d._relevance(article, d.SPECS_BY_KEY["domestic_egg"]), 0)

    def test_imported_meat_holiday_promotions_are_not_overseas_news(self):
        body = "미국과 호주산 소고기, 미국산 돼지고기는 국내 소비자를 위해 수입됐다. 소고기와 돼지고기 가격을 낮추고 공급을 확대하기 위한 행사다."
        for key, title in (("domestic", '"호주산 소고기 30%↓" 이마트 추석 먹거리 할인'),
                           ("domestic_pork", '한우 대신 미국산…고물가가 바꾼 추석 차례상')):
            self.assertLess(d._relevance({"title": title, "body": body}, d.SPECS_BY_KEY[key]), 0)

    def test_user_post_about_taiwan_is_not_japanese_local_news(self):
        article = {"url": "https://note.com/writer/post", "title": "台湾の鶏卵企業買収の背景", "body": "日本企業は台湾の鶏卵生産と価格を調査した。" * 10}
        self.assertLess(d._relevance(article, d.SPECS_BY_KEY["japan_egg"], trusted_country=True), 0)
        article["url"] = "https://example.jp/news"
        self.assertLess(d._relevance(article, d.SPECS_BY_KEY["japan_egg"], trusted_country=True), 0)

    def test_identified_japanese_local_news_does_not_need_japan_in_headline(self):
        article = {'url': 'https://times.abema.tv/articles/market', 'title': '豚肉・卵が最高値',
                   'body': '今週発表された豚肉と卵の平均価格は過去最高を更新。'}
        self.assertGreater(d._relevance(article, d.SPECS_BY_KEY['japan_egg']), 0)
        summary = s._native_report_sentence('japan_egg', article['body'])
        self.assertIn('역대 최고치를 경신', summary)
        self.assertIn('이번 주 발표', summary)
        self.assertTrue(s._valid_brief(summary, 'japan_egg', article['body']))
        article['url'] = 'https://example.org/user/post'
        self.assertLess(d._relevance(article, d.SPECS_BY_KEY['japan_egg']), 0)

    def test_model_cannot_borrow_unit_or_direction_from_another_sentence(self):
        body = "Egg prices rose 5%. The total laying flock was 72,529 head."
        with patch.object(s, "_ollama_generate", return_value={"response": "미국 계란 가격은 5% 상승한 72,529마리를 기록"}):
            with self.assertRaises(s.ArticleDigestError):
                s._extract_report_facts(audience="미국 계란", title="Egg prices", body=body, headline_only=False, search_result=False)


if __name__ == "__main__":
    unittest.main()
