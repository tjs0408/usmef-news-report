"""Industry events are related fallbacks, not direct market-price news."""
import unittest

from src import livestock_article_draft as collector


class MarketEventSourceTierTests(unittest.TestCase):
    def article(self, title, url='https://example.org/news/market'):
        return {'title': title, 'url': url, 'body':
                'Australian beef and cattle production supply and prices are described. '
                'The beef industry discusses production cycles across Australia. ' * 3,
                'sourceLanguage': 'en', 'searchResult': False, 'headlineOnly': False}

    def test_event_program_and_sponsored_information_are_related_not_market_tier(self):
        spec = collector.SPECS_BY_KEY['australia']
        for article in (
            self.article('National Beef Carcase Competition judging well advanced'),
            self.article('Eight producers selected for National Beef Leaders Program'),
            self.article('Cattle producers manage for efficiency', 'https://example.org/sponsored/cattle'),
        ):
            with self.subTest(article=article):
                self.assertEqual(collector._selection_profile(article, spec)[0], 2)

    def test_export_competition_is_not_confused_with_carcase_judging_event(self):
        article = self.article('Australian beef export prices face increased competition')
        self.assertEqual(collector._selection_profile(article, collector.SPECS_BY_KEY['australia'])[0], 0)


if __name__ == '__main__':
    unittest.main()
