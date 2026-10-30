"""Keep a BLS ground-beef monthly price separate from other product figures."""
import unittest
from unittest.mock import patch
from src import overseas_article_digest as s
from src.article_hwpx_layout import summary_reference_layout

BODY = ('미국 노동통계국(BLS)이 발표한 물가 지표에 따르면 지난달 다진 소고기의 평균 가격은 '
        '파운드(약 454g)당 7.062달러(약 9500원)로 나타났다. '
        '이는 사상 최고치를 기록했던 전월보다 1.3% 하락한 수준이다. '
        '전년 동기와 비교하면 6.3% 높은 수치다. 스테이크용 소고기는 파운드당 12.69달러를 기록했다.')


class KoreanBlsBeefPriceTests(unittest.TestCase):
    def test_original_price_and_immediate_monthly_comparison_need_no_model(self):
        with patch.object(s, '_ollama_generate', side_effect=AssertionError('No model required')):
            summary = s._summarize_report_sentence('domestic', '미국 소고기 가격 동향', BODY)
        self.assertIn('다진 소고기', summary)
        self.assertIn('파운드당 7.062달러', summary)
        self.assertIn('전월 대비 1.3% 하락', summary)
        self.assertNotIn('6.3', summary)
        self.assertNotIn('12.69', summary)
        self.assertGreaterEqual(len(summary), 40)
        self.assertTrue(summary_reference_layout(summary, 'domestic')['withinLineLimit'])
        self.assertEqual([], s.brief_validation_reasons(summary, 'domestic', BODY))

    def test_changes_are_captured_not_saved_values(self):
        original = BODY.replace('7.062', '6.123').replace('1.3%', '2.5%').replace('하락', '상승')
        fact = s._korean_bls_ground_beef_price_fact(original)
        self.assertIn('6.123달러', fact[0])
        self.assertIn('2.5% 상승', fact[0])
        self.assertTrue(s._valid_brief(fact[0], 'domestic', original))

    def test_cannot_borrow_steak_price_or_another_period_or_denied_claim(self):
        for original in (BODY.replace('다진 소고기', '스테이크'),
                         BODY.replace('미국 노동통계국(BLS)', '익명 게시물'),
                         BODY.replace('전월보다', '전년보다'),
                         BODY.replace('이는 사상', '스테이크용 가격은 사상'),
                         BODY.replace('하락한 수준이다.', '하락한 수준이 아니다.'),
                         '잘못된 정보라고 반박했다. ' + BODY):
            with self.subTest(original=original):
                self.assertIsNone(s._korean_bls_ground_beef_price_fact(original))

    def test_evidence_is_product_and_own_month_comparison_only(self):
        summary = s._native_report_sentence('domestic', BODY)
        excerpt = s._native_source_excerpt(BODY, summary)
        self.assertIn('다진 소고기', excerpt)
        self.assertIn('1.3%', excerpt)
        self.assertNotIn('스테이크', excerpt)
        self.assertNotIn('6.3%', excerpt)


if __name__ == '__main__':
    unittest.main()
