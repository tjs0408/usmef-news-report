"""A distinct pork CPI article can replace a reserved multi-species story."""
import unittest
from unittest.mock import patch
from src import overseas_article_digest as s
from src.article_hwpx_layout import summary_reference_layout

BODY = ('중국 국가통계국에 따르면 9월 생산자물가지수(PPI)는 전년비 5.0% 상승했다. '
        '9월 소비자물가지수(CPI)는 전년 동월 대비 0.9% 상승했다. '
        '휘발유 가격은 16.6% 상승했다. 돼지고기(-10.0%)와 신선 채소(-8.1%) 등 식료품 가격은 내려갔다.')


class DomesticPorkCpiTests(unittest.TestCase):
    def test_consumer_month_period_and_pork_rate_are_distinct_from_ppi_and_fuel(self):
        with patch.object(s, '_ollama_generate', side_effect=AssertionError('typed source needs no model')):
            summary = s._summarize_report_sentence.__wrapped__('domestic_pork', '중국 물가', BODY)
        self.assertIn('9월 CPI 전년 동월비 0.9% 상승', summary)
        self.assertIn('돼지고기 가격은 10.0% 하락', summary)
        self.assertTrue(s._valid_brief(summary, 'domestic_pork', BODY))
        self.assertTrue(summary_reference_layout(summary, 'domestic_pork')['oneLine'])
        self.assertNotIn('5.0%', summary)
        self.assertNotIn('16.6%', summary)
        self.assertFalse(s._valid_brief(summary.replace('10.0% 하락', '10.0% 상승'), 'domestic_pork', BODY))

    def test_values_month_and_sign_are_source_driven(self):
        changed = BODY.replace('9월', '8월').replace('0.9%', '1.2%').replace('-10.0%', '+4.5%')
        fact = s._korean_china_pork_cpi_fact(changed)
        self.assertIn('8월 CPI 전년 동월비 1.2%', fact[0])
        self.assertIn('돼지고기 가격은 4.5% 상승', fact[0])
        self.assertTrue(s._valid_brief(fact[0], 'domestic_pork', changed))

    def test_country_index_period_product_and_denial_are_required(self):
        for changed in (BODY.replace('중국', '한국'), BODY.replace('소비자물가지수(CPI)', '생산자물가지수(PPI)'),
                        BODY.replace('전년 동월 대비 0.9%', '전월 대비 0.9%'), BODY.replace('돼지고기', '소고기'),
                        BODY.replace('-10.0%', '10.0%'), BODY + ' 이 수치는 사실이 아니라고 정정했다.'):
            with self.subTest(changed=changed):
                self.assertIsNone(s._korean_china_pork_cpi_fact(changed))


if __name__ == '__main__':
    unittest.main()
