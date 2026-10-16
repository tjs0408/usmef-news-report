"""Historical references guide wording/discovery, not current-week facts."""
from datetime import date, timedelta
import json
import unittest
from unittest.mock import patch

from src import report_reference_corpus as corpus
from src import report_brief_style as style
from src import overseas_article_digest as digest


class ReportReferenceCorpusTests(unittest.TestCase):
    def test_reviewed_portable_examples_cover_all_sections_with_provenance(self):
        content = corpus.REFERENCE_PATH.read_text(encoding='utf-8')
        value = json.loads(content)
        self.assertTrue(value['historicalStyleOnly'])
        self.assertNotIn('C:/Users', content)
        self.assertNotIn('C:\\\\Users', content)
        self.assertEqual(set(style.SECTION_AUDIENCES), {row['kind'] for row in value['examples']})
        self.assertGreaterEqual(len(value['examples']), 17)
        for key in style.SECTION_AUDIENCES:
            examples = corpus.historical_style_examples(key)
            self.assertTrue(examples, key)
            self.assertTrue(all(40 <= len(text) <= 95 for text in examples), key)
        for key in style.TWO_LINE_SECTIONS:
            self.assertTrue(any(60 <= len(text) <= 85 for text in corpus.historical_style_examples(key)), key)
        for row in value['examples']:
            date.fromisoformat(row['reportDate'])
            self.assertGreater(row['page'], 0)
            self.assertIn(row['reportOrigin'], ('public-board', 'user-pdf'))

    def test_all_domestic_outlets_are_discovery_seeds_not_species_whitelists(self):
        names = corpus.cited_media_names('domestic_egg')
        self.assertIn('농민신문', names)
        self.assertIn('팜인사이트', names)
        self.assertGreaterEqual(len(names), 20)
        self.assertNotIn('USDA / USDA AMS', names)
        self.assertEqual((), corpus.cited_media_names('us'))
        start = date(2026, 10, 11)
        queries = corpus.cited_media_queries('domestic_egg', start, limit=100)
        self.assertEqual(2, len(queries))
        self.assertEqual(queries, corpus.cited_media_queries('domestic_egg', start))
        self.assertNotEqual(queries, corpus.cited_media_queries('domestic_egg', start + timedelta(days=7)))
        self.assertTrue(all(query.startswith('계란 해외 ') for query in queries))

    def test_invalid_or_missing_reference_file_fails_closed_to_existing_examples(self):
        with patch.object(corpus, 'editorial_reference', return_value={'examples': [
            {'kind': 'us', 'text': 'x' * 70, 'page': 1, 'reportDate': 'wrong'},
            {'kind': 'us', 'text': 'x' * 70, 'page': 0, 'reportDate': '2026-10-01'},
            {'kind': 'us', 'text': 'too short', 'page': 1, 'reportDate': '2026-10-01'},
        ]}):
            self.assertEqual((), corpus.historical_style_examples('us'))

    def test_two_line_prompts_have_context_not_forced_production_numbers(self):
        for key in style.TWO_LINE_SECTIONS:
            prompt = style.style_prompt(key, 'demand supply policy prices')
            self.assertIn('65~85자', prompt)
            self.assertIn('이번 기사 근거가 아니므로 복사하지', prompt)
            self.assertIn('원인 또는 시장 영향', prompt)
            self.assertNotIn('우선 40~50자', prompt)
            self.assertEqual(2, len(style.reference_examples(key)))

    def test_nominal_import_dependence_example_is_complete_not_an_unfinished_verb(self):
        text = '프랑스 닭고기 소비량이 전년비 5.6% 늘고 수입량도 10% 증가하며 소비의 절반 이상을 수입에 의존'
        self.assertTrue(digest._is_valid_korean_report_sentence(text))
        self.assertFalse(digest._is_valid_korean_report_sentence(text[:-2] + '의존하면서'))


if __name__ == '__main__':
    unittest.main()
