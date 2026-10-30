"""The first of explicit 'respectively' pork/vegetable rates is pork's rate."""
import unittest
from unittest.mock import patch

from src import overseas_article_digest as s
from src.article_hwpx_layout import summary_reference_layout


BODY = ('중국 국가통계국은 9월 소비자물가지수(CPI)가 전년 동월 대비 0.9% 상승했다고 발표했다. '
        '휘발유 가격은 14.9% 상승했다. 9월 식품 가격은 전년 대비 1.7% 떨어졌으며 '
        '돼지고기 가격과 신선 채소 가격은 각각 10.0%, 8.1% 하락했다. '
        '생산자물가지수(PPI)는 전년 동월 대비 5.0% 상승했다.')


class PorkCpiParallelPricesTests(unittest.TestCase):
    def tearDown(self):
        s._summarize_report_sentence.cache_clear()

    def test_real_source_shape_completes_without_model_or_other_commodity_rates(self):
        with patch.object(s, '_ollama_generate') as model:
            summary = s._summarize_report_sentence('domestic_pork', '중국 물가 상승 제한', BODY)
        model.assert_not_called()
        self.assertIn('9월 CPI 전년 동월비 0.9% 상승', summary)
        self.assertIn('돼지고기 가격은 10.0% 하락', summary)
        self.assertTrue(s._valid_brief(summary, 'domestic_pork', BODY))
        self.assertTrue(summary_reference_layout(summary, 'domestic_pork')['withinLineLimit'])
        for rate in ('14.9%', '1.7%', '8.1%', '5.0%'):
            self.assertNotIn(rate, summary)
        evidence = s._native_source_excerpt(BODY, summary)
        self.assertIn('전년 동월 대비 0.9%', evidence)
        self.assertIn('돼지고기 가격과 신선 채소 가격은 각각 10.0%, 8.1% 하락', evidence)

    def test_month_direction_and_first_ordered_value_follow_the_source(self):
        changed = BODY.replace('9월', '8월').replace('10.0%', '3.2%').replace('8.1%', '11.7%').replace('하락했다', '상승했다')
        summary, _ = s._korean_china_pork_cpi_fact(changed)
        self.assertIn('8월 CPI', summary)
        self.assertIn('돼지고기 가격은 3.2% 상승', summary)
        self.assertNotIn('11.7%', summary)

    def test_period_month_product_order_and_complete_pair_are_required(self):
        for changed in (
            BODY.replace('9월 식품', '8월 식품'),
            BODY.replace('식품 가격은 전년 대비', '식품 가격은 전월 대비'),
            BODY.replace('돼지고기 가격과 신선 채소 가격', '신선 채소 가격과 돼지고기 가격'),
            BODY.replace('돼지고기', '소고기'),
            BODY.replace('각각 10.0%, 8.1%', '각각 10.0%'),
            BODY.replace('각각 10.0%, 8.1%', '대체로 10.0%, 8.1%'),
            BODY.replace('소비자물가지수(CPI)', '생산자물가지수(PPI)'),
            BODY.replace('중국', '한국'),
            BODY.replace('9월 식품', '미국 9월 식품'),
            BODY.replace('9월 소비자물가', '미국 9월 소비자물가'),
            BODY + ' 해당 수치는 사실이 아니라고 정정했다.',
        ):
            with self.subTest(changed=changed):
                self.assertIsNone(s._korean_china_pork_cpi_fact(changed))

    def test_signed_pork_cannot_inherit_other_month_country_or_monthly_period(self):
        lead = '중국 9월 소비자물가지수(CPI)는 전년 동월 대비 0.9% 상승했다. '
        for following in ('10월 돼지고기(-10.0%) 가격은 하락했다.',
                          '전월 대비 돼지고기(-10.0%) 가격은 하락했다.',
                          '미국 9월 돼지고기(-10.0%) 가격은 하락했다.',
                          '미국 9월 CPI는 상승했다. 돼지고기(-10.0%) 가격은 하락했다.',
                          '10월 소비자물가가 발표됐다. 돼지고기(-10.0%) 가격은 하락했다.'):
            with self.subTest(following=following):
                self.assertIsNone(s._korean_china_pork_cpi_fact(lead + following))

    def test_intervening_general_cpi_monthly_rate_does_not_change_annual_food_fact(self):
        body = BODY.replace('휘발유 가격은 14.9% 상승했다.', '전월 대비 소비자물가는 0.2% 상승했다.')
        self.assertIn('돼지고기 가격은 10.0% 하락', s._korean_china_pork_cpi_fact(body)[0])


if __name__ == '__main__':
    unittest.main()
