"""Recorded public-source clauses and mutations; no network or model calls."""
import unittest

from src import overseas_article_digest as d
from src.article_hwpx_layout import summary_reference_layout
from src.domestic_week_recovery_facts import native_domestic_recovery as native


RECALL = (
    '미국 농무부(USDA) 산하 식품안전검사국(FSIS)은 캘리포니아주에 본사를 둔 샘표식품 미국법인이 '
    '수입·유통한 한국산 삼계탕 완제품 약 4596파운드(약 2.08t)에 대해 공식 리콜을 명령했다. '
    "이번 조치는 제품 자체의 세균 오염이나 성분 변질과 같은 '품질 하자'가 아니라 미국 항만 반입 당시 "
    '필수적으로 거쳐야 하는 FSIS 수입 검사소의 물리적 재검사 절차가 누락된 행정적 결함에서 '
    '비롯된 것으로 확인됐다.'
)
EGG = (
    '농식품부 축산경영과 관계자는 “9월 하순 잠정으로 산지 가격은 6150원(특란 30구)으로, '
    '7월 하순과 비교해 9% 이상 떨어지긴 했지만, 기대한 만큼 안정된 수준은 아니”라면서 '
    '“추석 연휴 전까지 1억3250만개 계란을 수입하고 잠정 중단했는데, 현재 aT가 갖고 있는 '
    '수입란 재고는 없다. 상황에 따라 언제든 추가 수입을 검토할 수 있다”고 밝혔다.'
)
PORK = ('농림축산식품부는 유엔 식량농업기구(FAO)의 9월 세계식량가격지수가 상승했다고 밝혔다. '
        '육류 가격지수는 127.9로 1.1% 하락했다. 브라질의 충분한 수출 공급과 EU의 수입 수요 약화로 '
        '가금육 가격이 내렸고, 돼지고기도 주요 수출국의 풍부한 공급으로 하락했다.')


class DomesticWeekRecoveryFactsTests(unittest.TestCase):
    def test_pork_global_supply_fact_does_not_borrow_poultry_or_aggregate_figures(self):
        summary, evidence = native('domestic_pork', PORK)
        self.assertIn('FAO 9월', summary)
        self.assertIn('주요 수출국의 풍부한 공급', summary)
        for unrelated in ('1.1%', '127.9', '브라질', 'EU'):
            self.assertNotIn(unrelated, summary)
        self.assertTrue(d._valid_brief(summary, 'domestic_pork', PORK))
        self.assertTrue(summary_reference_layout(summary, 'domestic_pork')['withinLineLimit'])
        self.assertLess(len(evidence), 150)
        self.assertEqual(d._native_source_excerpt(PORK, summary), evidence)
        self.assertIn('10월', native('domestic_pork', PORK.replace('9월', '10월'))[0])

    def test_pork_supply_frame_abstains_for_wrong_scope_direction_and_negation(self):
        for changed in (PORK.replace('식량농업기구(FAO)', '세계은행'),
                        PORK.replace('돼지고기도', '쇠고기도'),
                        PORK.replace('풍부한 공급으로 하락했다', '부족한 공급으로 상승했다'),
                        PORK.replace('하락했다.', '하락하지 않았다.')):
            self.assertIsNone(native('domestic_pork', changed), changed)

    def test_actual_clauses_pass_existing_factual_and_one_line_gate(self):
        for kind, body in (('domestic_chicken', RECALL), ('domestic_egg', EGG)):
            with self.subTest(kind=kind):
                result = native(kind, body)
                self.assertIsNotNone(result)
                summary, evidence = result
                self.assertGreaterEqual(len(summary), 40)
                self.assertLessEqual(len(summary), 80)
                self.assertFalse(summary.endswith(('다', '.')))
                self.assertIn(evidence, body)
                self.assertTrue(d._valid_brief(summary, kind, body), d.brief_validation_reasons(summary, kind, body))
                self.assertTrue(summary_reference_layout(summary, kind)['withinLineLimit'])

    def test_recall_preserves_procedural_cause_not_bacterial_hazard(self):
        summary, evidence = native('domestic_chicken', RECALL)
        self.assertIn('4596파운드', summary)
        self.assertIn('약 ', summary)
        self.assertIn('수입 재검사 누락', summary)
        self.assertNotIn('세균', summary)
        self.assertNotIn('2.08', summary)
        self.assertIn('품질 하자', evidence)

    def test_recall_quantity_is_dynamic_not_the_saved_week_weight(self):
        summary, _ = native('domestic_chicken', RECALL.replace('4596파운드', '2,400파운드'))
        self.assertIn('2,400파운드', summary)
        self.assertNotIn('4596', summary)

    def test_recall_rejects_other_species_country_future_or_negated_order(self):
        for changed in (RECALL.replace('한국산 삼계탕', '한국산 돼지고기'),
                        RECALL.replace('한국산 삼계탕', '캐나다산 삼계탕'),
                        RECALL.replace('명령했다', '명령할 예정이다'),
                        RECALL.replace('명령했다', '명령하지 않았다'),
                        RECALL.replace('절차가 누락된', '절차가 누락되지 않은'),
                        RECALL.replace('확인됐다', '확인되지 않았다'),
                        RECALL.replace('이번 조치는', '이번 조치는 다른 원인이다. 다른 제품의 조치는'),
                        RECALL.replace('이번 조치는', '다른 제품의 조치는')):
            self.assertIsNone(native('domestic_chicken', changed), changed)

    def test_egg_keeps_import_pause_and_conditional_possible_review(self):
        summary, evidence = native('domestic_egg', EGG)
        self.assertIn('1억 3250만개', summary)
        self.assertIn('잠정 중단', summary)
        self.assertIn('상황에 따라', summary)
        self.assertTrue(summary.endswith('검토 가능성'))
        self.assertNotIn('재개 확정', summary)
        self.assertNotIn('6150', summary)
        self.assertNotIn('9%', summary)
        self.assertNotIn('가격', evidence)

    def test_egg_quantity_is_dynamic_and_domestic_price_does_not_supply_it(self):
        summary, _ = native('domestic_egg', EGG.replace('1억3250만', '8000만'))
        self.assertIn('8000만개', summary)
        self.assertNotIn('3250', summary)
        for changed in (EGG.replace('계란을 수입하고', '닭고기를 수입하고'),
                        EGG.replace('계란을 수입하고', '계란을 생산하고'),
                        EGG.replace('잠정 중단했는데', '중단하지 않았는데'),
                        EGG.replace('상황에 따라 언제든', '확정적으로'),
                        EGG.replace('검토할 수 있다', '검토할 수 없다'),
                        EGG.replace('수입란 재고는 없다', '수입란 재고는 많다')):
            self.assertIsNone(native('domestic_egg', changed), changed)

    def test_incomplete_unknown_or_wrong_section_source_abstains(self):
        for kind, body in (('domestic', RECALL), ('domestic_pork', RECALL),
                           ('domestic_egg', RECALL), ('domestic_chicken', EGG),
                           ('domestic_egg', '계란 30개 가격 6150원으로 하락했다.'),
                           ('domestic_chicken', RECALL.split('이번 조치')[0]),
                           ('domestic_egg', ''), ('domestic_egg', None)):
            self.assertIsNone(native(kind, body))


if __name__ == '__main__':
    unittest.main()
