"""Public, bounded publisher history: publication dates never follow RSS labels."""
from datetime import date
from dataclasses import replace
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse
from urllib.error import URLError

from bs4 import BeautifulSoup

from src import publisher_history_discovery as h
from src import livestock_article_draft as d
from src import overseas_article_digest as s


START, END = date(2026, 8, 30), date(2026, 9, 5)
ROOT = 'https://publisher.example/'


def page(html=''):
    return BeautifulSoup('<link rel="https://api.w.org/" href="https://publisher.example/wp-json/">' + html,
                         'html.parser')


def post(day='2026-09-03', **extra):
    return {'date': day + 'T12:30:00', 'modified': '2026-09-04T00:00:00',
            'link': ROOT + 'market/', 'title': {'rendered': 'US egg prices &amp; demand'},
            'excerpt': {'rendered': '<p>Discovery excerpt.</p>'},
            'content': {'rendered': '<p>US egg prices decline as production increases.</p>'}, **extra}


class PublisherHistoryTests(unittest.TestCase):
    def test_temporary_fetch_failure_is_not_cached_for_the_next_run(self):
        h._cached_public_json.cache_clear()
        with patch.object(h, 'urlopen', side_effect=URLError('temporary')) as fetch:
            self.assertIsNone(h._public_json(ROOT + 'wp-json/wp/v2/posts?search=egg'))
            self.assertIsNone(h._public_json(ROOT + 'wp-json/wp/v2/posts?search=egg'))
        self.assertEqual(fetch.call_count, 2)

    def test_advertised_query_form_route_is_supported_without_guessing_api(self):
        html = BeautifulSoup('<link rel="https://api.w.org/" href="https://publisher.example/?rest_route=/">', 'html.parser')
        with patch.object(h, '_public_json', return_value=[post()]) as read:
            found = self.discover(html)
        self.assertEqual(len(found), 1)
        query = parse_qs(urlparse(read.call_args.args[0]).query)
        self.assertEqual(query['rest_route'], ['/wp/v2/posts'])
        self.assertEqual(query['after'], [START.isoformat() + 'T00:00:00'])

    def discover(self, soup=None, **extra):
        return h.public_history_candidates(soup or page(), ROOT, species='egg', language='en',
            publisher='Publisher', start=START, end=END, **extra)

    def test_date_query_uses_selected_week_and_not_current_date(self):
        with patch.object(h, '_public_json', return_value=[post()]) as read:
            found = self.discover()
        query = parse_qs(urlparse(read.call_args.args[0]).query)
        self.assertEqual(query['after'], ['2026-08-30T00:00:00'])
        self.assertEqual(query['before'], ['2026-09-05T23:59:59'])
        self.assertEqual(query['search'], ['egg'])
        self.assertEqual(found[0]['publishedDate'], date(2026, 9, 3))
        self.assertEqual(found[0]['title'], 'US egg prices & demand')
        self.assertNotIn('<p>', found[0]['body'])
        read.assert_called_once()

    def test_modified_in_week_cannot_relabel_old_publication(self):
        with patch.object(h, '_public_json', return_value=[post('2026-08-29'), post('2026-09-06')]):
            self.assertEqual(self.discover(), [])

    def test_external_root_external_records_and_protected_posts_are_refused(self):
        external_root = BeautifulSoup('<link rel="https://api.w.org/" href="https://evil.example/wp-json/">', 'html.parser')
        with patch.object(h, '_public_json') as read:
            self.assertEqual(self.discover(external_root), [])
        read.assert_not_called()
        for item in (post(link='https://evil.example/egg/'), post(content={'protected': True}),
                     post(date=''), post(title=None)):
            with self.subTest(item=item), patch.object(h, '_public_json', return_value=[item]):
                self.assertEqual(self.discover(), [])

    def test_missing_advertisement_never_guesses_api(self):
        with patch.object(h, '_public_json') as read:
            self.assertEqual(self.discover(BeautifulSoup('<h1>News</h1>', 'html.parser')), [])
        read.assert_not_called()

    def test_unavailable_api_is_terminal_and_has_separate_diagnostics(self):
        stats = {}
        with patch.object(h, '_public_json', return_value=None) as read:
            self.assertEqual(h.public_history_candidates(page(), ROOT, species='pork', language='en',
                publisher='Publisher', start=START, end=END, diagnostics=stats), [])
        read.assert_called_once()
        self.assertEqual(stats, {'publisherArchiveRequests': 1, 'publisherArchiveUnavailable': 1,
                                 'publisherArchiveCandidates': 0})

    def test_public_month_search_only_uses_advertised_same_host_get_form(self):
        form = '<form action="/" method="get"><input name="s"></form>'
        urls = h.public_month_search_urls(page(form), ROOT, species='egg', language='en', start=START, end=END)
        self.assertEqual(len(urls), 2)
        self.assertEqual([parse_qs(urlparse(url).query)['m'][0] for url in urls], ['202609', '202608'])
        for bad in ('<form action="/" method="post"><input name="s"></form>',
                    '<form action="https://evil.example/"><input name="s"></form>'):
            self.assertEqual(h.public_month_search_urls(page(bad), ROOT, species='egg', language='en',
                                                       start=START, end=END), [])

    def test_next_page_uses_actual_link_not_last_page_or_external_link(self):
        html = ('<ul class="pagination"><li><a href="?page=1">1</a></li>'
                '<li><a href="https://evil.example/?page=2">2</a></li>'
                '<li><a href="?page=12">&gt;|</a></li><li><a href="?page=2">&gt;</a></li></ul>')
        self.assertEqual(h.public_next_listing_url(BeautifulSoup(html, 'html.parser'), ROOT), ROOT + '?page=2')
        self.assertIsNone(h.public_next_listing_url(BeautifulSoup(html, 'html.parser'), ROOT + '?page=12'))

    def test_google_js_interstitial_is_not_reported_as_real_empty_search(self):
        html = BeautifulSoup('<title>Google Search</title>Please click here if you are not redirected within a few seconds.', 'html.parser')
        with patch.object(s, '_download_soup', return_value=html):
            found = d._public_google_candidates('US egg', 'en', START, END)
        self.assertEqual(found, [])
        self.assertEqual(found.discovery_reason, 'interstitial')

    def test_google_interstitial_stops_unproductive_query_variants(self):
        stats = {}
        with patch.object(s, '_search_google_news_rss', return_value=[]), \
             patch.object(d, '_public_bing_candidates', return_value=[]), \
             patch.object(d, '_public_google_candidates', return_value=h.PublicSearchCandidates(reason='interstitial')) as search, \
             patch.object(d, '_choose_original', return_value=None):
            self.assertIsNone(d._search_article(d.SPECS_BY_KEY['eu_pork'], START, END, diagnostics=stats))
        search.assert_called_once()
        self.assertEqual(stats['googleSearchInterstitial'], 1)

    def test_historical_lookup_precedes_unnecessary_latest_feed_download(self):
        html = page('<link rel="alternate" type="application/rss+xml" href="/feed/">')
        original = {'url': ROOT + 'egg/', 'publishedDate': START}
        with patch.object(s, '_download_soup', return_value=html), \
             patch.object(d, 'public_history_candidates', return_value=[original]), \
             patch.object(d, '_choose_original', return_value=original), \
             patch.object(s, '_download_html') as latest_feed:
            found = d._preferred_site_article(replace(d.SPECS_BY_KEY['us_egg'], listings=(ROOT,)), START, END)
        self.assertEqual(found['url'], original['url'])
        latest_feed.assert_not_called()

    def test_indexbox_global_category_never_infers_us_from_publisher(self):
        spec = replace(d.SPECS_BY_KEY['us_egg'], publisher='IndexBox', listings=(d.INDEXBOX_EGG_NEWS_URL,))
        original = {'url': ROOT + 'egg/', 'publishedDate': START}
        with patch.object(s, '_download_soup', return_value=BeautifulSoup('', 'html.parser')), \
             patch.object(d, '_choose_original', return_value=original) as choose:
            d._preferred_site_article(spec, START, END)
        self.assertFalse(choose.call_args.kwargs['trusted_country'])

    def test_us_egg_archive_uses_public_shell_egg_category_and_real_geography(self):
        original = {'url': ROOT + 'egg/', 'publishedDate': START}
        with patch.object(d, '_preferred_site_article', return_value=original) as find:
            found = d._search_article(d.SPECS_BY_KEY['us_egg'], START, END)
        fallback = find.call_args.args[0]
        self.assertIn(h.INDEXBOX_SHELL_EGG_NEWS_URL, fallback.listings)
        self.assertIn('New York', fallback.regions)
        self.assertEqual(found['sourceMethod'], 'publisher_archive')

    def test_month_archive_cross_year_uses_both_actual_calendar_months(self):
        form = '<form action="/" method="get"><input name="s"></form>'
        urls = h.public_month_search_urls(page(form), ROOT, species='egg', language='en',
                                         start=date(2024, 12, 29), end=date(2025, 1, 4))
        self.assertEqual([parse_qs(urlparse(url).query)['m'][0] for url in urls], ['202501', '202412'])


if __name__ == '__main__':
    unittest.main()
