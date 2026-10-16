import unittest
from unittest.mock import patch
from src import overseas_article_digest as s
from src.article_hwpx_layout import summary_reference_layout


BRAZIL = (
    'Por enquanto, o Brasil conserva uma vantagem expressiva no comércio mundial de carne de frango, '
    'sustentada por sua estrutura de produção, capacidade industrial e presença em diferentes mercados consumidores. '
    'A China pretende ocupar um espaço maior nas exportações.'
)
RECALL = (
    '연방농무부(USDA) 식품안전검사국(FSIS)은 한국에서 수입한 즉석 닭고기 스튜 '
    '제품 약 4,596파운드를 리콜한다고 밝혔다. '
    '리콜 사유는 해당 제품이 미국 반입 당시 수입 재검사를 받지 않았기 때문이다.'
)
STORAGE = (
    'Beef Central is aware of at least two, and possibly three export beef plants that have lost production '
    'days simply because they have run out of cold storage – either for China, or other markets. '
    'The majority of Australian Wagyu heading for China is in frozen form. '
    'One plant is now 2000-2500 head behind its schedule, although we have been unable to confirm that.'
)


class CurrentTradeAndRecallTests(unittest.TestCase):
    def test_confirmed_source_clauses_pass_without_model(self):
        for kind, body in (('brazil_chicken', BRAZIL), ('domestic_chicken', RECALL), ('australia', STORAGE)):
            with self.subTest(kind=kind), patch.object(s, '_ollama_generate') as model:
                s._summarize_report_sentence.cache_clear()
                summary = s._summarize_report_sentence(kind, 'title', body)
                model.assert_not_called()
                self.assertGreaterEqual(len(summary), 40)
                self.assertTrue(s._valid_brief(summary, kind, body))
                self.assertTrue(summary_reference_layout(summary, kind)['withinLineLimit'])

    def test_storage_brief_omits_unconfirmed_volume_and_requires_actual_disruption(self):
        summary = s._australian_beef_cold_storage_summary(STORAGE)
        self.assertNotIn('2000', summary)
        self.assertNotIn('2500', summary)
        self.assertIn('생산 일정 차질', summary)
        for body in (STORAGE.replace('have lost', 'have not lost'),
                     STORAGE.replace('run out of cold storage', 'ample cold storage'),
                     STORAGE.replace('Australian Wagyu', 'US Wagyu')):
            self.assertIsNone(s._australian_beef_cold_storage_summary(body))

    def test_recall_requires_product_and_own_inspection_reason(self):
        for body in (RECALL.replace('닭고기', '돼지고기'),
                     RECALL.replace('수입 재검사를 받지 않았기', '포장 오류가 발생했기'),
                     RECALL.replace('리콜한다고 밝혔다', '리콜하지 않는다고 밝혔다')):
            self.assertIsNone(s._korean_poultry_recall_summary(body))

    def test_brazil_trade_advantage_requires_the_same_product_and_stated_basis(self):
        for body in (BRAZIL.replace('conserva uma vantagem', 'não conserva uma vantagem'),
                     BRAZIL.replace('carne de frango', 'carne suína'),
                     BRAZIL.replace('capacidade industrial', 'falta de capacidade industrial')):
            self.assertIsNone(s._brazil_chicken_trade_advantage_summary(body))


if __name__ == '__main__':
    unittest.main()
