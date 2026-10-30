"""Reuse an in-flight native original after the alternate spends call two."""
from concurrent.futures import Future
from datetime import date
from threading import Event
import unittest
from unittest.mock import patch

from src import livestock_article_draft as d
from src import overseas_article_digest as s


DAY = date(2026, 10, 14)
KEY = 'domestic_egg'
READY_BODY = (
    '브라질산 계란 수입가격의 적정성에 대한 논의가 이어졌다. '
    '브라질 상파울루대 농업경제연구센터(CEPEA)에 따르면 현지 계란 산지가격은 '
    '한 알에 100원 안팎이지만, 항공 운송비와 관세 등이 더해지면서 수입가격이 크게 높아졌다.'
)


def original(name, **changes):
    return {'title': '미국 계란 공급과 가격 현지 조사 ' + name,
            'url': 'https://example.org/' + name,
            'publishedDate': date(2026, 10, 13), 'publisher': '검증 매체',
            'body': ('미국 계란 공급은 운송 차질과 현지 수요 회복으로 감소해 가격이 상승했다. '
                     '생산 농가들은 장기적인 사육 여건을 점검하고 주요 수입국의 수급 추이를 검토했다. '
                     '시장 관계자는 향후 수요와 공급 변화를 살펴볼 필요가 있다고 설명했다.'),
            'sourceLanguage': 'ko', 'searchResult': False, 'headlineOnly': False, **changes}


class LateNativeAfterAlternateTests(unittest.TestCase):
    def collect(self, *, completed_links=False, stale_ready=False):
        alternate = original('alternate', title='중국 계란 생산과 수출 동향',
            body=('중국 계란 생산 확대와 내수 수요 부진으로 현지 가격 약세가 나타났다. '
                  '현지 수출 업체들은 해외 시장 판로를 확대하고 장기 계약 비중을 늘리고 있다. '
                  '생산자 단체는 사료 조달 여건과 출하 계획 변화가 시장에 미치는 영향을 분석했다.'))
        main = original('primary', alternatives=[alternate], _candidateLinksSearched=completed_links)
        ready = original('late-native', title='브라질 식탁물가와 항공 운송 부담', body=READY_BODY,
                         publishedDate=date(2026, 10, 10) if stale_ready else date(2026, 10, 13))
        second_call_failed, release_enrichment, enrichment_finished = Event(), Event(), Event()
        actual_native, actual_result = s._native_report_sentence, Future.result
        attempted_titles = []

        def enrichment(candidate, *_args, **_kwargs):
            if candidate['url'] == main['url']:
                self.assertTrue(second_call_failed.wait(5))
                self.assertTrue(release_enrichment.wait(5))
                candidate['_candidateLinkOriginals'] = [ready]
                candidate['_candidateLinksSearched'] = True
                enrichment_finished.set()
            return []

        def future_result(future, *args, **kwargs):
            # Release the existing worker only when the collector actually
            # waits for a future AFTER its second model call. No sleeps/races:
            # before the fix this happens only at the final futures drain,
            # after the item has already been marked incomplete.
            if second_call_failed.is_set():
                release_enrichment.set()
            return actual_result(future, *args, **kwargs)

        def failed_summary(_key, title, _body):
            attempted_titles.append(title)
            s._ollama_generate('one bounded draft for a different original')
            if len(attempted_titles) == 2:
                second_call_failed.set()
            raise s.ArticleSummaryValidationError('요약 검증 미완료: 최소 길이 또는 원문 근거 불일치')

        with patch.object(d, '_usmef_pair', return_value={}), \
             patch.object(d, '_find_section', side_effect=lambda spec, *_:
                          main if spec.key == KEY else None), \
             patch.object(d, '_candidate_links', side_effect=enrichment), \
             patch.object(d, '_search_article', return_value=None) as search, \
             patch.object(s, '_ensure_ollama_ready', return_value={'available': True}), \
             patch.object(s, '_native_report_sentence', side_effect=lambda kind, body:
                          actual_native(kind, body) if body == READY_BODY else None), \
             patch.object(s, '_request_json', return_value={'response': 'invalid draft'}) as request, \
             patch.object(s, '_summarize_report_sentence', side_effect=failed_summary) as summarize, \
             patch.object(Future, 'result', future_result):
            result = d.collect_weekly_livestock_report_draft(DAY)
        self.assertTrue(enrichment_finished.is_set())
        self.assertEqual(request.call_count, 2)
        self.assertEqual(summarize.call_count, 2)
        self.assertEqual({call.args[1] for call in summarize.call_args_list},
                         {main['title'], alternate['title']})
        section = result['sections'][KEY]
        self.assertEqual(section['diagnostics']['modelCalls'], 2)
        return section, ready, search

    def test_last_model_failure_waits_for_existing_native_enrichment_before_research(self):
        for completed_links in (False, True):
            with self.subTest(completed_links=completed_links):
                section, ready, search = self.collect(completed_links=completed_links)
                self.assertEqual(section['status'], 'completed')
                self.assertEqual(section['article']['url'], ready['url'])
                self.assertEqual(section['article']['publishedDate'], '2026-10-13')
                self.assertTrue(s._valid_brief(section['summary'], KEY, READY_BODY))
                self.assertFalse(any(call.args[0].key == KEY for call in search.call_args_list),
                                 'an existing native original must be reused without a new source search')

    def test_waiting_for_late_enrichment_does_not_admit_a_previous_week_original(self):
        section, _ready, search = self.collect(completed_links=True, stale_ready=True)
        self.assertEqual(section['status'], 'summary_error')
        self.assertIsNone(section.get('summary'))
        native_searches = [call for call in search.call_args_list
                           if call.args[0].key == KEY and call.kwargs.get('native_only')]
        self.assertEqual(len(native_searches), 1)


if __name__ == '__main__':
    unittest.main()
