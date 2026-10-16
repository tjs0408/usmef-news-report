"""Regression checks for optimizations; no network, AI or Office required."""
from datetime import date
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from src import overseas_article_digest as digest
from src.excel_charts import chart_specs, read_chart_exports, record_chart_exports
from src.runtime_cache import ttl_cache
from src.xlsx_values import read_cached_sheets


class CacheTests(unittest.TestCase):
    def test_expiry_and_mutable_isolation(self):
        calls = []
        @ttl_cache(seconds=5, maxsize=2)
        def read(key):
            calls.append(key)
            return {"items": [key]}
        with patch("src.runtime_cache.monotonic", return_value=10):
            read("a")["items"].append("bad mutation")
            self.assertEqual(read("a"), {"items": ["a"]})
            self.assertEqual(calls, ["a"])
        with patch("src.runtime_cache.monotonic", return_value=16):
            read("a")
            self.assertEqual(calls, ["a", "a"])

    def test_failures_not_cached(self):
        calls = []
        @ttl_cache(seconds=5)
        def read():
            calls.append(1)
            raise RuntimeError("unavailable")
        for _ in range(2):
            with self.assertRaises(RuntimeError):
                read()
        self.assertEqual(len(calls), 2)

    def test_validated_summary_reused_but_changed_body_recomputed(self):
        digest._summarize_report_sentence.cache_clear()
        body = "미국 소고기 가격은 수급 변화에 따라 상승세를 보이며 높은 가격 수준을 유지"
        try:
            with patch.object(digest, "_native_report_sentence", return_value=None), patch.object(digest, "_summarize_usmef_market_sentence", return_value=body) as generate:
                self.assertEqual(digest._summarize_report_sentence("us", "기사", body), body)
                self.assertEqual(digest._summarize_report_sentence("us", "기사", body), body)
                self.assertEqual(generate.call_count, 1)
                digest._summarize_report_sentence("us", "기사", body + " 지속")
                self.assertEqual(generate.call_count, 2)
        finally:
            digest._summarize_report_sentence.cache_clear()


class ArticleParallelTests(unittest.TestCase):
    def test_independent_finders_overlap(self):
        barrier = Barrier(3)
        def find(start, end):
            barrier.wait(timeout=2)
            return {"title": "소고기 가격 상승", "body": "소고기 공급 감소로 가격 상승",
                    "url": "https://example.org/market", "publishedDate": end, "publisher": "Test"}
        with patch.object(digest, "_find_us_beef_headline", side_effect=find), \
             patch.object(digest, "_find_australia_beef_article", side_effect=find), \
             patch.object(digest, "_find_domestic_beef_article", side_effect=find), \
             patch.object(digest, "_ollama_state", return_value={"available": True}), \
             patch.object(digest, "_summarize_report_sentence", return_value="소고기 공급 감소로 가격 상승") as summarize:
            result = digest.collect_weekly_beef_report_draft(date(2026, 9, 24))
            self.assertEqual(set(result["sections"]), {"us", "australia", "domestic"})
            self.assertEqual(summarize.call_count, 3)

    def test_mla_skips_events_and_out_of_week_cards(self):
        from bs4 import BeautifulSoup
        html = '''<a href="/news-and-events/events-and-workshops/?topics=cattle">Cattle market event</a>
          <div class="item-news"><a class="item-news__link" href="/news-and-events/industry-news/past/">Beef supply falls</a><span>04 Sept 2026</span></div>
          <div class="item-news"><a class="item-news__link" href="/news-and-events/industry-news/current/">Beef supply falls</a><span>23 Sept 2026</span></div>'''
        article = {"title": "Beef supply falls", "briefBody": "Cattle slaughter and beef price change with supply",
                   "publishedDate": date(2026, 9, 23)}
        with patch.object(digest, "_download_soup", return_value=BeautifulSoup(html, "html.parser")), \
             patch.object(digest, "_fetch_mla_article", return_value=article) as fetch:
            self.assertEqual(digest._find_mla_latest_news_article(date(2026, 9, 18), date(2026, 9, 24)), article)
            self.assertEqual(fetch.call_count, 1)
            self.assertTrue(fetch.call_args.args[0].endswith("/current/"))


class WorkbookCacheTests(unittest.TestCase):
    def test_chart_exports_rejected_after_workbook_changes(self):
        with TemporaryDirectory() as folder:
            directory = Path(folder)
            workbook = directory / "source.xlsx"
            workbook.write_bytes(b"workbook")
            for spec in chart_specs():
                (directory / spec["outputName"]).write_bytes(b"image")
            record_chart_exports(directory, workbook)
            self.assertEqual(len(read_chart_exports(directory, workbook)), 6)
            workbook.write_bytes(b"new workbook")
            self.assertIsNone(read_chart_exports(directory, workbook))
            self.assertIsNone(read_chart_exports(None, workbook))

    def test_cached_cell_types_and_selected_rows(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "values.xlsx"
            with ZipFile(path, "w") as z:
                ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
                z.writestr("xl/workbook.xml", f'<workbook xmlns="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="report" sheetId="1" r:id="r1"/></sheets></workbook>')
                z.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="r1" Target="worksheets/sheet1.xml"/></Relationships>')
                z.writestr("xl/sharedStrings.xml", f'<sst xmlns="{ns}"><si><r><t>보고</t></r><r><t>일자</t></r></si></sst>')
                z.writestr("xl/worksheets/sheet1.xml", f'''<worksheet xmlns="{ns}"><sheetData>
                  <row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="inlineStr"><is><t>2026-9-24</t></is></c>
                    <c r="C1"><f>1/10</f><v>0.1</v></c><c r="D1" t="str"><f>TEXT(1)</f><v>9월 3주</v></c>
                    <c r="E1" t="e"><v>#N/A</v></c><c r="F1" t="b"><v>1</v></c><c r="G1"><f>1</f></c></row>
                  <row r="2"><c r="XFD2"><v>123</v></c></row></sheetData></worksheet>''')
            sheet = read_cached_sheets(path, {"report": {1}})["report"]
            self.assertEqual([sheet.cell(1, i).value for i in range(1, 8)],
                             ["보고일자", "2026-9-24", .1, "9월 3주", "#N/A", True, None])
            self.assertEqual(sheet.max_column, 6)


if __name__ == "__main__":
    unittest.main()
