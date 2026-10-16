"""A publisher suffix is metadata, not permission to shorten a headline."""
from datetime import date
import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup

from src.article_titles import clean_article_title, format_domestic_article_title, normalize_article_publisher
from src.overseas_article_digest import _public_article, _hydrate_foreign_article, normalize_report_spacing, _brief_numeric_values, _numeric_unit_facts


class ArticleTitleTests(unittest.TestCase):
    def test_domestic_presentation_quotes_are_idempotent_without_changing_source_metadata(self):
        title = '브라질산 계란 수입가 논란… 정부 “수급 안정 조치” vs 野 "재정 투입 적정성 따져야"'
        expected = "브라질산 계란 수입가 논란… 정부 '수급 안정 조치' vs 野 '재정 투입 적정성 따져야'"
        self.assertEqual(format_domestic_article_title(title), expected)
        self.assertEqual(format_domestic_article_title(expected), expected)
        self.assertEqual(format_domestic_article_title("미국 '계란' 시장과 농가's 수익 ‘개선’"), "미국 '계란' 시장과 농가's 수익 ‘개선’")
        self.assertEqual(format_domestic_article_title('독일 „가격‟, 일본 ＂수급＂'), "독일 '가격', 일본 '수급'")
        self.assertEqual(clean_article_title(title, '인싸잇'), title)
        raw = {'title': title, 'publisher': '인싸잇', 'url': 'https://example.com/news', 'publishedDate': date(2026, 10, 14)}
        self.assertEqual(_public_article(raw)['title'], title)
        self.assertEqual(raw['title'], title)

    def test_only_matching_trailing_publisher_is_removed(self):
        for separator in [" - ", " – ", " — ", " | "]:
            with self.subTest(separator=separator):
                self.assertEqual(clean_article_title("해외 육류 수급 동향" + separator + "머니투데이", "머니투데이"), "해외 육류 수급 동향")
        for title in ["머니투데이가 본 해외 육류 수급", "해외 육류 - 공급 감소", "해외 육류 - 다른매체", "머니투데이", "수급-MTF"]:
            self.assertEqual(clean_article_title(title, "머니투데이"), title)

    def test_no_publisher_or_empty_headline_is_not_discarded(self):
        self.assertEqual(clean_article_title("해외 육류 - 머니투데이", ""), "해외 육류 - 머니투데이")
        self.assertEqual(clean_article_title(" - 머니투데이", "머니투데이"), "- 머니투데이")

    def test_public_article_used_by_display_and_copy_has_clean_title(self):
        article = _public_article({"title": "해외 육류 수급 - 머니투데이", "publisher": "머니투데이",
                                   "url": "https://example.com/news", "publishedDate": date(2026, 10, 6)})
        self.assertEqual(article["title"], "해외 육류 수급")
        self.assertEqual(article["publisher"], "머니투데이")

    def test_known_bilingual_publisher_label_is_not_repeated(self):
        self.assertEqual(normalize_article_publisher('식품저널 foodnews'), '식품저널')
        self.assertEqual(normalize_article_publisher('다른매체 foodnews'), '다른매체 foodnews')
        self.assertEqual(clean_article_title('해외 돼지고기 가격 동향 - 식품저널', '식품저널 foodnews'), '해외 돼지고기 가격 동향')

    def test_matching_bracketed_outlet_is_removed_but_editorial_labels_survive(self):
        self.assertEqual(clean_article_title('[머니투데이] 해외 계란 수급 동향', '머니투데이'), '해외 계란 수급 동향')
        self.assertEqual(clean_article_title('[식품저널] 해외 계란 수급 동향', '식품저널 foodnews'), '해외 계란 수급 동향')
        self.assertEqual(clean_article_title('[머니투데이][특파원 보고] 해외 계란 수급 동향 - 머니투데이', '머니투데이'), '[특파원 보고] 해외 계란 수급 동향')
        for title in ('[특파원 보고] 프랑스 닭고기 소비 동향', '[분석] 해외 계란 수입 증가', '[인싸잇] 브라질 계란 수입가격 논란', '[머니투데이]'):
            self.assertEqual(clean_article_title(title, '농민신문'), title)
        self.assertEqual(clean_article_title('[머니투데이]', '머니투데이'), '[머니투데이]')

    def test_insait_brand_needs_explicit_brand_and_its_exact_publisher_domain(self):
        title = '[인싸잇] 브라질 계란 수입가격 논란'
        for publisher, url in (('mediawatch.kr', ''), ('www.mediawatch.kr', ''), ('네이버 뉴스', 'https://www.mediawatch.kr/news/article.html?no=1')):
            with self.subTest(publisher=publisher, url=url):
                self.assertEqual(normalize_article_publisher(publisher, title=title, url=url), '인싸잇')
                self.assertEqual(clean_article_title(title, publisher, url=url), '브라질 계란 수입가격 논란')
        for url in ('https://mediawatch.kr.example.com/news', 'https://notmediawatch.kr/news', 'https://example.com/mediawatch.kr'):
            self.assertEqual(normalize_article_publisher('다른매체', title=title, url=url), '다른매체')
            self.assertEqual(clean_article_title(title, '다른매체', url=url), title)
        self.assertEqual(normalize_article_publisher('mediawatch.kr', title='브라질 계란 수입가격 논란'), 'mediawatch.kr')
        self.assertEqual(normalize_article_publisher('미디어워치', title='예전 기록', url='https://mediawatch.kr/news'), '미디어워치')
        self.assertEqual(normalize_article_publisher('인싸it'), '인싸잇')

    def test_public_article_normalizes_brand_without_changing_headline_quotes_or_raw_candidate(self):
        headline = '브라질산 계란 수입가 논란… 정부 “수급 안정 조치” vs 野 “재정 투입 적정성 따져야”'
        candidate = {'title': '[인싸잇] ' + headline, 'publisher': 'mediawatch.kr',
                     'url': 'https://www.mediawatch.kr/news/article.html?no=261344', 'publishedDate': date(2026, 10, 14)}
        article = _public_article(candidate)
        self.assertEqual(article['title'], headline)
        self.assertEqual(article['publisher'], '인싸잇')
        self.assertEqual(article['publishedDate'], '2026-10-14')
        self.assertEqual(candidate['title'], '[인싸잇] ' + headline)
        self.assertEqual(candidate['publisher'], 'mediawatch.kr')
        self.assertEqual(_public_article({**candidate, 'title': article['title'], 'publisher': article['publisher']}), article)

    def test_domain_suffix_is_removed_after_publisher_was_already_canonicalized(self):
        headline = '브라질 계란 수입가격 논란'
        url = 'https://www.mediawatch.kr/news/article.html?no=1'
        for publisher in ('mediawatch.kr', '인싸잇'):
            for suffix in ('mediawatch.kr', 'www.mediawatch.kr'):
                with self.subTest(publisher=publisher, suffix=suffix):
                    title = f'[인싸잇] {headline} - {suffix}'
                    candidate = {'title': title, 'publisher': publisher, 'url': url, 'publishedDate': date(2026, 10, 14)}
                    article = _public_article(candidate)
                    self.assertEqual(article['title'], headline)
                    self.assertEqual(article['publisher'], '인싸잇')
                    self.assertEqual(clean_article_title(title, '인싸잇', url=url), headline)
        self.assertEqual(clean_article_title('[인싸잇] ' + headline + ' - mediawatch.kr', '인싸잇', url='https://mediawatch.kr.example.com/news'), headline + ' - mediawatch.kr')

    def test_hydration_retains_brand_after_removing_headline_prefix(self):
        candidate = {'title': '[인싸잇] 브라질 계란 수입가격 논란', 'publisher': 'mediawatch.kr',
                     'url': 'https://www.mediawatch.kr/news/article.html?no=1', 'publishedDate': date(2026, 10, 14)}
        with patch('src.overseas_article_digest._download_soup', return_value=BeautifulSoup('<html></html>', 'html.parser')):
            hydrated = _hydrate_foreign_article(candidate)
        self.assertEqual(hydrated['publisher'], '인싸잇')
        self.assertEqual(hydrated['title'], '브라질 계란 수입가격 논란')
        self.assertEqual(_public_article(hydrated)['publisher'], '인싸잇')

    def test_large_quantity_spacing_is_idempotent_and_preserves_exact_values(self):
        original = "363만2000마리 줄어 1억8968만9000마리 기록,4억 8,700만파운드 생산"
        expected = "363만 2000마리 줄어 1억 8968만 9000마리 기록, 4억 8,700만 파운드 생산"
        normalized = normalize_report_spacing(original)
        self.assertEqual(normalized, expected)
        self.assertEqual(normalize_report_spacing(normalized), expected)
        self.assertEqual(_brief_numeric_values(original), _brief_numeric_values(normalized))
        self.assertEqual(_numeric_unit_facts(original), _numeric_unit_facts(normalized))
        self.assertIn("8,700", normalized)
