"""A stale/manual payload must not put the same original in two report boxes."""
import unittest
from src.article_hwpx import ArticleHwpxError, _draft_values
from test_article_hwpx import _draft


class HwpxDomesticDuplicateGuardTests(unittest.TestCase):
    def test_shared_original_url_is_rejected_before_document_editing(self):
        draft = _draft()
        draft['sections']['domestic']['article']['url'] = 'https://example.org/current?id=17'
        draft['sections']['domestic_pork']['article']['originalUrl'] = 'http://www.example.org/current?utm_source=feed&id=17'
        with self.assertRaisesRegex(ArticleHwpxError, '같은 기사'):
            _draft_values(draft)

    def test_blank_duplicate_is_not_reinserted_or_a_download_blocker(self):
        draft = _draft()
        article = draft['sections']['domestic']['article']
        draft['sections']['domestic_pork'] = {'status': 'summary_error', 'article': dict(article)}
        values = _draft_values(draft)
        self.assertTrue(values['domestic'][0])
        self.assertEqual(('', None), values['domestic_pork'])

    def test_distinct_originals_about_similar_markets_are_allowed(self):
        draft = _draft()
        values = _draft_values(draft)
        self.assertEqual(len(values), 12)


if __name__ == '__main__':
    unittest.main()
