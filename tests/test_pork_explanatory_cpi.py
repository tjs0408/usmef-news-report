"""A CPI headline can contain a substantive, source-stated pork explanation."""
from datetime import date
import unittest
from unittest.mock import patch

from src import overseas_article_digest as s
from src.article_hwpx_layout import summary_reference_layout


REPORT = ('경제통과 재신쾌보에 따르면 중국 국가통계국은 14일 체감경기를 반영하는 '
          '9월 소비자 물가지수(CPI)가 전년 동월보다 0.9% 상승했다고 발표했다.')
FOOD = ('식품 가격은 작년 같은 달보다 1.7% 떨어졌다. '
        '8월 1.4%에 비해 낙폭이 0.3% 포인트 확대, 4개월 만에 최대를 기록했다. '
        '6개월 연속 하락했다.')
CAUSE = ('돼지고기 공급이 충분한 가운데 소비가 부진하면서 돼지고기 가격이 '
         '더 떨어진 게 식품 물가를 끌어내렸다.')
MONTHLY = ('전월 대비로 식품 가격은 0.4% 올라 8월과 같았다. '
           '신선 채소와 돼지고기 및 달걀과 신선 과일 가격은 0.5~2.3% 상승했다.')
BODY = ' '.join((REPORT, FOOD, CAUSE, MONTHLY))
TITLE = '[올댓차이나] 9월 中 소비자물가 0.9%↑…연휴 소비에도 예상 하회'


