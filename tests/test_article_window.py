"""Sunday-to-Saturday article windows; never change Excel report dates."""
from datetime import date, timedelta
from unittest.mock import patch
import unittest

from bs4 import BeautifulSoup
from src import overseas_article_digest as source
from src import livestock_article_draft as drafts


REPORT_DAY = date(2026, 10, 1)
START, END = date(2026, 9, 27), date(2026, 10, 3)
OFFLINE = {"available": False, "message": "offline"}


class ArticleWindowTests(unittest.TestCase):
    def test_user_example_and_all_days_in_same_week(self):
        for offset in range(7):
            selected = START + timedelta(days=offset)
            with self.subTest(selected=selected):
                self.assertEqual(source.report_article_window(selected), (START, END))
        self.assertGreater(END, REPORT_DAY, "Friday/Saturday after the report day stay in the window")

    def test_month_year_and_leap_day_boundaries(self):
        for selected, expected in (
            (date(2026, 12, 31), (date(2026, 12, 27), date(2027, 1, 2))),
            (date(2027, 1, 1), (date(2026, 12, 27), date(2027, 1, 2))),
            (date(2028, 2, 29), (date(2028, 2, 27), date(2028, 3, 4))),
        ):
            with self.subTest(selected=selected):
                start, end = source.report_article_window(selected)
                self.assertEqual((start, end), expected)
                self.assertEqual(start.weekday(), 6)
                self.assertEqual(end.weekday(), 5)
                self.assertEqual((end - start).days, 6)

    def test_all_twelve_sections_and_fallbacks_receive_same_period(self):
        with patch.object(source, "_ensure_ollama_ready", return_value=OFFLINE), \
             patch.object(drafts, "_usmef_pair", return_value={}) as us, \
             patch.object(drafts, "_search_article", return_value=None) as fallback, \
             patch.object(drafts, "_find_section", return_value=None) as other:
            result = drafts.collect_weekly_livestock_report_draft(REPORT_DAY)
        us.assert_called_once_with(START, END)
        self.assertEqual(other.call_count, 10)
        self.assertEqual(fallback.call_count, 2)
        for call in other.call_args_list + fallback.call_args_list:
            self.assertEqual(call.args[1:3], (START, END))
        self.assertEqual(result["reportDate"], "2026-10-01")
        self.assertEqual(result["weekStart"], "2026-09-27")
        self.assertEqual(result["weekEnd"], "2026-10-03")

    def test_older_three_section_and_domestic_routes_use_shared_window(self):
        with patch.object(source, "_ollama_state", return_value=OFFLINE), \
             patch.object(source, "_find_us_beef_headline", return_value=None) as us, \
             patch.object(source, "_find_australia_beef_article", return_value=None) as au, \
             patch.object(source, "_find_domestic_beef_article", return_value=None) as domestic, \
             patch.object(source, "_find_best_article", return_value=(None, [], True)) as best:
            beef = source.collect_weekly_beef_report_draft(REPORT_DAY)
            korean = source.collect_weekly_article_summaries(REPORT_DAY)
        for finder in (us, au, domestic):
            finder.assert_called_once_with(START, END)
        for call in best.call_args_list:
            self.assertEqual(call.args[1:3], (START, END))
        for result in (beef, korean):
            self.assertEqual(result["weekStart"], "2026-09-27")
            self.assertEqual(result["weekEnd"], "2026-10-03")

    def test_usmef_accepts_sunday_and_saturday_but_not_adjacent_weeks(self):
        for stamp, accepted in (("20260926", False), ("20260927", True), ("20261003", True), ("20261004", False)):
            with self.subTest(published=stamp):
                url = f"https://usmef.co.kr/ebook/newsline/2026/{stamp}/{stamp}.pdf"
                html = f'''<a class="board_content" href="javascript:sampleOpenWin('{url}')">Market report</a>'''
                with patch.object(source, "_download_soup", return_value=BeautifulSoup(html, "html.parser")), \
                     patch.object(source, "_extract_usmef_market_texts", return_value={"beef": "소고기 시장 공급 동향 " * 30}) as extract:
                    found = drafts._usmef_pair(START, END)
                self.assertEqual(bool(found), accepted)
                self.assertEqual(extract.call_count, int(accepted))

    def test_google_exclusive_bounds_include_both_week_endpoints(self):
        with patch.object(source, "_download_html", return_value="<rss><channel/></rss>") as html:
            source._search_google_news_rss("eggs", START, END)
        from urllib.parse import parse_qs, urlparse
        query = parse_qs(urlparse(html.call_args.args[0]).query)["q"][0]
        self.assertIn("after:2026-09-26", query)
        self.assertIn("before:2026-10-04", query)


if __name__ == "__main__":
    unittest.main()
