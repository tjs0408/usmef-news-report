import unittest
from unittest.mock import patch

from src import overseas_article_digest as s
from src.article_hwpx_layout import summary_reference_layout
from src.usmef_pork_price_frame import native_usmef_pork_price_brief as native


BODY = ('돼지고기 컷아웃 가격은 올해 7월 넷째 주 1.04달러로 연중 최고가를 기록한 이후 '
        '12주 연속 하락세를 이어가고 있다. 지난주 가격은 전주 대비 하락했다. '
        '컷아웃 가격이 전년 동기 수준을 밑돌고 있는 가운데, 4분기 도축 및 생산량이 '
        '본격적으로 증가함에 따라 10월 들어 하락세가 한층 가팔라졌다. '
        '미국의 돼지고기 수출량은 별도로 집계되었다.')


class UsmefPorkPriceFrameTests(unittest.TestCase):
    def test_weekly_cutout_change_preserves_stated_cuts_not_unknown_price_unit(self):
        body = ('지난주 돼지고기 컷아웃 가격은 전주 대비 1.4%(-0.01달러) 하락한 0.97달러를 기록했고, '
                '대분할 belly 부위 가격이 전년 동기를 크게 밑돌며 전체 컷아웃 가격을 끌어내리는 '
                '주된 요인으로 작용하고 있으며, 대분할 ham 부위 역시 주요 하락 요인으로 작용하고 있다. '
                '미국의 돼지고기 수출량은 별도로 집계되었다.')
        summary, _ = native(body)
        self.assertIn('전주비 1.4% 하락', summary)
        self.assertIn('삼겹살·뒷다리 약세', summary)
        self.assertNotIn('0.97', summary)
        self.assertTrue(s._valid_brief(summary, 'us_pork', body))
        self.assertTrue(summary_reference_layout(summary, 'us_pork')['withinLineLimit'])
        changed, _ = native(body.replace('1.4%', '2.1%'))
        self.assertIn('2.1%', changed)
        self.assertIsNone(native(body.replace('ham 부위 역시 주요 하락', 'ham 부위는 오히려 주요 상승')))

    def test_explicit_cause_and_trend_need_no_unstated_dollar_denominator(self):
        summary, evidence = native(BODY)
        self.assertIn('12주 연속 하락', summary)
        self.assertIn('생산 증가로 10월 하락 가속', summary)
        self.assertNotIn('달러', summary)
        self.assertTrue(s._valid_brief(summary, 'us_pork', BODY))
        self.assertTrue(summary_reference_layout(summary, 'us_pork')['withinLineLimit'])
        self.assertIn('4분기 도축 및 생산량', evidence)
        with patch.object(s, '_ollama_generate', side_effect=AssertionError('no model')):
            self.assertEqual(s._native_report_sentence('us_pork', BODY), summary)
        revised = native(BODY.replace('12주', '9주').replace('4분기', '3분기').replace('10월', '8월'))
        self.assertIn('9주', revised[0])
        self.assertIn('8월', revised[0])

    def test_denied_conditional_mixed_species_or_mismatched_period_is_not_a_frame(self):
        for bad in (BODY.replace('증가함에 따라', '증가할 것으로 전망됨에 따라'),
                    BODY.replace('이어가고 있다', '이어가고 있지 않다'),
                    BODY.replace('하락세가 한층 가팔라졌다', '하락세가 한층 가팔라지지 않았다'),
                    BODY.replace('4분기', '1분기'), BODY.replace('돼지고기', '소고기'),
                    BODY + ' 그러나 해당 발표는 오류로 정정했다.'):
            with self.subTest(body=bad):
                self.assertIsNone(native(bad))


if __name__ == '__main__':
    unittest.main()
