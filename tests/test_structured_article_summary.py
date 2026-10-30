"""Schema syntax helps small local models; factual gates remain independent."""
import json
import unittest
from unittest.mock import patch

from src import overseas_article_digest as s


class StructuredArticleSummaryTests(unittest.TestCase):
    def test_single_summary_is_parsed_and_nominalized(self):
        response = {'response': json.dumps({'summary': '미국 계란 가격은 전년비 5% 상승했고 공급은 비슷한 수준을 유지했다.'}, ensure_ascii=False)}
        with patch.object(s, '_ollama_generate', return_value=response) as generate:
            facts = s._extract_report_facts(kind='us_egg', audience='미국 계란',
                title='Egg prices', body='US egg prices rose 5% on the year. Egg supply was unchanged.',
                headline_only=False, search_result=False)
        self.assertEqual(len(facts), 1)
        self.assertTrue(facts[0].endswith('유지'))
        self.assertEqual(generate.call_args.kwargs['response_format'], s._SUMMARY_RESPONSE_SCHEMA)
        self.assertNotIn('문체 예시', generate.call_args.args[0])

    def test_truncated_json_or_wrong_schema_never_becomes_a_brief(self):
        for raw in ('{"summary":"미국 계란 공급', '{"facts":["계란 공급 증가"]}', '["계란 공급 증가"]'):
            with self.subTest(raw=raw):
                self.assertEqual(s._model_brief_text({'response': raw}), '')

    def test_json_does_not_approve_wrong_source_quantity(self):
        raw = json.dumps({'summary': '미국 계란 가격은 전년비 50% 상승한 가운데 계란 공급은 변동 없이 유지'}, ensure_ascii=False)
        with patch.object(s, '_ollama_generate', return_value={'response': raw}):
            with self.assertRaises(s.ArticleSummaryValidationError):
                s._extract_report_facts(kind='us_egg', audience='미국 계란', title='Egg prices',
                    body='US egg prices rose 5% on the year. Egg supply was unchanged.',
                    headline_only=False, search_result=False)

    def test_plan_is_a_valid_nominal_ending_not_an_observed_result(self):
        draft = '올해 신선 계란 약 1억800만개 수입, 추석 전 매주 약 1000만개 추가 수입 계획이다.'
        normalized = s._normalize_report_sentence(draft, 'domestic_egg')
        self.assertTrue(normalized.endswith('계획'))
        self.assertTrue(s._is_valid_korean_report_sentence(normalized))


if __name__ == '__main__':
    unittest.main()
