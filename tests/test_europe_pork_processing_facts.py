"""Pork processing material equivalents must not become live-animal exports."""
import unittest
from unittest.mock import patch

from src.europe_pork_processing_facts import native_europe_pork_processing_brief as native
from src.article_hwpx_layout import summary_reference_layout
from src import overseas_article_digest as s


BODY = (
    "Danish Crown’s Polish business, Sokołów, will now breed more Danish pigs. "
    "This will increase the value of the cooperative owners’ slaughter pigs. "
    "It is not new that Danish pork is being sent to Poland. "
    "But in the coming months, a larger portion of the raw materials from Danish Crown’s shareholders "
    "will be processed in Sokołów, the group’s Polish business. "
    "Specifically, Danish Crown plans to send raw materials equivalent to around 500,000 pigs per year "
    "to Sokołów, and in the longer term the ambition is to double that number. "
    "Sokołów produces cold cuts, sausages and pâtés for Polish consumers and has a processing degree "
    "of more than 70 percent."
)


class EuropePorkProcessingFactsTests(unittest.TestCase):
    def test_final_gate_does_not_turn_equivalent_plan_into_slaughter_or_completed_trade(self):
        summary, _ = native(BODY)
        self.assertTrue(s._valid_brief(summary, 'eu_pork', BODY))
        for wrong in (summary.replace('공급 계획', '공급 완료'),
                      summary.replace('원료 ', '').replace(' 상당', ''),
                      summary.replace('연간 ', ''), summary.replace('약 ', ''),
                      '덴마크 돼지의 연간 도축두수는 폴란드 가공업체의 공급 확대로 약 50만두 증가'):
            with self.subTest(summary=wrong):
                self.assertFalse(s._valid_brief(wrong, 'eu_pork', BODY))

    def test_actual_plan_keeps_origin_destination_raw_equivalent_period_and_modality(self):
        with patch.object(s, '_ollama_generate', side_effect=AssertionError('no inference')):
            fact = native(BODY)
        self.assertIsNotNone(fact)
        summary, evidence = fact
        for token in ('덴마크산 돼지고기 원료', '폴란드', '연간 약 50만두 상당', '공급 계획'):
            self.assertIn(token, summary)
        self.assertGreaterEqual(len(summary), 40)
        self.assertTrue(summary_reference_layout(summary, 'eu_pork')['oneLine'])
        self.assertGreaterEqual(summary_reference_layout(summary, 'eu_pork')['tracking'], -20)
        for forbidden in ('생돈', '생우', '수출량', '도축두수', '실적', '100만', '두 배', '70%'):
            self.assertNotIn(forbidden, summary)
        self.assertIn('raw materials equivalent to around 500,000 pigs per year', evidence)
        self.assertIn('Polish business', evidence)
        self.assertNotIn('will now breed', evidence)

    def test_quantity_company_target_and_approximation_follow_original(self):
        for value, expected in (('750,000', '75만'), ('250000', '25만'),
                                ('0.65 million', '65만'), ('425 thousand', '42만 5000')):
            with self.subTest(value=value):
                summary, _ = native(BODY.replace('500,000', value))
                self.assertIn(expected + '두 상당', summary)
                self.assertNotIn('50만두', summary)
        exact, _ = native(BODY.replace('around ', ''))
        self.assertIn('연간 50만두 상당', exact)
        self.assertNotIn('약', exact)
        changed, evidence = native(BODY.replace('Sokołów', 'Sokolow'))
        self.assertIn('폴란드', changed)
        self.assertIn('to Sokolow', evidence)

    def test_plan_and_processing_grammar_variants_remain_future_plans(self):
        for before, after in (('plans to', 'intends to'), ('plans to', 'is planning to'),
                              ('per year', 'annually'), ('around', 'approximately')):
            with self.subTest(after=after):
                summary, _ = native(BODY.replace(before, after))
                self.assertIn('연간 약 50만두 상당', summary)
                self.assertTrue(summary.endswith('공급 계획'))

    def test_other_country_commodity_business_and_denominator_cannot_be_inferred(self):
        for changed in (BODY.replace('Danish pork', 'Canadian pork'),
                        BODY.replace('sent to Poland', 'sent to Canada'),
                        BODY.replace('Polish business', 'German business'),
                        BODY.replace('shareholders will be processed', 'shareholders have been processed'),
                        BODY.replace('raw materials equivalent to', 'live pigs equivalent to'),
                        BODY.replace('per year', 'per month'),
                        BODY.replace('per year ', ''),
                        BODY.replace('pigs per year', 'cattle per year'),
                        BODY.replace('to Sokołów, and', 'to Another Company, and')):
            with self.subTest(changed=changed):
                self.assertIsNone(native(changed))

    def test_denial_cancellation_conditional_and_realized_results_are_refused(self):
        for changed in (BODY.replace('plans to send', 'does not plan to send'),
                        BODY.replace('Danish Crown plans', 'It is not true that Danish Crown plans'),
                        BODY.replace('will be processed', 'will not be processed'),
                        BODY.replace('plans to send', 'has already sent'),
                        BODY.replace('will be processed', 'has already processed'),
                        BODY.replace('to Sokołów, and', 'to Sokołów if approval is granted, and'),
                        BODY.replace('to Sokołów, and', 'to Sokołów subject to approval, and'),
                        BODY + ' The processing plan was cancelled.',
                        BODY + ' This report was incorrect and the announcement was withdrawn.',
                        BODY + ' The plan was suspended pending regulatory approval.'):
            with self.subTest(changed=changed):
                self.assertIsNone(native(changed))

    def test_incomplete_or_non_positive_quantity_is_refused(self):
        for value in ('0', '-500,000', '12.5', 'unknown'):
            with self.subTest(value=value):
                self.assertIsNone(native(BODY.replace('500,000', value)))
        self.assertIsNone(native(BODY.replace('It is not new that Danish pork is being sent to Poland. ', '')))


if __name__ == '__main__':
    unittest.main()