class PorkExplanatoryCpiTests(unittest.TestCase):
    def tearDown(self):
        s._summarize_report_sentence.cache_clear()

    def test_real_newsis_cause_is_complete_nominal_one_line_without_model(self):
        with patch.object(s, '_ollama_generate') as model:
            summary = s._summarize_report_sentence('domestic_pork', TITLE, BODY)
        model.assert_not_called()
        self.assertEqual(summary, '중국 돼지고기 공급 충분·소비 부진으로 가격 추가 하락, 식품 물가 하락 요인으로 작용')
        self.assertGreaterEqual(len(summary), 40)
        self.assertTrue(s._valid_brief(summary, 'domestic_pork', BODY))
        self.assertTrue(summary_reference_layout(summary, 'domestic_pork')['withinLineLimit'])
        self.assertFalse(summary.endswith(('다', '다.')))
        for unrelated in ('CPI', '0.9%', '1.7%', '1.4%', '0.4%', '0.5', '2.3%', '10%', '10.0%', '전월', '전년'):
            self.assertNotIn(unrelated, summary)

    def test_excerpt_is_exact_country_context_and_exact_causal_sentence(self):
        summary, evidence = s._korean_china_pork_supply_price_cause_fact(BODY)
        self.assertEqual(evidence, REPORT + ' ' + CAUSE)
        self.assertEqual(s._native_source_excerpt(BODY, summary), evidence)
        self.assertNotIn('신선 채소', evidence)
        self.assertNotIn('1.7%', evidence)

    def test_causal_explanation_precedes_a_separate_signed_cpi_statistic(self):
        paired_report = ('중국 국가통계국은 9월 소비자물가지수(CPI)가 전년 동월 대비 '
                         '0.9% 상승했다고 발표했다. 돼지고기(-10.0%) 가격은 하락했다. ')
        body = paired_report + CAUSE
        self.assertIn('10.0%', s._korean_china_pork_cpi_fact(body)[0])
        summary = s._native_report_sentence('domestic_pork', body)
        self.assertIn('공급 충분·소비 부진', summary)
        self.assertNotIn('10.0%', summary)
        self.assertEqual(s._grounded_market_statistic('domestic_pork', body), summary)

    def test_neighbouring_monthly_and_annual_rates_never_become_pork_rates(self):
        for food in (FOOD, FOOD.replace('작년 같은 달보다', '전월보다'),
                     FOOD.replace('1.7%', '7.1%')):
            with self.subTest(food=food):
                summary, _ = s._korean_china_pork_supply_price_cause_fact(' '.join((REPORT, food, CAUSE, MONTHLY)))
                self.assertNotRegex(summary, r'\d|%|전년|전월')
                self.assertIn('가격 추가 하락', summary)

    def test_direction_and_additional_change_follow_the_explicit_cause(self):
        body = BODY.replace('더 떨어진 게', '하락한 것이').replace('끌어내렸다', '낮췄다')
        summary, evidence = s._korean_china_pork_supply_price_cause_fact(body)
        self.assertIn('가격 하락,', summary)
        self.assertNotIn('추가', summary)
        self.assertIn('하락한 것이', evidence)
        self.assertGreaterEqual(len(summary), 40)

    def test_changed_subject_cause_direction_and_incomplete_statement_are_not_facts(self):
        for changed in (
            BODY.replace('돼지고기 공급', '닭고기 공급'),
            BODY.replace('돼지고기 가격이', '닭고기 가격이'),
            BODY.replace('식품 물가를 끌어내렸다', '휘발유 물가를 끌어내렸다'),
            BODY.replace('공급이 충분한', '공급이 부족한'),
            BODY.replace('소비가 부진하면서', '소비가 회복하면서'),
            BODY.replace('더 떨어진', '더 오른'),
            BODY.replace('끌어내렸다.', '끌어내릴 전망이다.'),
            BODY.replace('끌어내렸다.', '끌어내렸다가 아니다.'),
        ):
            with self.subTest(changed=changed):
                self.assertIsNone(s._korean_china_pork_supply_price_cause_fact(changed))

    def test_condition_denial_correction_or_reported_hypothesis_are_rejected(self):
        for changed in (
            BODY.replace(CAUSE, '만약 가정한다면 ' + CAUSE),
            BODY.replace(CAUSE, '가상의 시나리오에 따르면 ' + CAUSE),
            BODY.replace(CAUSE, '잘못된 설명에 따르면 ' + CAUSE),
            BODY.replace(CAUSE, CAUSE + ' 이 설명은 사실이 아니라고 정정했다.'),
            BODY.replace(CAUSE, CAUSE + ' 하지만 이는 허위라고 부인했다.'),
            BODY.replace(CAUSE, '"' + CAUSE + '"라는 주장은 허위다.'),
            BODY.replace(REPORT, '허위 자료에 따르면 ' + REPORT),
            BODY.replace('상승했다고 발표했다.', '상승했다는 주장은 사실이 아니다.'),
        ):
            with self.subTest(changed=changed):
                self.assertIsNone(s._korean_china_pork_supply_price_cause_fact(changed))

    def test_different_country_month_or_historical_report_cannot_inherit_china(self):
        for changed in (
            BODY.replace('중국 국가통계국', '한국 통계청'),
            BODY.replace('9월 소비자', '13월 소비자'),
            BODY.replace('소비자 물가지수(CPI)', '생산자 물가지수(PPI)'),
            BODY.replace(CAUSE, '미국에서는 ' + CAUSE),
            BODY.replace(CAUSE, '미국의 9월 소비자물가가 발표됐다. ' + CAUSE),
            BODY.replace(CAUSE, '10월 ' + CAUSE),
            BODY.replace(CAUSE, '10월 식품 가격을 발표했다. ' + CAUSE),
            BODY.replace(CAUSE, '지난해 9월에는 ' + CAUSE),
        ):
            with self.subTest(changed=changed):
                self.assertIsNone(s._korean_china_pork_supply_price_cause_fact(changed))

    def test_public_selection_metadata_is_separate_from_title_and_brief(self):
        candidate = dict(title=TITLE, url='https://www.newsis.com/view/NISX20261014_0003825548',
                         publisher='뉴시스', publishedDate=date(2026, 10, 14),
                         selectionTier=1, selectionReason='본문 돼지고기 수급·가격 설명',
                         briefBody=CAUSE, privateCredential='must-not-be-public')
        result = s._public_article(candidate)
        self.assertEqual(result['selectionTier'], 1)
        self.assertEqual(result['selectionReason'], candidate['selectionReason'])
        self.assertEqual(result['sourceExcerpt'], CAUSE)
        self.assertNotIn(candidate['selectionReason'], result['title'])
        self.assertNotIn('privateCredential', result)
        for invalid in (True, '1', -1, 3, None):
            with self.subTest(tier=invalid):
                candidate['selectionTier'] = invalid
                result = s._public_article(candidate)
                self.assertNotIn('selectionTier', result)
                self.assertNotIn('selectionReason', result)


if __name__ == '__main__':
    unittest.main()
