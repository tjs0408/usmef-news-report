"""Search coverage and local-AI recovery regressions; never contact services."""
from datetime import date
from unittest.mock import Mock, patch
import unittest

from bs4 import BeautifulSoup

from src import livestock_article_draft as d
from src import overseas_article_digest as s

START, END = date(2026, 9, 25), date(2026, 10, 1)


class SearchRecoveryTests(unittest.TestCase):
    def test_api_keeps_market_article_after_first_eight_hits(self):
        items = [{"title": f"Shopping story {i}", "description": "Discovery only", "pubDate": "Wed, 30 Sep 2026 10:00:00 +0900", "originallink": f"https://example.org/{i}"} for i in range(12)]
        with patch.object(s, "_request_json", return_value={"items": items}):
            self.assertEqual(len(s._search_naver_news_api("eggs", START, END, "fake", "fake")), 12)

    def test_bing_reads_explicit_original_url_and_enforces_week(self):
        xml = '<rss><channel><item><title>鶏卵価格が上昇</title><link>https://www.bing.com/news/apiclick.aspx?url=https%3A%2F%2Fexample.jp%2Fnews</link><pubDate>Wed, 30 Sep 2026 08:00:00 GMT</pubDate></item><item><title>Old egg news</title><link>https://example.jp/old</link><pubDate>Wed, 23 Sep 2026 08:00:00 GMT</pubDate></item></channel></rss>'
        with patch.object(s, "_download_html", return_value=xml):
            found = d._public_bing_candidates("鶏卵", d.SPECS_BY_KEY["japan_egg"], START, END)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["url"], "https://example.jp/news")

    def test_generic_market_headline_uses_relevant_lead_not_title_only(self):
        spec = d.SPECS_BY_KEY["eu_pork"]
        article = {"title": "Germany market prices fall as supplies recover", "body": "Germany pork supply and pig production increased, lowering pork prices."}
        self.assertGreater(d._relevance(article, spec), 0)
        article["title"] = "Germany beef prices fall"
        self.assertLess(d._relevance(article, spec), 0)

    def test_domestic_stock_recap_or_local_event_is_not_livestock_news(self):
        for title in ("미국 증시 상승, 물가 안정", "전국 육계인 한자리에"):
            article = {"title": title, "body": "미국 계란과 닭고기 생산 가격 하락 공급 증가. " * 10}
            self.assertLess(d._relevance(article, d.SPECS_BY_KEY["domestic_chicken"]), 0)

    def test_species_excerpt_excludes_other_meat_and_preserves_complete_sentence(self):
        body = "Beef production is up 5 percent in the United States. Egg production fell 7 percent in the United States. Pork supply increased 4 percent."
        excerpt = d._species_excerpt(body, d.SPECS_BY_KEY["us_egg"])
        self.assertIn("Egg production fell 7", excerpt)
        self.assertNotIn("Beef", excerpt)
        self.assertNotIn("Pork", excerpt)
        self.assertTrue(excerpt.endswith("."))

    def test_native_summary_does_not_need_ai(self):
        body = "지난주 미국 돼지고기 생산량은 전주 대비 3.0% 증가한 5억 파운드를 기록했다."
        with patch.object(s, "_ollama_generate") as generate:
            self.assertIn("돼지", s._native_report_sentence("us_pork", body))
            generate.assert_not_called()

    def test_species_excerpt_keeps_tariff_actor_context(self):
        body = "중국은 미국산 의료기기의 관세를 낮출 방침이다. 또 돼지고기 등 총 1619개 미국산 품목의 관세를 인하하기로 했다. 미국은 중국산 장난감 관세를 낮춘다."
        excerpt = d._species_excerpt(body, d.SPECS_BY_KEY["domestic_pork"])
        self.assertIn("중국은", excerpt)
        self.assertIn("돼지고기", excerpt)
        self.assertNotIn("장난감", excerpt)

    def test_english_number_words_are_not_spurious_new_numbers(self):
        self.assertTrue(s._brief_content_supported("유럽 돼지 가격은 7주 연속 상승 이후 하락", "eu_pork", "EU pig prices eased after seven weekly increases."))
        self.assertFalse(s._brief_content_supported("유럽 돼지 가격은 8주 연속 상승 이후 하락", "eu_pork", "EU pig prices eased after seven weekly increases."))

    def test_translation_cannot_invent_weather_or_an_unrelated_product(self):
        body = "Beef production is forecast to rise through improved productivity."
        self.assertFalse(s._brief_content_supported("호주 소고기 생산은 건조한 날씨로 감소", "australia", body))
        self.assertFalse(s._brief_content_supported("브라질 닭고기와 베리 수출 재개 예정", "brazil_chicken", "Brasil pode retomar as exportações de frango e mel."))

    def test_exact_public_statements_translate_without_ai(self):
        cases = [
            ("australia", "Projections estimate the national herd at approximately 30.8 million head in 2026.", "3080만두"),
            ("us_chicken", "Poultry in cold storage was down 4%, with a 5% decline for chicken to 749.919 million pounds.", "7억 4991만 9000"),
            ("us_egg", "Farmgate prices for US shell eggs have fallen to roughly a third of production costs.", "3분의 1"),
            ("eu_pork", "EU pig prices eased last week, ending a run of seven weekly increases.", "7주"),
            ("brazil_chicken", "A UE pode retomar compras de frango do Brasil.", "수입 재개"),
            ("japan_egg", "鶏卵価格、下振れ見通し。生産量が回復。", "하락할 것으로 전망"),
        ]
        for kind, body, expected in cases:
            with self.subTest(kind=kind), patch.object(s, "_ollama_generate") as generate:
                summary = s._native_report_sentence(kind, body)
                self.assertIsNotNone(summary)
                self.assertIn(expected, summary)
                self.assertTrue(s._valid_brief(summary, kind, body))
                generate.assert_not_called()

    def test_related_article_facts_are_not_original_article_evidence(self):
        html = '<html lang="en"><h1>US egg prices drop</h1><article>' + "US egg prices declined and supply increased. " * 4 + 'Related Articles China pig prices rise 50%. Japan chicken production rises 12%.</article></html>'
        candidate = {"title": "US egg prices drop", "url": "https://example.org/egg", "publishedDate": END}
        with patch.object(s, "_download_soup", return_value=BeautifulSoup(html, "html.parser")):
            found = d._original_article(candidate, d.SPECS_BY_KEY["us_egg"])
        self.assertNotIn("50%", found["body"])
        self.assertNotIn("China", found["briefBody"])

    def test_tariff_list_compaction_preserves_actor_species_and_uncertainty(self):
        body = "이번 중국이 관세 인하를 검토하는 미국산 품목 목록에는 쇠고기, 돼지고기, 닭고기 등 농축산물이 포함됐다."
        for kind, product in (("domestic_pork", "돼지고기"), ("domestic_chicken", "닭고기")):
            result = s._native_report_sentence(kind, body)
            self.assertEqual(result, f"중국이 미국산 {product} 등 농축산물이 포함된 품목을 대상으로 관세 인하를 검토")
            self.assertTrue(s._valid_brief(result, kind, body))
        self.assertIsNone(s._grounded_market_statistic("domestic_egg", body))
        self.assertIsNone(s._grounded_market_statistic("domestic_pork", body.replace("포함됐다", "포함되지 않았다")))
        self.assertEqual(s._grounded_market_statistic("domestic_pork", body.replace("검토하는", "검토할").replace("품목", "제품")), "중국이 미국산 돼지고기 등 농축산물이 포함된 품목을 대상으로 관세 인하를 검토")

    def test_contemplated_tariff_cut_does_not_invent_export_growth(self):
        body = "중국은 미국산 의료기기와 장비의 관세를 낮출 방침이다. 또 돼지고기 등 총 1619개 미국산 품목의 관세 인하를 검토한다."
        self.assertFalse(s._brief_content_supported("미국에서 중국으로의 관세 인하로 인해 돼지고기 수출이 증가하고 있다.", "domestic_pork", body))
        self.assertTrue(s._brief_content_supported("중국이 미국산 돼지고기 관세 인하를 검토", "domestic_pork", body))
        # A long numeric continuation must not lose the preceding actor.
        context = "중국은 미국산 자기공명영상과 수술로봇, 초음파진단기 등 의료기기의 관세를 낮출 방침이다."
        excerpt = s._market_fact_excerpt(context + " " + body.split(". ", 1)[1])
        self.assertIn("중국은", excerpt)

    def test_http_encodes_unicode_paths_without_exposing_keys(self):
        response = Mock()
        response.headers.get_content_charset.return_value = "utf-8"
        response.read.return_value = b"public article"
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        with patch.object(s, "urlopen", return_value=response) as opened:
            s._download_html("https://example.jp/卵-unique-test?topic=계란")
        self.assertTrue(opened.call_args.args[0].full_url.isascii())


