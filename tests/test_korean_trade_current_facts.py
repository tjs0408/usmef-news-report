"""Completed trade quantities stay with their own commodity and source scope."""
import unittest

from src import overseas_article_digest as digest
from src.article_hwpx_layout import summary_reference_layout
from src.korean_trade_current_facts import native_korean_trade_current_brief


PORK = (
    '제주양돈농협(조합장 고권진)이 몽골에 돼지고기 약 15t을 한꺼번에 수출하며 '
    '단일 수출 물량으로는 역대 최대 실적을 기록했다. '
    '제주양돈농협은 10월말까지 누적 수출량이 100t을 넘어설 것으로 보고 있으며, '
    '연말까지 올해 목표인 140t을 달성할 수 있을 것으로 기대하고 있다.'
)
POULTRY = (
    '올해 1~9월 EU 권역 K-푸드 수출액은 7억2838만 달러로 전년 동기 대비 23.5% 증가했다. '
    '같은 기간 미국과 중국의 수출 증가율은 각각 11.0%, 5.1%였다. '
    '특히 2023년 검역 협상이 타결된 열처리 가금육 수출액은 724만 달러로 '
    '전년 동기 대비 492% 늘었다. '
    '행사에서는 열처리 가금육을 활용한 치킨과 핫도그, 떡볶이 등을 선보였다.'
)


