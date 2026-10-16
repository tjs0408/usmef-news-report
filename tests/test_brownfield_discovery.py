from datetime import date
import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup
from src import livestock_article_draft as d


START, END = date(2026, 10, 4), date(2026, 10, 10)
ARTICLE = "https://brownfieldagnews.com/news/broiler-market/"


class BrownfieldDiscoveryTests(unittest.TestCase):
    def test_wrapped_heading_has_exact_title_date_excerpt_and_www_alias(self):
        page = BeautifulSoup(
            '<a class="post_link_wrapper wide" href="' + ARTICLE + '">'
            '<div class="loop_inner"><p class="post_loop_date">Oct 07, 2026</p>'
            '<h2 class="post_loop_title">Broiler sets fall on week</h2>'
            '<p class="post_loop_excerpt">USDA reports lower weekly broiler sets.</p></div></a>'
            '<a class="post_link_wrapper" href="https://unrelated.example/news/">'
            '<h2 class="post_loop_title">Broiler exports rise</h2></a>', 'html.parser')
        candidates = d._listing_candidates(page, "https://www.brownfieldagnews.com/news/",
                                           d.SPECS_BY_KEY['us_chicken'], START, END)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]['title'], 'Broiler sets fall on week')
        self.assertEqual(candidates[0]['publishedDate'], date(2026, 10, 7))
        self.assertEqual(candidates[0]['body'], 'USDA reports lower weekly broiler sets.')

    def test_public_search_feed_is_followed_across_www_alias(self):
        feed = 'https://brownfieldagnews.com/search/broiler/feed/rss2/'
        page = BeautifulSoup('<link rel="alternate" type="application/rss+xml" href="' + feed + '">', 'html.parser')
        chosen = {'url': ARTICLE, 'publishedDate': date(2026, 10, 7)}
        spec = d.SPECS_BY_KEY['us_chicken']
        with patch.object(d.source, '_download_soup', return_value=page), \
             patch.object(d.source, '_download_html', return_value='<rss/>') as download, \
             patch.object(d, '_feed_candidates', return_value=[chosen]), \
             patch.object(d, '_choose_original', return_value=chosen):
            result = d._preferred_site_article(spec, START, END)
        self.assertIs(result, chosen)
        download.assert_called_once_with(feed)

    def test_feed_entry_alias_is_allowed_but_other_domain_is_rejected(self):
        def item(url):
            return '<item><title>Broiler sets fall on week</title><link>' + url + '</link><pubDate>Wed, 07 Oct 2026 12:00:00 GMT</pubDate></item>'
        xml = '<rss><channel>' + item(ARTICLE) + item('https://outside.example/broiler/') + '</channel></rss>'
        result = d._feed_candidates(xml, 'https://www.brownfieldagnews.com/news/feed/',
                                    d.SPECS_BY_KEY['us_chicken'], START, END)
        self.assertEqual([a['url'] for a in result], [ARTICLE])

    def test_verified_current_week_article_does_not_wait_for_older_pages(self):
        page = BeautifulSoup(
            '<a class="post_link_wrapper" href="' + ARTICLE + '">'
            '<p class="post_loop_date">Oct 07, 2026</p>'
            '<h2 class="post_loop_title">US broiler production rises</h2></a>'
            '<a href="https://brownfieldagnews.com/news/page/2/">Older Entries »</a>', 'html.parser')
        chosen = {'url': ARTICLE, 'publishedDate': date(2026, 10, 7)}
        with patch.object(d.source, '_download_soup', return_value=page) as download, \
             patch.object(d, '_choose_original', return_value=chosen):
            result = d._preferred_site_article(d.SPECS_BY_KEY['us_chicken'], START, END)
        self.assertIs(result, chosen)
        download.assert_called_once_with('https://www.brownfieldagnews.com/news/')


if __name__ == '__main__':
    unittest.main()
