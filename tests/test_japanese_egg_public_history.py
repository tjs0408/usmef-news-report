from datetime import date
import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup

from src import livestock_article_draft as d
from src import overseas_article_digest as summaries


START, END = date(2026, 10, 11), date(2026, 10, 17)
BASE = d.JAPANESE_EGG_MARKET_URL


def quotation(day=16, *, price="315", arrivals="760", search=True, action=BASE,
              unit="単位 円 / kg"):
    form = (f'<form id="day_search" action="{action}" method="post">'
            '<input name="souba_day" type="text" readonly></form>') if search else ""
    return BeautifulSoup(f'''<html lang="ja">{form}
      <link rel="canonical" href="{BASE}">
      <p class="publication-date">2026年10月{day}日(金) 09:00 発表</p>
      <div id="tokyo"><table><thead><tr><th>東 京</th><th>高値</th>
      <th colspan="2">基準値</th><th>安値</th></tr></thead><tbody>
      <tr><th>LL</th><td>334</td><td>310</td><td>±0</td><td>303</td></tr>
      <tr><th>M</th><td>340</td><td>{price}</td><td>±0</td><td>309</td></tr>
      <tr><th>MS</th><td>360</td><td>335</td><td>±0</td><td>329</td></tr>
      <tr><th>市況</th><td colspan="4">保合</td></tr>
      <tr><th>入荷量</th><td colspan="4">{arrivals}t</td></tr></tbody></table>
      <div class="unit">{unit}</div></div></html>''', "html.parser")


class JapaneseEggPublicHistoryTests(unittest.TestCase):
    def test_rolling_page_reads_latest_verified_day_inside_historical_week(self):
        pages = {
            BASE: quotation(19, price="320", arrivals="900"),
            BASE + "2026/10/17/": BeautifulSoup("休日のため相場発表なし", "html.parser"),
            BASE + "2026/10/16/": quotation(16),
        }
        with patch.object(d.source, "_download_soup", side_effect=pages.__getitem__) as download:
            article = d._official_market_article(d.SPECS_BY_KEY["japan_egg"], START, END)
        self.assertEqual(article["publishedDate"], date(2026, 10, 16))
        self.assertEqual(article["url"], BASE + "2026/10/16/")
        self.assertIn("M 340 315 ±0 309", article["body"])
        self.assertNotIn("900t", article["body"])
        self.assertEqual([call.args[0] for call in download.call_args_list], list(pages))
        summary = summaries._native_report_sentence("japan_egg", article["body"])
        self.assertIn("315엔", summary)
        self.assertIn("760톤", summary)
        self.assertTrue(summaries._valid_brief(summary, "japan_egg", article["body"]))

    def test_current_week_quotation_needs_no_archive_requests(self):
        with patch.object(d.source, "_download_soup", return_value=quotation()) as download:
            article = d._japanese_egg_market_article(START, END)
        self.assertEqual(article["url"], BASE)
        download.assert_called_once_with(BASE)

    def test_current_page_returned_for_archived_date_is_never_backdated(self):
        with patch.object(d.source, "_download_soup", return_value=quotation(19)) as download:
            article = d._japanese_egg_market_article(START, END)
        self.assertIsNone(article)
        self.assertEqual(download.call_count, 8)
        self.assertNotIn(BASE + "2026/10/10/", [c.args[0] for c in download.call_args_list])

    def test_within_week_wrong_day_is_also_rejected_for_requested_date(self):
        result = d._japanese_egg_market_table(quotation(15), BASE + "2026/10/16/", START, END,
                                               requested_date=date(2026, 10, 16))
        self.assertIsNone(result)

    def test_absent_or_external_date_search_cannot_add_guessed_routes(self):
        pages = (quotation(19, search=False), quotation(19, action="https://other.example/search/"),
                 quotation(19, action=BASE + "../private/"))
        for page in pages:
            with self.subTest(page=page), patch.object(d.source, "_download_soup", return_value=page) as download:
                self.assertIsNone(d._japanese_egg_market_article(START, END))
                self.assertEqual(download.call_count, 1)

    def test_no_announced_date_or_only_older_date_does_not_search_future_values(self):
        pages = (quotation(9), quotation(19))
        pages[1].select_one(".publication-date").string = "2026年10月19日 更新"
        for page in pages:
            with self.subTest(page=page), patch.object(d.source, "_download_soup", return_value=page) as download:
                self.assertIsNone(d._japanese_egg_market_article(START, END))
                self.assertEqual(download.call_count, 1)

    def test_archive_without_benchmark_unit_is_not_a_usable_table(self):
        with patch.object(d.source, "_download_soup", side_effect=lambda url:
                          quotation(19) if url == BASE else quotation(16, unit="単位 不明")):
            self.assertIsNone(d._japanese_egg_market_article(START, END))

    def test_unavailable_day_falls_back_only_inside_requested_week(self):
        def fetch(url):
            if url == BASE:
                return quotation(19)
            if url == BASE + "2026/10/17/":
                raise d.source.ArticleDigestError("公開ページなし")
            return quotation(16)
        with patch.object(d.source, "_download_soup", side_effect=fetch):
            self.assertEqual(d._japanese_egg_market_article(START, END)["publishedDate"], date(2026, 10, 16))

    def test_negated_scheduled_or_cancelled_announcements_are_not_published(self):
        for stamp in ("2026年10月16日(金) 09:00 相場発表なし", "2026年10月16日(金) 09:00 発表中止",
                      "2026年10月16日(金) 09:00 発表予定", "2026年10月16日(金) 29:00 発表",
                      "2026年10月16日(金) 発表"):
            html = quotation()
            html.select_one(".publication-date").string = stamp
            with self.subTest(stamp=stamp), patch.object(d.source, "_download_soup", return_value=html) as download:
                self.assertIsNone(d._japanese_egg_market_article(START, END))
                self.assertEqual(download.call_count, 1)


if __name__ == "__main__":
    unittest.main()
