from datetime import date
import unittest
from unittest.mock import patch
from bs4 import BeautifulSoup

from src import livestock_article_draft as d


START, END = date(2026, 10, 11), date(2026, 10, 17)


class PublisherMarketFeedTests(unittest.TestCase):
    def test_empty_home_feed_does_not_hide_advertised_news_feed(self):
        page = BeautifulSoup(
            '<link rel="alternate" type="application/rss+xml" href="https://www.beefcentral.com/home/feed/">'
            '<link rel="alternate" type="application/rss+xml" href="https://www.beefcentral.com/feed/">', 'html.parser')
        chosen = {'title': 'Australian cattle prices rise', 'url': 'https://www.beefcentral.com/prices/',
                  'publishedDate': date(2026, 10, 13), 'body': 'Australian cattle supply and prices changed.'}
        def feed(xml, *_):
            return [chosen] if xml == 'news feed' else []
        with patch.object(d.source, '_download_soup', return_value=page), \
             patch.object(d.source, '_download_html', side_effect=['home feed', 'news feed']) as download, \
             patch.object(d, '_feed_candidates', side_effect=feed), \
             patch.object(d, '_choose_original', return_value=chosen):
            result = d._preferred_site_article(d.replace(d.SPECS_BY_KEY['australia'],
                listings=('https://www.beefcentral.com/',)), START, END)
        self.assertIs(result, chosen)
        self.assertEqual(download.call_count, 2)

    def test_mla_industry_exchange_uses_market_fallback_instead_of_event(self):
        event = {'title': 'Australia and China strengthen red meat partnership through industry exchange',
                 'body': 'Australian cattle production organisations visited China for an industry cooperation forum.',
                 'publishedDate': date(2026, 10, 14)}
        market = {'title': 'Australian cattle prices rise', 'body': 'Australian cattle supply and prices changed.',
                  'publishedDate': date(2026, 10, 13)}
        with patch.object(d.source, '_find_australia_beef_article', return_value=event), \
             patch.object(d, '_preferred_site_article', return_value=market) as fallback, \
             patch.object(d, '_search_article') as general:
            result = d._find_section(d.SPECS_BY_KEY['australia'], START, END)
        self.assertEqual(result['title'], market['title'])
        self.assertEqual(result['sourceMethod'], 'search')
        self.assertEqual(fallback.call_args.args[0].listings, ('https://www.beefcentral.com/',))
        general.assert_not_called()

    def test_real_mla_market_reporting_keeps_priority(self):
        market = {'title': 'Australian beef exports to China rise',
                  'body': 'Australian beef exports rose as demand in China strengthened.',
                  'publishedDate': date(2026, 10, 13)}
        with patch.object(d.source, '_find_australia_beef_article', return_value=market), \
             patch.object(d, '_preferred_site_article') as fallback:
            result = d._find_section(d.SPECS_BY_KEY['australia'], START, END)
        self.assertEqual(result['title'], market['title'])
        fallback.assert_not_called()


if __name__ == '__main__':
    unittest.main()
