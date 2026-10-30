"""Real generation paths must use structure without copying archived facts."""
from datetime import date
import json
from time import monotonic
import unittest
from unittest.mock import patch

from src import report_style_retrieval as r
from src import overseas_article_digest as d
from src import livestock_article_draft as c


class StyleRetrievalTests(unittest.TestCase):
    def test_all_twelve_have_crosschecked_portable_references(self):
        self.assertEqual(r.style_corpus()['scope']['reportCount'], 90)
        for kind in r._KINDS:
            items = r._reviewed_examples(kind)
            self.assertGreaterEqual(len(items), 2, kind)
            self.assertTrue(all(x['originalText'] and x['reviewStatus'] == 'reviewed-paraphrase' for x in items))

    def test_source_specific_structure_has_no_historical_claim_or_number(self):
        context = 'US pork production remains high but Mexico export demand supports prices.'
        guidance, ref = r.source_style_guidance('us_pork', context)
        self.assertEqual(ref['kind'], 'us_pork')
        self.assertIn('구성', guidance)
        self.assertNotIn('멕시코', guidance)
        self.assertNotIn('크리스마스', guidance)
        self.assertFalse(any(ch.isdigit() for ch in guidance))
        self.assertNotIn(r.reference_for_source('us_pork', context)['text'], guidance)

    def test_plain_statistic_never_gets_invented_cause_or_forecast_recipe(self):
        guidance, ref = r.source_style_guidance('us_egg', 'US egg production rose 6% on year.')
        self.assertEqual(ref['pattern'], 'market_change')
        self.assertIn('비교기간', guidance)
        self.assertIsNone(r.reference_for_source('unknown', 'egg prices'))
        self.assertEqual(r.source_style_guidance('us', 'navigation contacts'), ('', None))

    def test_all_four_actual_model_prompts_receive_retrieved_structure(self):
        body = 'US egg prices rose 5% on the year. Egg supply was unchanged.'
        summary = '미국 계란 가격은 전년비 5% 상승했고 공급은 비슷한 수준을 유지했다.'
        result = {'response': json.dumps({'summary': summary}, ensure_ascii=False)}
        budget = d.ArticleModelBudget()
        with d.article_model_budget(budget), patch.object(d, '_ollama_generate', return_value=result) as generate:
            d._extract_report_facts(kind='us_egg', audience='미국 계란', title='Egg prices', body=body,
                                   headline_only=False, search_result=False)
            d._compose_report_sentence(kind='us_egg', audience='미국 계란', facts=[body])
            d._repair_korean_report_sentence(kind='us_egg', audience='미국 계란', facts=[body], draft='')
            with patch.object(d, '_extract_usmef_source_summary', return_value=None):
                d._summarize_usmef_market_sentence(title='소 시장', body='미국 소고기 수요 증가로 가격이 상승했다.')
        self.assertEqual(generate.call_count, 4)
        for call in generate.call_args_list:
            self.assertIn('기존 보고서 문장 구성:', call.args[0])
            self.assertIn('요약 대상:', call.args[0])
            self.assertIn('수급·가격', call.args[0])
            self.assertNotIn('문체 예시:', call.args[0])
            self.assertEqual(call.kwargs['num_predict'], 128)
        self.assertEqual({item['kind'] for item in budget.style_references}, {'us', 'us_egg'})
        self.assertTrue(all(x['mode'] == 'retrieved_structure_only' for x in budget.style_references))

    def test_structure_does_not_relax_original_measurement_validation(self):
        wrong = '미국 계란 가격은 전년비 50% 상승한 가운데 계란 공급은 변동 없이 유지'
        with patch.object(d, '_ollama_generate', return_value={'response': json.dumps({'summary': wrong})}):
            with self.assertRaises(d.ArticleSummaryValidationError):
                d._extract_report_facts(kind='us_egg', audience='미국 계란', title='Egg prices',
                    body='US egg prices rose 5% on the year. Egg supply was unchanged.', headline_only=False, search_result=False)

    def test_retrieval_is_cached_and_bounded_without_model_or_archive_io(self):
        r.source_style_guidance('us', 'US beef demand prices supply')
        started = monotonic()
        for _ in range(100):
            guidance, reference = r.source_style_guidance('us', 'US beef demand prices supply')
            self.assertLess(len(guidance), 160)
            self.assertIsNotNone(reference)
        self.assertLess(monotonic() - started, 1)

    def test_real_relevance_path_cannot_promote_a_rejected_story(self):
        spec = c.SPECS_BY_KEY['domestic_pork']
        rejected = {'title': '휘발유 가격 상승', 'body': '휘발유값 상승으로 운송비가 올랐다.'}
        with patch.object(c, 'editorial_selection_bonus', return_value=8):
            self.assertEqual(c._relevance(rejected, spec), -1)
        direct = {'title': '중국 돼지고기 가격 하락', 'body': '중국 돼지고기 가격은 공급 증가 영향으로 전년비 8% 하락했다.'}
        with patch.object(c, '_selection_profile', return_value=(0, 995, 'direct')):
            self.assertEqual(c._relevance(direct, spec), 2999)

    def test_native_preselection_uses_editorial_fit_within_equal_tier_and_readiness(self):
        spec = c.SPECS_BY_KEY['us_pork']
        day = date(2026, 10, 21)
        plain = {'title': 'US pork production', 'body': 'US pork production rose 2% on the year. ' * 3,
                 'url': 'https://example.org/plain', 'publishedDate': day}
        issue = {'title': 'US pork demand', 'body': 'US pork prices rose due to stronger demand despite higher production. ' * 3,
                 'url': 'https://example.org/issue', 'publishedDate': day}
        summary = '미국 돼지고기는 생산량 증가에도 소비 수요 개선에 따라 도매가격 상승세 지속'
        with patch.object(c, '_selection_profile', return_value=(0, 30, 'direct')), \
             patch.object(d, '_native_report_sentence', return_value=summary), \
             patch.object(d, '_fit_report_summary', return_value=summary), \
             patch.object(d, '_valid_brief', return_value=True), \
             patch.object(d, '_native_source_excerpt', return_value='evidence'):
            found = c._prefer_native_summary_candidate({**plain, 'alternatives': [issue]}, spec, day, day)
        self.assertEqual(found['url'], issue['url'])
        self.assertEqual(found['editorialFit']['bonus'], 8)


if __name__ == '__main__':
    unittest.main()