class KoreanTradeCurrentFactsTests(unittest.TestCase):
    def test_single_export_record_keeps_actor_destination_approximation_and_scope(self):
        summary, evidence = native_korean_trade_current_brief('domestic_pork', PORK)
        self.assertEqual(summary,
                         '제주양돈농협, 몽골에 돼지고기 약 15톤 수출하며 단일 수출 물량 역대 최대 기록')
        self.assertIn('단일 수출 물량', summary)
        self.assertNotIn('100톤', summary)
        self.assertNotIn('140톤', summary)
        self.assertNotIn('전국', summary)
        self.assertIn('15t', evidence)
        self.assertTrue(digest._valid_brief(summary, 'domestic_pork', PORK))
        self.assertGreaterEqual(len(summary), 40)
        layout = summary_reference_layout(summary, 'domestic_pork')
        self.assertEqual(layout['bodySizePt'], 12)
        self.assertTrue(layout['withinLineLimit'])
        self.assertGreaterEqual(layout['tracking'], -20)

    def test_pork_values_actor_destination_and_precision_are_not_week_constants(self):
        changed = PORK.replace('제주양돈농협', '한돈유통').replace('몽골', '싱가포르').replace('약 15t', '약 18.5ｔ')
        summary, _ = native_korean_trade_current_brief('domestic_pork', changed)
        self.assertIn('한돈유통, 싱가포르에 돼지고기 약 18.5톤', summary)
        self.assertNotIn('15톤', summary)
        self.assertTrue(digest._supported_measurements(summary, changed))
        precise = PORK.replace('약 15t', '15톤')
        self.assertNotIn('약 ', native_korean_trade_current_brief('domestic_pork', precise)[0])

    def test_pork_forecast_denial_different_product_and_record_scope_are_not_actual(self):
        for original in (
            PORK.replace('돼지고기', '쇠고기'),
            PORK.replace('수출하며', '수출하지 않았으며'),
            PORK.replace('기록했다', '기록할 계획이다'),
            PORK.replace('단일 수출 물량으로는', '연간 수출액으로는'),
            PORK.replace('단일 수출 물량으로는', '국내 총수출 물량으로는'),
            PORK.replace('약 15t', '약 0t'),
        ):
            with self.subTest(original=original):
                self.assertIsNone(native_korean_trade_current_brief('domestic_pork', original))
        self.assertIsNone(native_korean_trade_current_brief('domestic_chicken', PORK))

    def test_export_record_retracted_by_next_original_sentence_is_not_used(self):
        original = PORK.split('. ', 1)[0] + '. 해당 수치는 잘못된 발표로 정정됐다.'
        self.assertIsNone(native_korean_trade_current_brief('domestic_pork', original))

    def test_poultry_own_value_and_rate_keep_eu_and_adjacent_monthly_period(self):
        summary, evidence = native_korean_trade_current_brief('domestic_chicken', POULTRY)
        self.assertEqual(summary,
                         '올해 1~9월 EU 열처리 가금육 수출액 724만달러, 전년 동기비 492% 증가')
        self.assertIn('올해 1~9월 EU', summary)
        self.assertIn('가금육', summary)  # Do not narrow all poultry to a chicken example.
        self.assertNotIn('23.5%', summary)
        self.assertNotIn('7억2838만', summary)
        self.assertNotIn('11.0%', summary)
        self.assertNotIn('5.1%', summary)
        self.assertIn('724만 달러', evidence)
        self.assertTrue(digest._supported_measurements(summary, POULTRY))
        self.assertGreaterEqual(len(summary), 40)
        layout = summary_reference_layout(summary, 'domestic_chicken')
        self.assertEqual(layout['bodySizePt'], 12)
        self.assertTrue(layout['withinLineLimit'])
        self.assertGreaterEqual(layout['tracking'], -20)

    def test_poultry_period_currency_values_and_destination_are_dynamic(self):
        changed = (POULTRY.replace('올해 1~9월 EU', '지난해 2~8월 유럽연합(EU)')
                   .replace('724만 달러', '931만 달러').replace('492%', '87.6%'))
        summary, _ = native_korean_trade_current_brief('domestic_chicken', changed)
        self.assertIn('지난해 2~8월 EU', summary)
        self.assertIn('931만달러', summary)
        self.assertIn('87.6%', summary)
        self.assertNotIn('492%', summary)
        self.assertTrue(digest._supported_measurements(summary, changed))
        foreign = POULTRY.replace('1~9월 EU 권역', '1~9월 영국 권역')
        self.assertIn('1~9월 영국', native_korean_trade_current_brief('domestic_chicken', foreign)[0])

    def test_poultry_does_not_borrow_other_period_destination_product_or_planned_statistic(self):
        for original in (
            POULTRY.replace('열처리 가금육 수출액은', '열처리 돼지고기 수출액은'),
            POULTRY.replace('492% 늘었다', '492% 늘어날 전망이다'),
            POULTRY.replace('492% 늘었다', '492% 늘지 않았다'),
            POULTRY.replace('492% 늘었다', '492%로 확대할 계획이다'),
            POULTRY.replace('올해 1~9월 EU', '올해 1~13월 EU'),
            POULTRY.replace('올해 1~9월 EU', '올해 9~1월 EU'),
            POULTRY.replace('724만 달러', '724만 유로'),
            POULTRY.replace('전년 동기 대비 492%', '전월 대비 492%'),
            POULTRY.replace('같은 기간 미국과 중국의 수출 증가율은 각각 11.0%, 5.1%였다.',
                            '미국은 지난해 3월부터 닭고기 수출을 확대했다.'),
            POULTRY.replace('같은 기간 미국과 중국의 수출 증가율은 각각 11.0%, 5.1%였다.',
                            '식품업계는 돼지고기 수출액이 증가했다고 밝혔다.'),
        ):
            with self.subTest(original=original):
                self.assertIsNone(native_korean_trade_current_brief('domestic_chicken', original))
        no_period = '열처리 가금육 수출액은 724만 달러로 전년 동기 대비 492% 늘었다.'
        self.assertIsNone(native_korean_trade_current_brief('domestic_chicken', no_period))
        self.assertIsNone(native_korean_trade_current_brief('domestic_pork', POULTRY))

    def test_poultry_value_correction_is_not_saved_by_earlier_valid_period(self):
        original = POULTRY.replace('행사에서는', '이 수치는 오류로 정정됐다. 행사에서는')
        self.assertIsNone(native_korean_trade_current_brief('domestic_chicken', original))


if __name__ == '__main__':
    unittest.main()
