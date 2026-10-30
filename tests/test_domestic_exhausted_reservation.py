"""A completed native recovery cannot be replaced by an unaffordable source."""
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
    return {'title': '미국 계란 가격과 공급 여건 조사 ' + name,
            'url': 'https://example.org/' + name,
            'publishedDate': date(2026, 10, 13), 'publisher': '검증 매체',
            'body': ('미국 계란 공급은 유통 차질과 현지 수요 변화로 부족해져 가격이 상승했다. '
                     '이 원문은 공급 부족 원인을 분석하고 주요 수입국의 현지 수급 여건을 설명했다. '
                     '업계 관계자는 장기적인 생산 여건을 확인하며 향후 시장 전망을 제시했다.'),
            'sourceLanguage': 'ko', 'headlineOnly': False, 'searchResult': False,
            **changes}


class DomesticExhaustedReservationTests(unittest.TestCase):
    def collect(self, changes=None):
        main = original('failed-primary')
        shared = original('unattempted-top-tier',
            title='중국 계란 수출 가격과 생산 증가세',
            body=('중국 계란 수출 가격은 현지 생산 확대에 따른 공급 증가로 약세를 보였다. '
                  '농가들은 내수 수요 부진이 지속되는 가운데 해외 수출 비중을 확대하고 있다. '
                  '수출 업계는 장기 계약과 국내 유통 구조 개선을 통한 시장 안정 방안을 논의했다.'))
        ready = original('native-ready-lower-tier',
            title='브라질 식탁물가, 운송비로 수입 부담 확대', body=READY_BODY,
            **(changes or {}))
        if (changes or {}).get('duplicate_failed_alias'):
            ready.pop('duplicate_failed_alias')
            ready['originalUrl'] = main['url']
        spec = d.SPECS_BY_KEY[KEY]
        self.assertEqual(d._selection_profile(main, spec)[0], 0)
        self.assertEqual(d._selection_profile(shared, spec)[0], 0)
        if not changes:
            self.assertEqual(d._selection_profile(ready, spec)[0], 1)
        failed, enrichment_done = Event(), Event()
        actual_native = s._native_report_sentence

        def enrichment(candidate, *_args, **_kwargs):
            if candidate['url'] == main['url']:
                self.assertTrue(failed.wait(4), 'the primary never exhausted its inference allowance')
                candidate['_candidateLinkOriginals'] = [ready, shared]
                candidate['_candidateLinksSearched'] = True
                enrichment_done.set()
            return []

        def summarize(*_args):
            s._ollama_generate('first bounded draft')
            s._ollama_generate('second bounded draft')
            failed.set()
            self.assertTrue(enrichment_done.wait(4))
            raise s.ArticleSummaryValidationError('요약 검증 미완료: 원문 근거 불일치')

        with patch.object(d, '_usmef_pair', return_value={}), \
             patch.object(d, '_find_section', side_effect=lambda spec, *_:
                          main if spec.key == KEY else None), \
             patch.object(d, '_candidate_links', side_effect=enrichment), \
             patch.object(d, '_search_article', return_value=None) as search, \
             patch.object(s, '_ensure_ollama_ready', return_value={'available': True}), \
             patch.object(s, '_native_report_sentence', side_effect=lambda kind, body:
                          actual_native(kind, body) if body == READY_BODY else None), \
             patch.object(s, '_request_json', return_value={'response': 'invalid model draft'}) as request, \
             patch.object(s, '_summarize_report_sentence', side_effect=summarize) as summary:
            result = d.collect_weekly_livestock_report_draft(DAY)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(summary.call_count, 1, 'a shared model-only source cannot reopen inference')
        section = result['sections'][KEY]
        self.assertEqual(section['diagnostics']['modelCalls'], 2)
        return section, ready, main, shared, search

    def test_exhausted_reservation_keeps_ready_tier_one_over_shared_model_only_tier_zero(self):
        section, ready, _main, shared, search = self.collect()
        self.assertEqual(section['status'], 'completed')
        self.assertEqual(section['article']['url'], ready['url'])
        self.assertNotEqual(section['article']['url'], shared['url'])
        self.assertEqual(section['article']['selectionTier'], 1)
        self.assertTrue(s._valid_brief(section['summary'], KEY, READY_BODY))
        self.assertEqual(section['article']['publishedDate'], '2026-10-13')
        self.assertFalse(any(call.args[0].key == KEY for call in search.call_args_list))

    def test_invalid_or_failed_alias_ready_original_is_never_reserved(self):
        for changes in ({'publishedDate': date(2026, 10, 10)},
                        {'publishedDate': date(2026, 10, 18)},
                        {'duplicate_failed_alias': True},
                        {'sourceLanguage': 'en'}, {'searchResult': True}):
            with self.subTest(changes=changes):
                section, _ready, main, _shared, search = self.collect(changes)
                self.assertEqual(section['status'], 'summary_error')
                self.assertIsNone(section.get('summary'))
                self.assertEqual(section['article']['url'], main['url'])
                native_searches = [call for call in search.call_args_list
                                   if call.args[0].key == KEY and call.kwargs.get('native_only')]
                self.assertEqual(len(native_searches), 1)
                self.assertEqual(section['sourceDiagnostics']['nativeRecoveryReady'], 0)


if __name__ == '__main__':
    unittest.main()
