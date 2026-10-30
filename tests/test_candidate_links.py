from datetime import date
import unittest
from unittest.mock import patch
from bs4 import BeautifulSoup

from src import livestock_article_draft as d


class CandidateLinksTests(unittest.TestCase):
    def setUp(self):
        self.start, self.end = date(2026, 9, 27), date(2026, 10, 3)
        self.spec = d.SPECS_BY_KEY['us_chicken']

    def article(self, name, **extra):
        return {'title': 'Chicken production market ' + name,
                'url': 'https://example.com/' + name, 'publisher': 'Publisher',
                'publishedDate': self.start, 'body': 'Chicken production market', **extra}

    def test_two_verified_alternatives_without_inference_or_search(self):
        main = self.article('main', alternatives=[self.article('one'), self.article('two')])
        with patch.object(d, '_search_article') as search:
            links = d._candidate_links(main, self.spec, self.start, self.end)
        self.assertEqual([x['url'] for x in links], ['https://example.com/one', 'https://example.com/two'])
        self.assertEqual(set(links[0]), {'title', 'url', 'publisher', 'publishedDate', 'selectionTier', 'selectionReason'})
        search.assert_not_called()

    def test_filter_duplicates_dates_and_unsafe_urls(self):
        main = self.article('main', alternatives=[self.article('main'),
            self.article('old', publishedDate=date(2026, 9, 26)),
            self.article('bad', url='javascript:alert(1)'),
            self.article('one', title='Chicken production market ' + 'X' * 100), self.article('one'), self.article('two')])
        links = d._candidate_links(main, self.spec, self.start, self.end, search_missing=False)
        self.assertEqual(len(links), 2)
        self.assertEqual(len(links[0]['title']), 72)

    def test_search_excludes_main_and_keeps_only_two(self):
        other = self.article('one', alternatives=[self.article('two'), self.article('three')])
        with patch.object(d, '_search_article', return_value=other) as search:
            links = d._candidate_links(self.article('main'), self.spec, self.start, self.end)
        self.assertEqual(len(links), 2)
        self.assertIn('https://example.com/main', search.call_args.kwargs['exclude_urls'])

    def test_optional_search_failure_does_not_fail_main(self):
        with patch.object(d, '_search_article', side_effect=RuntimeError('upstream')):
            self.assertEqual(d._candidate_links(self.article('main'), self.spec, self.start, self.end), [])

    def test_selection_retains_three_verified_originals(self):
        articles = [self.article(str(n)) for n in range(4)]
        with patch.object(d, '_original_article', side_effect=lambda candidate, spec: candidate), \
             patch.object(d, '_relevance', return_value=1):
            chosen = d._choose_original(articles, self.spec, self.start, self.end)
        self.assertEqual(len(chosen['alternatives']), 2)
        self.assertNotIn(chosen['url'], [x['url'] for x in chosen['alternatives']])

    def test_article_metadata_precedes_generic_comment_heading(self):
        body = 'US chicken production increased as demand and exports rose. ' * 8
        soup = BeautifulSoup('<html lang="en"><meta property="og:title" content="US chicken exports rise">'
            '<meta property="article:published_time" content="2026-10-01"><h1>댓글</h1>'
            '<article>' + body + '</article></html>', 'html.parser')
        with patch.object(d.source, '_download_soup', return_value=soup):
            article = d._read_original_article(self.article('one'), self.spec)
        self.assertEqual(article['title'], 'US chicken exports rise')


if __name__ == '__main__':
    unittest.main()