class OllamaRecoveryTests(unittest.TestCase):
    def test_ready_or_remote_service_does_not_start_a_process(self):
        with patch.object(s, "_ollama_state", return_value={"available": True}), patch.object(s.subprocess, "Popen") as start:
            self.assertTrue(s._ensure_ollama_ready()["available"])
            start.assert_not_called()
        with patch.object(s, "_ollama_state", return_value={"available": False}), patch.object(s, "OLLAMA_BASE_URL", "https://remote.example"), patch.object(s.subprocess, "Popen") as start:
            self.assertFalse(s._ensure_ollama_ready()["available"])
            start.assert_not_called()

    def test_running_server_without_model_is_not_restarted(self):
        with patch.object(s, "_ollama_state", return_value={"available": False}), patch.object(s, "_request_json", return_value={"models": []}), patch.object(s.subprocess, "Popen") as start:
            self.assertFalse(s._ensure_ollama_ready()["available"])
            start.assert_not_called()

    def test_offline_windows_service_starts_existing_cli_hidden(self):
        process = Mock()
        process.poll.return_value = None
        offline, ready = {"available": False}, {"available": True}
        with patch.object(s.os, "name", "nt"), patch.object(s, "_ollama_state", side_effect=[offline, offline, ready]), patch.object(s, "_request_json", side_effect=s.ArticleDigestError("offline")), patch.object(s.shutil, "which", return_value="C:/installed/ollama.exe"), patch.object(s, "_OLLAMA_STARTED_PROCESS", None), patch.object(s.subprocess, "Popen", return_value=process) as start:
            self.assertTrue(s._ensure_ollama_ready()["available"])
        self.assertEqual(start.call_args.args[0], ["C:/installed/ollama.exe", "serve"])
        self.assertEqual(start.call_args.kwargs["creationflags"], s.subprocess.CREATE_NO_WINDOW)
        self.assertEqual(start.call_args.kwargs["env"]["OLLAMA_HOST"], "127.0.0.1:11434")

    def test_image_only_issue_uses_real_heading_positions(self):
        page = Mock()
        page.rect = s.pymupdf.Rect(0, 0, 800, 1200)
        box = lambda y: [[20, y], [200, y], [200, y + 25], [20, y + 25]]
        result = Mock(txts=["미, 소고기 시장동향", "소고기 공급 감소 가격 상승 " * 30, "미, 돼지고기 시장동향", "돼지고기 생산 증가 가격 하락 " * 30], boxes=[box(100), box(150), box(500), box(550)])
        with patch.object(s, "_run_ocr", return_value=result):
            text = s._ocr_usmef_market_sections(page)
        self.assertIn("beef", text)
        self.assertIn("pork", text)
        self.assertNotIn("돼지고기", text["beef"])


if __name__ == "__main__":
    unittest.main()
