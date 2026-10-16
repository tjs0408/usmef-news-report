import unittest
from unittest.mock import patch
from src import overseas_article_digest as s
from src.article_hwpx_layout import summary_reference_layout


class ShortBriefExpressionTests(unittest.TestCase):
    def test_grounded_39_character_price_brief_needs_no_second_model_call(self):
        draft = '미국 쇠고기 수입 가격 상승에 국내 공급 부담과 소비자 물가 상승 우려'
        body = ('미국 쇠고기 수입 가격이 상승해 국내 공급 부담이 커졌다. '
                '이로 인한 소비자 물가 상승 우려도 제기됐다.')
        with patch.object(s, '_native_report_sentence', return_value=None), \
             patch.object(s, '_ollama_generate', return_value={'response': draft}) as model:
            summary = s._summarize_report_sentence.__wrapped__('domestic', '미국 쇠고기 가격', body)
        self.assertEqual(model.call_count, 1)
        self.assertGreaterEqual(len(summary), 40)
        self.assertTrue(s._valid_brief(summary, 'domestic', body))
        self.assertTrue(summary_reference_layout(summary, 'domestic')['withinLineLimit'])
        self.assertEqual(s._normalize_report_sentence(summary, 'domestic'), summary)

    def test_spelling_out_origin_preserves_the_origin_species_binding(self):
        original = '미국산 쇠고기와 브라질산 돼지고기 수입 가격'
        expanded = '미국에서 생산한 쇠고기와 브라질에서 생산한 돼지고기 수입 가격'
        self.assertEqual(s._korean_origin_species_pairs(original), s._korean_origin_species_pairs(expanded))

    def test_expansion_does_not_authorize_invented_numbers_or_reverse_direction(self):
        draft = '미국 쇠고기 가격 상승에 따라 국내 수입업체의 구매 비용 부담 증가'
        expanded = s._normalize_report_sentence(draft, 'domestic')
        self.assertFalse(s._valid_brief(expanded, 'domestic', '미국 쇠고기 가격이 하락했고 구매 비용이 감소했다.'))
        self.assertFalse(s._valid_brief(expanded + ' 99%', 'domestic', '미국 쇠고기 가격이 상승했다.'))
        self.assertEqual(s._brief_numeric_values(expanded), s._brief_numeric_values(draft))

    def test_truly_short_statement_is_not_padded_into_completion(self):
        short = '브라질 닭고기 수출 확대'
        self.assertEqual(s._normalize_report_sentence(short, 'brazil_chicken'), short)
        self.assertFalse(s._valid_brief(short, 'brazil_chicken', 'Brasil amplia exportações de carne de frango.'))


if __name__ == '__main__':
    unittest.main()
