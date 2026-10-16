"""Twelve-section source, safety, progress and route regressions; no network/AI."""
from datetime import date
from unittest.mock import patch, Mock, MagicMock
import unittest

from bs4 import BeautifulSoup

import app as web
from src import livestock_article_draft as drafts
from src import overseas_article_digest as source
from src.report_brief_style import SECTION_AUDIENCES, SUMMARY_LIMITS

START, END = date(2026, 9, 25), date(2026, 10, 1)


def article(title="US pork prices rise as supply declines", published=END, **values):
    return {"title": title, "publishedDate": published, "url": "https://example.org/news/market",
            "publisher": "Test", "body": ("US pork supply declines and prices rise with demand. " * 6),
            "sourceLanguage": "en", **values}


class SourceTests(unittest.TestCase):
    def test_twelve_unique_sections_match_prompt_limits(self):
        self.assertEqual(len(drafts.SECTION_SPECS), 12)
        self.assertEqual(len(drafts.SPECS_BY_KEY), 12)
        self.assertEqual(set(drafts.SPECS_BY_KEY), set(SECTION_AUDIENCES))
        self.assertEqual([len(g["sections"]) for g in drafts.SECTION_GROUPS], [3] * 4)
        for spec in drafts.SECTION_SPECS:
            self.assertEqual(SUMMARY_LIMITS[spec.key], 80 if spec.domestic else 95)
        self.assertIn("euromeatnews.com", drafts.SPECS_BY_KEY["eu_pork"].listings[0])
        self.assertIn("avisite.com.br", drafts.SPECS_BY_KEY["brazil_chicken"].listings[0])
        self.assertEqual(drafts.SPECS_BY_KEY["us_egg"].listings[0], drafts.SPECS_BY_KEY["us_chicken"].listings[0])

    def test_dates_use_publication_not_report_or_modified_date(self):
        for text in ("2026-09-30T12:00:00+03:00", "30/09/2026", "２０２６年９月３０日", "2026年 9月 30日", "September 30, 2026", "Wed, 30 Sep 2026 08:00:00 GMT"):
            self.assertEqual(drafts._parse_date(text), date(2026, 9, 30))
        self.assertIsNone(drafts._parse_date("2026-02-31"))
        self.assertIsNone(drafts._parse_date("yesterday"))
        self.assertEqual(source.report_article_window(END), (date(2026, 9, 27), date(2026, 10, 3)))

    def test_wrong_species_pr_and_country_are_rejected(self):
        pork = drafts.SPECS_BY_KEY["eu_pork"]
        self.assertLess(drafts._relevance(article("Germany beef prices rise"), pork), 0)
        self.assertLess(drafts._relevance(article("Germany pork recipe award"), pork), 0)
        self.assertLess(drafts._relevance(article("Brazil pork exports rise", body="Brazil pork exports and production rise"), pork), 0)
        self.assertGreaterEqual(drafts._relevance(article("Germany pork prices rise"), pork), 0)
        egg = article("Poultry egg prices rise", body="Egg prices rise with lower supplies.")
        self.assertLess(drafts._relevance(egg, drafts.SPECS_BY_KEY["us_chicken"], trusted_country=True), 0)
        self.assertGreaterEqual(drafts._relevance(egg, drafts.SPECS_BY_KEY["us_egg"], trusted_country=True), 0)
        brazil = article("Brazil chicken prices rise", body="Brazil chicken supplies decline.")
        self.assertLess(drafts._relevance(brazil, drafts.SPECS_BY_KEY["us_chicken"], trusted_country=True), 0)

    def test_german_issue_outranks_eu_issue(self):
        spec = drafts.SPECS_BY_KEY["eu_pork"]
        german = article("Germany pork prices rise", body="German pork prices rise with lower supplies.")
        other = article("EU pork prices rise", body="EU pork prices rise with lower supplies.")
        self.assertGreater(drafts._relevance(german, spec), drafts._relevance(other, spec))

    def test_domestic_requires_overseas_market_event(self):
        spec = drafts.SPECS_BY_KEY["domestic_egg"]
        good = article("미국 계란 가격 급등, 공급 부족", body="미국 계란 생산 감소와 공급 부족으로 계란 가격 상승이 지속됐다.")
        self.assertGreater(drafts._relevance(good, spec), 0)
        self.assertLess(drafts._relevance({**good, "title": "국내 계란 가격 급등"}, spec), 0)
        self.assertLess(drafts._relevance({**good, "title": "미국 계란 요리 레시피 소개"}, spec), 0)

    def test_rss_uses_original_date_and_links_not_snippets(self):
        xml = '''<rss><channel><item><title>US egg prices rise</title><link>https://example.org/current</link><pubDate>Wed, 30 Sep 2026 08:00:00 GMT</pubDate><description>Discovery snippet</description></item><item><title>Old egg prices</title><link>https://example.org/old</link><pubDate>Wed, 23 Sep 2026 08:00:00 GMT</pubDate></item></channel></rss>'''
        found = drafts._feed_candidates(xml, "https://example.org/feed/", drafts.SPECS_BY_KEY["us_egg"], START, END)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["publishedDate"], date(2026, 9, 30))
        self.assertEqual(found[0]["url"], "https://example.org/current")

    def test_original_metadata_date_overrides_search_date(self):
        html = '''<html lang="en"><meta property="article:published_time" content="2026-09-20"><h1>US pork prices rise</h1><article>''' + "Pork supply and prices changed. " * 10 + "</article></html>"
        with patch.object(source, "_download_soup", return_value=BeautifulSoup(html, "html.parser")):
            found = drafts._original_article(article(), drafts.SPECS_BY_KEY["us_pork"])
            self.assertEqual(found["publishedDate"], date(2026, 9, 20))
            self.assertIsNone(drafts._choose_original([article()], drafts.SPECS_BY_KEY["us_pork"], START, END))

    def test_original_language_body_and_missing_date(self):
        spec = drafts.SPECS_BY_KEY["japan_egg"]
        html = '<html lang="ja"><h1>日本の鶏卵価格が上昇</h1><div class="content-main cms-article">' + "鶏卵の供給が減少して価格が上昇しています。" * 10 + "</div></html>"
        with patch.object(source, "_download_soup", return_value=BeautifulSoup(html, "html.parser")):
            found = drafts._original_article(article(), spec)
            self.assertEqual(found["sourceLanguage"], "ja")
            self.assertFalse(found["searchResult"])
            self.assertIsNone(drafts._original_article({"url": "https://example.org/no-date"}, spec))
        html = html.replace('lang="ja"', 'lang="zh"')
        with patch.object(source, "_download_soup", return_value=BeautifulSoup(html, "html.parser")):
            self.assertIsNone(drafts._original_article(article(), spec))

    def test_preferred_source_then_search_only_when_missing(self):
        spec = drafts.SPECS_BY_KEY["eu_pork"]
        with patch.object(drafts, "_preferred_site_article", return_value=article()) as preferred, patch.object(drafts, "_search_article") as search:
            self.assertEqual(drafts._find_section(spec, START, END)["sourceMethod"], "preferred")
            preferred.assert_called_once()
            search.assert_not_called()
        with patch.object(drafts, "_preferred_site_article", return_value=None), patch.object(drafts, "_search_article", return_value=article()) as search:
            self.assertEqual(drafts._find_section(spec, START, END)["sourceMethod"], "search")
            search.assert_called_once()

    def test_source_outage_falls_back_then_reports_safe_reason(self):
        spec = drafts.SPECS_BY_KEY["brazil_chicken"]
        with patch.object(drafts, "_preferred_site_article", side_effect=source.ArticleDigestError("upstream")), patch.object(drafts, "_search_article", return_value=article()):
            self.assertEqual(drafts._find_section(spec, START, END)["sourceMethod"], "search")
        with patch.object(source, "_download_soup", side_effect=source.ArticleDigestError("upstream")), patch.object(drafts, "_search_article", return_value=None):
            with self.assertRaisesRegex(drafts.SourceUnavailable, "AviSite 원문 연결 실패"):
                drafts._find_section(spec, START, END)

    def test_japanese_news_pdf_uses_listing_title_and_date(self):
        spec = drafts.SPECS_BY_KEY["japan_egg"]
        html = '<li><a href="/report.pdf"><div class="date">2026.09.30</div><div class="category">ニュース</div><div class="title">鶏卵の流通状況および相場情報について</div></a></li><li><a href="/old.pdf"><div class="date">2026.09.09</div><div class="title">鶏卵価格</div></a></li>'
        found = drafts._listing_candidates(BeautifulSoup(html, "html.parser"), spec.listings[1], spec, START, END)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["title"], "鶏卵の流通状況および相場情報について")
        self.assertEqual(found[0]["publishedDate"], date(2026, 9, 30))
        with patch.object(drafts, "_public_pdf_text", return_value="日本の鶏卵の供給と価格が変化しています。" * 10):
            original = drafts._original_article(found[0], spec)
            self.assertEqual(original["sourceLanguage"], "ja")
            self.assertFalse(original["headlineOnly"])
            self.assertFalse(original["searchResult"])
            self.assertIsNone(drafts._original_article({**found[0], "publishedDate": None}, spec))
        with patch.object(drafts, "_public_pdf_text", return_value="Unreadable PDF " * 10):
            self.assertIsNone(drafts._original_article(found[0], spec))

    def test_domestic_uses_naver_before_google(self):
        spec = drafts.SPECS_BY_KEY["domestic_pork"]
        with patch.object(source, "_search_naver_news", return_value=[article()]) as naver, patch.object(source, "_search_google_news_rss") as google, patch.object(drafts, "_choose_original", return_value=article()):
            self.assertIsNotNone(drafts._search_article(spec, START, END))
            self.assertEqual(naver.call_count, len(spec.queries + drafts.SEARCH_QUERIES[spec.key]))
            google.assert_not_called()

    def test_google_rss_xml_preserves_title_and_date(self):
        xml = '''<rss><channel><item><title>Egg prices - supply falls - Publisher</title><link>https://example.org/news</link><pubDate>Wed, 30 Sep 2026 08:00:00 GMT</pubDate><source url="https://example.org/">Publisher</source></item></channel></rss>'''
        with patch.object(source, "_download_html", return_value=xml):
            found = source._search_google_news_rss("eggs", START, END)
        self.assertEqual(found[0]["title"], "Egg prices - supply falls")
        self.assertEqual(found[0]["publisherUrl"], "https://example.org/")

    def test_foreign_numeric_units_and_decimal_validation(self):
        self.assertTrue(source._brief_content_supported("닭고기 생산량 340만톤으로 증가", "brazil_chicken", "produção de frango 3,4 milhões toneladas"))
        self.assertTrue(source._brief_content_supported("닭고기 수출량 1234.56톤으로 증가", "brazil_chicken", "exportações de frango 1.234,56 toneladas"))
        self.assertTrue(source._brief_content_supported("계란 생산량 300만개로 증가", "japan_egg", "鶏卵生産量は300万個"))
        self.assertFalse(source._brief_content_supported("계란 가격이 25% 상승", "us_egg", "Egg prices rise 5%"))


