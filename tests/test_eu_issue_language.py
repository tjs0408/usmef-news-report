"""German issue discovery/reading preserves existing English EU coverage."""
from dataclasses import replace
from datetime import date
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

from src import livestock_article_draft as collector
from src import overseas_article_digest as source


START, END = date(2026, 10, 18), date(2026, 10, 24)
EU = collector.SPECS_BY_KEY['eu_pork']
DE_BODY = ('Deutschland: Das Angebot an Schweinen ist umfangreich und die Nachfrage nach Schweinefleisch '
           'bleibt schwach. Höhere Futterkosten belasten Erzeuger, während der Absatz im Einzelhandel sinkt.')


def html(language, body=DE_BODY):
    return BeautifulSoup('<html lang="' + language + '"><head>'
        '<meta property="article:published_time" content="2026-10-21T10:00:00+02:00">'
        '<meta property="og:site_name" content="Public local publisher"></head><body>'
        '<article><h1>Deutschland Schweinefleisch Nachfrage und Angebot</h1>'
        '<p>' + body + '</p></article></body></html>', 'html.parser')


class EuropeanIssueLanguageTests(unittest.TestCase):
    def read(self, language, *, spec=EU, body=DE_BODY):
        candidate = {'title': 'German pork market news', 'url': 'https://publisher.example/news/pork',
                     'publishedDate': date(2026, 10, 21)}
        with patch.object(source, '_download_soup', return_value=html(language, body)):
            return collector._read_original_article(candidate, spec)

    def test_public_german_html_original_can_be_read_with_existing_eu_spec(self):
        result = self.read('de-DE')
        self.assertIsNotNone(result)
        self.assertEqual(result['sourceLanguage'], 'de')
        self.assertEqual(result['publishedDate'], date(2026, 10, 21))
        self.assertIn(DE_BODY, result['body'])
        self.assertFalse(result['headlineOnly'])
        self.assertFalse(result['searchResult'])

    def test_existing_english_eu_original_remains_english(self):
        body = ('Germany pork imports declined as domestic supply increased across European markets. '
                'Retail demand weakened and meat distributors held sufficient stocks for their customers.')
        result = self.read('en-GB', body=body)
        self.assertIsNotNone(result)
        self.assertEqual(result['sourceLanguage'], 'en')
        self.assertIn(body, result['body'])
        self.assertEqual(EU.language, 'en')  # no mutation of the registered spec

    def test_other_languages_and_other_countries_are_not_broadly_relaxed(self):
        self.assertIsNone(self.read('fr-FR'))
        self.assertIsNone(self.read('de', spec=collector.SPECS_BY_KEY['us_pork']))
        self.assertIsNone(self.read('de', spec=collector.SPECS_BY_KEY['australia']))

    def test_three_eu_search_callbacks_use_german_and_germany_locale(self):
        with patch.object(source, '_search_google_news_rss', return_value=[]) as rss, \
             patch.object(collector, '_public_google_candidates', return_value=[]) as web, \
             patch.object(collector, '_public_bing_candidates', return_value=[]) as bing:
            result = collector._search_editorial_issues(EU, START, END,
                exclude_urls=frozenset(), diagnostics={})
        self.assertIsNone(result)
        self.assertEqual(rss.call_count, 2)
        self.assertEqual(web.call_count, 1)
        self.assertEqual(bing.call_count, 2)
        for call in rss.call_args_list:
            self.assertEqual(call.kwargs['language'], 'de')
            self.assertEqual(call.kwargs['country'], 'DE')
            self.assertEqual(call.kwargs['edition'], 'DE:de')
        self.assertEqual(web.call_args.args[1], 'de')
        self.assertTrue(all(call.args[1].language == 'de' and call.args[1].country == 'DE'
                            for call in bing.call_args_list))
        self.assertEqual(EU.language, 'en')

    def test_public_bing_uses_german_market_for_german_issue_search(self):
        with patch.object(source, '_download_html', return_value='<rss><channel/></rss>') as download:
            self.assertEqual(collector._public_bing_candidates('Schweinefleisch Nachfrage',
                replace(EU, language='de'), START, END), [])
        query = parse_qs(urlparse(download.call_args.args[0]).query)
        self.assertEqual(query['mkt'], ['de-DE'])


if __name__ == '__main__':
    unittest.main()
