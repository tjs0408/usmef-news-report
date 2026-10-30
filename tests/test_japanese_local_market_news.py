"""Japan egg alternatives remain original-, week- and commodity-bound."""
from datetime import date
import json
import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup

from src import livestock_article_draft as collector
from src import overseas_article_digest as digest
from src.market_issue_selection import market_issue_profile


SPEC = collector.SPECS_BY_KEY['japan_egg']
START, END = date(2026, 10, 11), date(2026, 10, 17)
TITLE = '食品の販売価格を調査　卵の需要に変化'
RICE = '名古屋市の食品店を取材しました。コメの価格は5キロ2800円に下落しました。'
EGGS = ('卵の価格は前週から据え置きとなっています。\n'
        '卵の需要は今は落ち着いているため、価格は10月末頃まで安定する見通しです。')
BODY = RICE + '\n' + EGGS + '\nサケの価格は100グラム390円に上昇しました。'


def original(**changes):
    return {'title': TITLE, 'url': 'https://news.tv-aichi.co.jp/single.php?id=example',
            'publishedDate': date(2026, 10, 15), 'publisher': 'テレビ愛知',
            'body': BODY, 'sourceLanguage': 'ja', 'searchResult': False,
            'headlineOnly': False, **changes}


class JapaneseLocalMarketNewsTests(unittest.TestCase):
    def test_actual_japanese_locality_and_food_egg_passage_establish_country(self):
        article = original()
        self.assertNotIn('日本', BODY)
        self.assertTrue(collector._japanese_regional_egg_original(article))
        self.assertGreaterEqual(collector._relevance(article, SPEC), 0)
        self.assertEqual(collector._selection_profile(article, SPEC)[0], 0)

    def test_language_domain_and_search_metadata_are_not_country_evidence(self):
        variants = (
            {'url': 'https://unknown.jp/article'},
            {'url': 'https://news.tv-aichi.co.jp.evil.example/article'},
            {'url': 'https://www.stv.jp.evil.example/article'},
            {'sourceLanguage': 'zh'},
            {'body': EGGS + '\n' + EGGS},
            {'searchResult': True}, {'headlineOnly': True},
        )
        for changes in variants:
            with self.subTest(changes=changes):
                self.assertFalse(collector._japanese_regional_egg_original(original(**changes)))

    def test_foreign_egg_facts_cannot_be_made_japanese_by_a_local_publisher(self):
        body = ('名古屋の放送局から世界の市場を紹介します。\n'
                '台湾の卵価格は供給不足の影響で上昇し、鶏卵の需要も増加しました。\n'
                '日本の会社情報を別ページに掲載しています。')
        article = original(title='台湾の卵価格が上昇', body=body)
        self.assertFalse(collector._japanese_regional_egg_original(article))
        self.assertLess(collector._relevance(article, SPEC), 0)
        # Even a general headline and an unrelated 日本 footnote must not
        # provide the country for Taiwan's independent egg-price paragraph.
        article['title'] = '世界の食品価格と供給の動き'
        self.assertLess(collector._relevance(article, SPEC), 0)

    def test_roe_only_and_medical_prices_are_not_food_egg_market_evidence(self):
        variants = (
            ('日本のカジカの卵がお買い得', '日本の札幌でカジカの卵は100グラム290円、価格は安定。'),
            ('日本のイクラ価格が上昇', '日本の札幌で魚卵の供給が減少し価格は上昇しました。'),
            ('日本の卵培養ワクチン', '日本で卵を使うワクチンの価格と供給について研究しました。'),
        )
        for title, body in variants:
            with self.subTest(title=title):
                article = original(title=title, body=body * 4)
                self.assertFalse(collector._japanese_regional_egg_original(article))
                self.assertLess(collector._relevance(article, SPEC), 0)

    def test_original_body_is_preserved_but_summary_excerpt_excludes_other_foods(self):
        soup = BeautifulSoup('<html lang="ja"><h1>' + TITLE + '</h1>'
            '<time datetime="2026-10-15"></time><article>'
            + ''.join('<p>' + p + '</p>' for p in BODY.splitlines()) + '</article></html>', 'html.parser')
        with patch.object(digest, '_download_soup', return_value=soup):
            article = collector._read_original_article(original(), SPEC)
        self.assertIsNotNone(article)
        self.assertEqual(article['publishedDate'], date(2026, 10, 15))
        self.assertIn('2800円', article['body'])
        self.assertIn('390円', article['body'])
        self.assertIn('卵の需要', article['briefBody'])
        self.assertIn('10月末', article['briefBody'])
        self.assertNotIn('コメ', article['briefBody'])
        self.assertNotIn('サケ', article['briefBody'])
        self.assertNotIn('2800', article['briefBody'])

    def test_actual_chicken_egg_block_after_fish_roe_is_eligible_and_focused(self):
        body = ('札幌の小売店から報告します。カジカの卵は100グラム290円で価格は安定。\n'
                '続いてタマゴの価格です。タマゴは飼料費の上昇の影響で価格が上昇する見通しです。\n'
                'タマゴの供給は鳥インフルエンザで不足しています。')
        article = original(url='https://www.stv.jp/news/stvnews/example.html', body=body)
        self.assertGreaterEqual(collector._relevance(article, SPEC), 0)
        focused = collector._editorial_excerpt(body, TITLE, SPEC)
        self.assertIn('タマゴ', focused)
        self.assertNotIn('カジカ', focused)
        self.assertNotIn('290', focused)

    def test_original_year_wins_over_a_recent_search_timestamp_and_month_day(self):
        schema = {'@type': 'NewsArticle', 'datePublished': '2024-11-21T14:05:30+09:00'}
        soup = BeautifulSoup('<html lang="ja"><script type="application/ld+json">'
            + json.dumps(schema) + '</script><h1>' + TITLE + '</h1><article>'
            + BODY + '</article><div>10/15(木) 14:57</div></html>', 'html.parser')
        with patch.object(digest, '_download_soup', return_value=soup):
            article = collector._read_original_article(original(), SPEC)
        self.assertEqual(article['publishedDate'], date(2024, 11, 21))
        with patch.object(collector, '_original_article', return_value=article):
            self.assertIsNone(collector._choose_original([original()], SPEC, START, END))

    def test_missing_original_date_is_not_inferred_from_today_or_the_report_day(self):
        soup = BeautifulSoup('<html lang="ja"><h1>' + TITLE + '</h1><article>'
            + BODY + '</article><div>10/15(木) 14:57</div></html>', 'html.parser')
        candidate = {key: value for key, value in original().items() if key != 'publishedDate'}
        with patch.object(digest, '_download_soup', return_value=soup):
            self.assertIsNone(collector._read_original_article(candidate, SPEC))

    def test_substantive_original_remains_selected_through_native_preselection(self):
        quote = original(title='JA全農たまご 鶏卵相場（東京）',
            url='https://www.jz-tamago.co.jp/business/souba/',
            body='日本の鶏卵相場。東京の鶏卵価格は1kg320円、前日と変わらず。' * 4,
            _issueBaselineTrusted=True)
        news = original()
        self.assertGreaterEqual(market_issue_profile('japan_egg', TITLE, BODY)['level'], 2)
        with patch.object(collector, '_search_article', return_value=news):
            chosen = collector._broaden_editorial_candidate(quote, SPEC, START, END)
        self.assertEqual(chosen['url'], news['url'])
        summary = '일본 도쿄 계란 기준가는 전일과 같은 수준을 유지한 가운데 주간 시장가격 보합세 기록'
        with patch.object(digest, '_native_report_sentence',
                          side_effect=lambda _key, body: summary if body == quote['body'] else None), \
             patch.object(digest, '_fit_report_summary', side_effect=lambda value, *_: value), \
             patch.object(digest, '_valid_brief', return_value=True):
            ready = collector._prefer_native_summary_candidate(chosen, SPEC, START, END, True)
        self.assertEqual(ready['url'], news['url'])
        self.assertIn(quote['url'], [item['url'] for item in ready['alternatives']])

    def test_complete_korean_news_brief_does_not_request_another_context_inference(self):
        summary = '나고야 소매점은 계란 수요 진정에 10월 말까지 현 수준의 판매가격 유지 전망'
        self.assertFalse(collector._issue_summary_needs_context('japan_egg', TITLE, BODY, summary))

    def test_wrong_week_original_cannot_replace_daily_quote(self):
        quote = original(_issueBaselineTrusted=True)
        for stamp in (date(2026, 10, 10), date(2026, 10, 18)):
            with self.subTest(stamp=stamp):
                other = original(url='https://www.stv.jp/another', publishedDate=stamp)
                with patch.object(collector, '_search_article', return_value=other):
                    chosen = collector._broaden_editorial_candidate(quote, SPEC, START, END)
                self.assertEqual(chosen['url'], quote['url'])
                self.assertEqual(chosen['alternatives'], [])

    def test_public_regional_listing_resolves_a_story_without_decoding_google(self):
        # Distinct cards ensure dates are bound to the advertised story, not
        # a different headline/footer or a fabricated report-date fallback.
        page = BeautifulSoup('<html>'
            '<article><h2><a href="/single.php?id=new-story">卵の需要と価格の見通し</a></h2>'
            '<time datetime="2026-10-15">2026年10月15日</time></article>'
            '<article><h2><a href="/single.php?id=old-story">卵の価格</a></h2>'
            '<time datetime="2026-10-08">2026年10月8日</time></article>'
            '<article><h2><a href="/politics">政治ニュースと経済の見通し</a></h2>'
            '<time datetime="2026-10-15">2026年10月15日</time></article></html>', 'html.parser')
        diagnostics = {}
        with patch.object(digest, '_download_soup', return_value=page) as download, \
             patch.object(collector, 'public_history_candidates', return_value=[]):
            candidates = collector._issue_publisher_candidates([], SPEC, START, END,
                                                               frozenset(), diagnostics)
        self.assertEqual([item['url'] for item in candidates],
                         ['https://news.tv-aichi.co.jp/single.php?id=new-story'])
        self.assertEqual(candidates[0]['publishedDate'], date(2026, 10, 15))
        self.assertEqual(diagnostics['issuePublisherPages'], 1)
        download.assert_called_once_with('https://news.tv-aichi.co.jp/')

    def test_regional_listing_reuses_existing_two_publisher_page_allowance(self):
        candidates = [{'title': '卵の価格と需要', 'url': f'https://news.google.com/rss/articles/{i}',
                       'publisherUrl': f'https://publisher-{i}.example', 'publisher': str(i)}
                      for i in range(8)]
        diagnostics = {}
        with patch.object(digest, '_download_soup', return_value=BeautifulSoup('<html/>', 'html.parser')) as download, \
             patch.object(collector, 'public_history_candidates', return_value=[]):
            collector._issue_publisher_candidates(candidates, SPEC, START, END,
                                                  frozenset(), diagnostics)
        self.assertEqual(download.call_count, 2)
        self.assertEqual(diagnostics['issuePublisherPages'], 2)
        self.assertIn('https://news.tv-aichi.co.jp/', [call.args[0] for call in download.call_args_list])


if __name__ == '__main__':
    unittest.main()
