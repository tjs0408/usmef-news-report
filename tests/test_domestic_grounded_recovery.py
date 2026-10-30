"""Source-only poultry trade summaries and bounded domestic alternatives."""
from datetime import date
import unittest
from unittest.mock import patch

from src import overseas_article_digest as s, livestock_article_draft as d
from src.article_hwpx_layout import summary_reference_layout

BODY = ('한국 가공식품의 수출 실적을 집계했다. 올해 7월 말 기준 EU 열처리 가금육 수출액은 '
        '532만달러로 지난해 같은 기간보다 488% 증가한 것으로 나타났다. '
        '열처리 가금육은 닭고기 등을 가열해 만든 가공식품이다. 회사 매출이 아닌 국내 관련 품목 전체의 수출 실적이다.')


class DomesticGroundedRecoveryTests(unittest.TestCase):
    def test_explicit_poultry_sector_trade_is_ready_without_model(self):
        with patch.object(s, '_ollama_generate', side_effect=AssertionError('no inference')):
            summary = s._summarize_report_sentence('domestic_chicken', 'EU 가금육 수출 동향', BODY)
        self.assertIn('대EU', summary)
        self.assertIn('7월 말', summary)
        self.assertIn('532만 달러', summary)
        self.assertIn('전년 동기비 488% 증가', summary)
        self.assertGreaterEqual(len(summary), 40)
        self.assertEqual([], s.brief_validation_reasons(summary, 'domestic_chicken', BODY))
        self.assertTrue(summary_reference_layout(summary, 'domestic_chicken')['oneLine'])
        self.assertNotIn('하림', summary)

    def test_period_synonyms_do_not_disable_comparison_guard(self):
        for period in ('지난해 같은 기간보다', '작년 같은 기간보다', '전년 같은 기간보다'):
            original = '대EU 닭고기 수출액은 ' + period + ' 488% 증가했다.'
            self.assertTrue(s._supported_measurements('대EU 닭고기 수출 전년 동기비 488% 증가', original))
            self.assertFalse(s._supported_measurements('대EU 닭고기 수출 전주비 488% 증가', original))
        self.assertFalse(s._supported_measurements('대EU 닭고기 수출 전년 동기비 488% 증가',
                                                 '대EU 닭고기 수출은 전월 대비 488% 증가했다.'))

    def test_trade_values_destination_cutoff_and_direction_are_not_hardcoded(self):
        changed = BODY.replace('7월 말', '5월').replace('EU', '일본').replace('532만', '421만').replace('488%', '12.5%').replace('증가', '감소')
        summary = s._native_report_sentence('domestic_chicken', changed)
        self.assertIn('대일본', summary)
        self.assertIn('5월', summary)
        self.assertNotIn('월 말', summary)
        self.assertIn('421만 달러', summary)
        self.assertIn('12.5% 감소', summary)
        self.assertTrue(s._valid_brief(summary, 'domestic_chicken', changed))

    def test_poultry_rule_requires_chicken_definition_and_explicit_annual_report(self):
        cases = [BODY.replace('닭고기 등을', '오리고기 등을'),
                 BODY.replace('지난해 같은 기간보다', '전월보다'),
                 BODY.replace('수출액은', '매출액은'),
                 BODY.replace('7월', '17월'),
                 BODY.replace('것으로 나타났다.', '것이 아니라고 정정했다.')]
        for original in cases:
            with self.subTest(original=original):
                self.assertIsNone(s._korean_poultry_export_fact(original))

    def test_company_or_undefined_scope_cannot_become_sector_exports(self):
        no_sector = BODY[:BODY.index('회사 매출이 아닌')]
        for original in (no_sector, '하림의 ' + no_sector,
                         BODY.replace('닭고기 등을 가열해 만든 가공식품이다', '닭고기 등을 뜻하는 것이 아니다'),
                         BODY.replace('국내 관련 품목 전체의 수출 실적이다', '국내 관련 품목 전체의 수출 실적이 아니다')):
            with self.subTest(original=original):
                self.assertIsNone(s._korean_poultry_export_fact(original))

    def test_evidence_shows_sector_statistic_and_product_scope(self):
        summary = s._native_report_sentence('domestic_chicken', BODY)
        excerpt = s._native_source_excerpt(BODY, summary)
        self.assertIn('532만달러', excerpt)
        self.assertIn('지난해 같은 기간', excerpt)
        self.assertIn('닭고기 등', excerpt)

    def test_one_incidental_meat_price_cannot_qualify_macro_trade_article(self):
        article = {'title': '중국 무역흑자 확대, 다음 수출시장은?',
                   'body': '중국 수출액 증가와 무역흑자 확대가 이어졌다. 식품 가격은 1.7% 내렸고 돼지고기는 10% 떨어졌다. ' * 1}
        self.assertFalse(d._domestic_overseas_focus(article, d.SPECS_BY_KEY['domestic_pork']))
        article['title'] = '중국 돼지고기 가격 하락, 수급 동향'
        self.assertTrue(d._domestic_overseas_focus(article, d.SPECS_BY_KEY['domestic_pork']))

    def test_japan_chicken_consumption_keeps_explicit_cause_and_comparison(self):
        body = ('장기간 지속되는 고물가와 엔화 약세의 영향으로 일본에서 닭고기 소비가 '
                '돼지고기 소비를 추월하는 이례적 상황이 이어지고 있습니다.')
        with patch.object(s, '_ollama_generate', side_effect=AssertionError('no inference')):
            summary = s._summarize_report_sentence('domestic_chicken', '일본 닭고기 소비 동향', body)
        self.assertGreaterEqual(len(summary), 40)
        self.assertIn('일본 고물가·엔화 약세', summary)
        self.assertIn('돼지고기를 추월', summary)
        self.assertTrue(summary.endswith('지속'))
        self.assertTrue(summary_reference_layout(summary, 'domestic_chicken')['withinLineLimit'])
        self.assertEqual(s._native_source_excerpt(body, summary), body)
        for original in (body.replace('영향으로', '상관없이'), body.replace('일본에서', '한국에서'),
                         body.replace('상황이 이어지고 있습니다', '상황이 이어지고 있지 않습니다'),
                         body.replace('상황이 이어지고 있습니다', '상황은 허위라고 부인했습니다')):
            with self.subTest(original=original):
                self.assertIsNone(s._korean_japan_chicken_consumption_fact(original))

    def test_attempt_cap_reserves_second_call_without_resetting_overall_budget(self):
        budget = s.ArticleModelBudget()
        with patch.object(s, '_request_json', return_value={'response': 'draft'}) as request:
            with s.article_model_budget(budget, attempt_calls=1):
                s._ollama_generate('first original')
                with self.assertRaises(s.ArticleSummaryBudgetExceeded):
                    s._ollama_generate('same original repair')
            self.assertEqual((budget.calls, budget.max_calls), (1, 2))
            with s.article_model_budget(budget):
                s._ollama_generate('different verified original')
                with self.assertRaises(s.ArticleSummaryBudgetExceeded):
                    s._ollama_generate('third call forbidden')
        self.assertEqual(request.call_count, 2)


if __name__ == '__main__':
    unittest.main()
