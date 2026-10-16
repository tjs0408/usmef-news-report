from datetime import date
from threading import Event
import unittest
from unittest.mock import patch

from src import livestock_article_draft as d
from src import overseas_article_digest as s


class IncrementalNativeTests(unittest.TestCase):
    def test_later_native_result_is_visible_during_another_model_request(self):
        inference_started, native_visible = Event(), Event()
        summary = '일본 계란의 공식 시장가격과 공급 상황을 확인한 주간 시장 동향 기록'

        def article(key):
            return {'url': 'https://example.org/' + key, 'title': key,
                    'publishedDate': date(2026, 10, 14), 'body': key * 140,
                    'sourceLanguage': 'en', 'publisher': 'Test'}

        def find(spec, *_):
            if spec.key == 'japan_egg':
                if not inference_started.wait(4):
                    raise AssertionError('model never started')
                return article(spec.key)
            return article(spec.key) if spec.key == 'australia' else None

        def prepared(candidate, spec, *_):
            if spec.key == 'japan_egg':
                return {**candidate, '_nativeReadySummary': (spec.key, candidate['body'], summary)}
            return candidate

        def infer(*_):
            inference_started.set()
            self.assertTrue(native_visible.wait(4), 'native result waited for slow inference')
            return '호주 시장의 원문을 근거로 가격과 수급 변화를 정리한 한국어 초안'

        def progress(**event):
            if event['sections']['japan_egg'].get('summary') == summary:
                native_visible.set()

        with patch.object(d, '_usmef_pair', return_value={}), \
             patch.object(d, '_search_article', return_value=None), \
             patch.object(d, '_find_section', side_effect=find), \
             patch.object(d, '_prefer_native_summary_candidate', side_effect=prepared), \
             patch.object(d, '_candidate_links', return_value=[]), \
             patch.object(s, '_native_source_excerpt', return_value='original evidence'), \
             patch.object(s, '_native_report_sentence', return_value=None), \
             patch.object(s, '_ensure_ollama_ready', return_value={'available': True}), \
             patch.object(s, '_summarize_report_sentence', side_effect=infer):
            result = d.collect_weekly_livestock_report_draft(date(2026, 10, 14), progress=progress)
        self.assertTrue(native_visible.is_set())
        self.assertEqual(result['sections']['japan_egg']['status'], 'completed')
        self.assertEqual(result['sections']['japan_egg']['diagnostics']['modelCalls'], 0)
        self.assertEqual(result['sections']['australia']['status'], 'completed')


if __name__ == '__main__':
    unittest.main()
