from datetime import date
import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup

from src import livestock_article_draft as d


class CurrentWeekSourceFocusTests(unittest.TestCase):
    def score(self, key, title, body):
        return d._relevance({"title": title, "body": body}, d.SPECS_BY_KEY[key])

    def test_macro_wealth_and_k_brand_ingredient_mentions_are_not_market_stories(self):
        self.assertLess(self.score("domestic", "늘어난 美 가계 자산, 상위 1% 몫 확대",
            "미국 가계의 자산 격차가 확대됐다. 휘발유와 쇠고기 같은 일상 품목 가격이 가계 구매력을 잠식했다."), 0)
        self.assertLess(self.score("domestic_chicken", "고수 넣은 만두 미국서 대박…K브랜드 비결",
            "미국에 K브랜드 수출을 확대했다. 치킨과 닭고기 만두 등 현지 소비자를 공략하는 제품의 생산을 늘렸다."), 0)

    def test_local_export_sales_milestone_needs_destination_market_impact(self):
        self.assertLess(self.score("domestic_pork", "양돈농협, 몽골에 돈육 수출 쾌거",
            "농협은 몽골 시장에 돼지고기를 수출해 역대 최대 수출 실적을 기록했다."), 0)
        self.assertGreaterEqual(self.score("domestic_egg", "한국산 계란 홍콩 수출 재개",
            "홍콩 계란 공급 부족으로 가격이 상승했다. 한국산 계란 수출 재개로 홍콩 시장 공급이 확대된다."), 0)

    def test_real_foreign_inflation_disease_trade_and_safety_remain_eligible(self):
        cases = (
            ("domestic", "미국 소비자물가 발표", "미국 쇠고기 소매가격은 생산량 감소로 전년보다 상승했다."),
            ("domestic_chicken", "가금류 검역 조치 변경", "브라질 닭고기 수출은 조류독감 검역 제한으로 중단됐다."),
            ("domestic_pork", "독일 돈육 검역 완화", "독일 돼지고기 수출 재개가 현지 공급과 가격에 영향을 준다."),
            ("domestic_egg", "해외 식품 안전 경보", "일본 계란에서 살모넬라가 검출돼 유통 제품을 회수했다. 일본 계란 공급 부족이 예상된다."),
        )
        for key, title, body in cases:
            with self.subTest(key=key):
                self.assertGreaterEqual(self.score(key, title, body), 0)

    def test_scottish_and_us_reports_do_not_borrow_eu_comparison_context(self):
        self.assertLess(self.score("eu_pork", "Scottish pig sector faces market pressure",
            "Scottish pig prices improved. Competition from low EU pricing is weighing on confidence."), 0)
        self.assertLess(self.score("eu_pork", "USMEF: August pork exports lower",
            "US pork exports fell while European Union production grew."), 0)
        self.assertGreaterEqual(self.score("eu_pork", "German pig prices decrease",
            "German pig prices declined while British producers face higher feed costs."), 0)

    def test_korean_language_us_recall_source_body_excludes_the_share_toolbar(self):
        html = BeautifulSoup('''<html lang="ko"><meta property="article:published_time" content="2026-10-13T02:12:55Z">
            <h1>삼계탕 제품 미국 리콜</h1><section id="newsBody"><div class="headline">이전 자료 2025년 글자 크기 인쇄 공유</div>
            <div class="subHeadline">의무 수입 재검사 없이 반입</div>미국 USDA는 한국에서 수입한 즉석 닭고기 스튜 제품 4596파운드를 리콜했다.
            의무 수입 재검사를 받지 않았기 때문이다. 현재까지 질병이나 부상 사례는 보고되지 않았으며 소비자에게 먹지 말고 반품하도록 안내했다.
            <div class="iniframe">광고 닭고기 가격 99% 상승</div></section></html>''', "html.parser")
        with patch.object(d.source, "_download_soup", return_value=html):
            article = d._original_article({"url": "https://www.koreadaily.com/article/recall"}, d.SPECS_BY_KEY["domestic_chicken"])
        self.assertIsNotNone(article)
        self.assertEqual(article["publishedDate"], date(2026, 10, 13))
        self.assertNotIn("인쇄 공유", article["body"])
        self.assertNotIn("99%", article["body"])
        self.assertGreaterEqual(d._relevance(article, d.SPECS_BY_KEY["domestic_chicken"]), 0)


def market_html(stamp="2026年10月14日(水) 09:00 発表", unit="単位 円 / kg", row="<td>340</td><td>315</td><td>±0</td><td>309</td>"):
    return BeautifulSoup(f"""<html lang="ja"><p class="publication-date">{stamp}</p>
      <div id="tokyo"><table><thead><tr><th>東 京</th><th>高値</th><th colspan="2">基準値</th><th>安値</th></tr></thead>
      <tbody><tr><th>M</th>{row}</tr><tr><th>市況</th><td colspan="4">保合</td></tr>
      <tr><th>入荷量</th><td colspan="4">760t</td></tr></tbody></table><div class="unit">{unit}</div></div>
      <p>旧資料：2025年10月14日 相場上伸</p></html>""", "html.parser")


class JapanesePublicMarketSourceTests(unittest.TestCase):
    def test_dated_current_week_table_is_source_and_old_side_text_is_excluded(self):
        with patch.object(d.source, "_download_soup", return_value=market_html()):
            article = d._official_market_article(d.SPECS_BY_KEY["japan_egg"], date(2026, 10, 11), date(2026, 10, 17))
        self.assertEqual(article["publishedDate"], date(2026, 10, 14))
        self.assertEqual(article["sourceLanguage"], "ja")
        self.assertEqual(article["url"], d.JAPANESE_EGG_MARKET_URL)
        self.assertIn("M 340 315 ±0 309", article["body"])
        self.assertIn("入荷量 760t", article["body"])
        self.assertNotIn("旧資料", article["body"])

    def test_stale_or_unannounced_table_cannot_be_relabelled_as_requested_week(self):
        for stamp in ("2026年10月9日(金) 09:00 発表", "2026年10月14日 更新"):
            with self.subTest(stamp=stamp), patch.object(d.source, "_download_soup", return_value=market_html(stamp)):
                self.assertIsNone(d._japanese_egg_market_article(date(2026, 10, 11), date(2026, 10, 17)))

    def test_price_requires_m_benchmark_column_and_published_unit(self):
        for html in (market_html(unit="単位 不明"), market_html(row="<td>315</td><td>±0</td><td>309</td>"),
                     market_html(row="<td>340</td><td>-----</td><td>±0</td><td>309</td>")):
            with patch.object(d.source, "_download_soup", return_value=html):
                self.assertIsNone(d._japanese_egg_market_article(date(2026, 10, 11), date(2026, 10, 17)))


if __name__ == "__main__":
    unittest.main()