class CollectorTests(unittest.TestCase):
    def test_all_sections_partial_results_and_failure_isolation(self):
        events = []
        def find(spec, start, end):
            if spec.key == "brazil_chicken":
                raise RuntimeError("source unavailable")
            if spec.domestic:
                species = {'beef': '쇠고기', 'pork': '돼지고기', 'chicken': '닭고기', 'egg': '계란'}[spec.species]
                return article(title=f'미국 {species} 공급 감소와 수요 동향 분석',
                               url=f'https://example.org/news/{spec.key}', sourceLanguage='ko',
                               body=f'미국 {species} 시장의 공급과 수요 변화를 살펴봤다. ' * 6)
            return article()
        def summarize(kind, title, body):
            if kind == "us_egg":
                raise source.ArticleDigestError("invalid summary")
            return "공급 감소로 가격 상승이 지속"
        with patch.object(drafts, "_usmef_pair", return_value={"us": article(), "us_pork": article()}), patch.object(drafts, "_find_section", side_effect=find), patch.object(drafts, "_search_article", return_value=None), patch.object(source, "_ollama_state", return_value={"available": True}), patch.object(source, "_summarize_report_sentence", side_effect=summarize) as summary:
            result = drafts.collect_weekly_livestock_report_draft(END, progress=lambda **event: events.append(event))
        self.assertEqual(result["totalCount"], 12)
        self.assertEqual(len(result["sections"]), 12)
        self.assertEqual(result["readyCount"], 10)
        self.assertEqual(result["sections"]["brazil_chicken"]["status"], "source_error")
        self.assertEqual(result["sections"]["us_egg"]["status"], "summary_error")
        self.assertEqual(summary.call_count, 11)
        self.assertEqual([event["progress"] for event in events], sorted(event["progress"] for event in events))
        self.assertTrue(any(0 < event["readyCount"] < 10 for event in events))

    def test_one_us_fallback_failure_preserves_other_us_source(self):
        with patch.object(drafts, "_usmef_pair", return_value={"us": article()}), patch.object(drafts, "_search_article", side_effect=RuntimeError("failed")), patch.object(drafts, "_find_section", return_value=None), patch.object(source, "_ollama_state", return_value={"available": False, "message": "offline"}):
            result = drafts.collect_weekly_livestock_report_draft(END)
        self.assertIsNotNone(result["sections"]["us"]["article"])
        self.assertIsNone(result["sections"]["us_pork"]["article"])
        self.assertEqual(result["sections"]["us"]["status"], "model_unavailable")

    def test_usmef_never_reuses_previous_week(self):
        html = '''<a class="board_content" href="javascript:sampleOpenWin('https://usmef.co.kr/ebook/newsline/2026/20260923/20260923.pdf')">Old newsline</a>'''
        with patch.object(source, "_download_soup", return_value=BeautifulSoup(html, "html.parser")), patch.object(source, "_extract_usmef_market_texts") as extract:
            self.assertEqual(drafts._usmef_pair(START, END), {})
            extract.assert_not_called()

    def test_shared_pdf_native_headings_read_once_for_both_species(self):
        source._extract_usmef_market_texts.cache_clear()
        page = Mock()
        page.rect = source.pymupdf.Rect(0, 0, 1000, 8000)
        page.get_text.side_effect = lambda mode, **kwargs: (
            [(0, 500, 500, 550, "소고기 시장동향"), (0, 3000, 500, 3050, "돼지고기 시장동향"),
             (0, 5000, 500, 5050, "돼지고기 컷아웃 주간 가격")]
            if mode == "blocks" else ("소고기 공급 감소와 가격 상승 " * 30 if kwargs["clip"].y0 == 550 else "돼지고기 생산 증가와 가격 하락 " * 30)
        )
        document = MagicMock()
        document.__enter__.return_value = document
        document.__iter__.side_effect = lambda: iter([page])
        with patch.object(source, "_download_bytes", return_value=b"public pdf") as download, patch.object(source.pymupdf, "open", return_value=document):
            first = source._extract_usmef_market_texts("https://example.org/shared.pdf")
            second = source._extract_usmef_market_texts("https://example.org/shared.pdf")
        self.assertIn("소고기", first["beef"])
        self.assertIn("돼지고기", first["pork"])
        self.assertEqual(first, second)
        download.assert_called_once()
        page.get_pixmap.assert_not_called()
        source._extract_usmef_market_texts.cache_clear()

    def test_safe_source_error_is_visible_but_unknown_errors_are_sanitized(self):
        def find(spec, start, end):
            if spec.key == "brazil_chicken":
                raise drafts.SourceUnavailable("AviSite 원문 연결 실패 · 보완 검색 실패")
            if spec.key == "us_egg":
                raise RuntimeError("private request details")
            return None
        with patch.object(drafts, "_usmef_pair", return_value={}), patch.object(drafts, "_search_article", return_value=None), patch.object(drafts, "_find_section", side_effect=find), patch.object(source, "_ollama_state", return_value={"available": False, "message": "offline"}):
            result = drafts.collect_weekly_livestock_report_draft(END)
        self.assertIn("AviSite", result["sections"]["brazil_chicken"]["errors"][0])
        self.assertNotIn("private", str(result))


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.client = web.app.test_client()
        self.jobs = patch.object(web, "ARTICLE_JOBS", {})
        self.jobs.start()
        self.cancellations = patch.object(web, "ARTICLE_CANCELLED_REQUESTS", {})
        self.cancellations.start()

    def tearDown(self):
        self.jobs.stop()
        self.cancellations.stop()

    def test_rendered_page_has_twelve_cards(self):
        soup = BeautifulSoup(self.client.get("/").get_data(as_text=True), "html.parser")
        self.assertEqual(len(soup.select("[data-article-kind]")), 12)
        self.assertEqual(len(soup.select(".livestock-draft-group")), 4)

    def test_invalid_date_unknown_job_and_duplicate_job(self):
        self.assertEqual(self.client.post("/start-article-draft", json={"reportDate": "bad"}).status_code, 400)
        self.assertEqual(self.client.get("/article-draft-status/missing").status_code, 404)
        with patch.object(web, "Thread") as thread:
            response = self.client.post("/start-article-draft", json={"reportDate": END.isoformat()})
            self.assertEqual(response.status_code, 202)
            waiting = self.client.get(f'/article-draft-status/{response.json["jobId"]}').json
            self.assertEqual(len(waiting["sections"]), 12)
            self.assertTrue(all(section["status"] == "finding" for section in waiting["sections"].values()))
            self.assertEqual(self.client.post("/start-article-draft", json={"reportDate": END.isoformat()}).status_code, 409)
            thread.return_value.start.assert_called_once()

    def test_worker_progress_does_not_regress_and_status_has_duration(self):
        with patch.object(web, "Thread"):
            job_id = self.client.post("/start-article-draft", json={"reportDate": END.isoformat()}).json["jobId"]
        def collect(report_date, progress, *, cancel_event=None):
            progress(progress=70, stage=3, sections={"us": {"summary": "가격 상승"}})
            progress(progress=60, stage=2, sections={"us": {"summary": "가격 상승"}})
            job = self.client.get(f"/article-draft-status/{job_id}").json
            self.assertEqual(job["progress"], 70)
            self.assertEqual(job["stage"], 3)
            self.assertIn("elapsedSeconds", job)
            self.assertNotIn("startedAt", job)
            return {"sections": job["sections"], "message": "done", "readyCount": 1, "candidatesFound": 1}
        with patch.object(web, "collect_weekly_livestock_report_draft", side_effect=collect):
            web._run_article_job(job_id, END)
        job = self.client.get(f"/article-draft-status/{job_id}").json
        self.assertEqual(job["progress"], 100)
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["readyCount"], 1)


if __name__ == "__main__":
    unittest.main()
