"""One original/reprint per domestic species, with bounded valid replacement."""
from datetime import date
from threading import Event
import unittest
from unittest.mock import patch

from src import livestock_article_draft as d
from src import overseas_article_digest as s


DAY = date(2026, 10, 7)
CPTPP = (
    '정부는 CPTPP 가입 논의를 시작했다. 호주산 쇠고기, 멕시코산 쇠고기·돼지고기, '
    '캐나다산 돼지고기·닭고기, 뉴질랜드산 전지분유 등의 수입 증가가 국내 생산 감소로 이어질 수 있다는 전망이다.'
)
PORK = (
    '육류 가격지수는 전월보다 1.1% 하락한 127.9포인트를 기록했다. '
    'EU의 수입 규제 강화에 따른 가금육 수요 약화와 폭염 이후 가축 성장률을 회복한 '
    '유럽산 돼지고기 공급 증가가 하락을 주도했다.'
)
BEEF = (
    '중국이 남미의 친중 국가인 브라질의 소고기 수입품에 대해 1일부터 55%의 추가 관세를 부과한다고 상무부가 발표했다. '
    '상무부는 올해 브라질 소고기 수입 할당량이 100% 소진됐다고 이유를 밝혔다.'
)


def article(name, **changes):
    return {'url': 'https://example.org/' + name, 'title': 'CPTPP 가입과 해외 축산물 수입 증가 가능성',
            'publisher': '검증 매체', 'body': CPTPP, 'sourceLanguage': 'ko',
            'publishedDate': date(2026, 10, 6), **changes}


class DomesticIdentityTests(unittest.TestCase):
    def test_original_alias_tracking_and_naver_legacy_aliases(self):
        first = article('news?id=17&utm_source=feed')
        second = article('different', originalUrl='http://www.example.org/news?utm_medium=mail&id=17')
        self.assertTrue(d._same_domestic_article(first, second))
        first = article('direct', publicNewsUrl='https://n.news.naver.com/mnews/article/001/0012345678?sid=101')
        second = article('other', originalUrl='https://news.naver.com/main/read.naver?mode=LSD&oid=001&aid=0012345678')
        self.assertTrue(d._same_domestic_article(first, second))

    def test_normalized_headline_same_outlet_and_syndicated_body(self):
        first = article('first')
        second = article('reprint', title='“CPTPP 가입과 해외 축산물 수입 증가 가능성”')
        self.assertTrue(d._same_domestic_article(first, second))
        first['body'] = CPTPP * 3
        second = article('syndicated', title='무역 협정으로 해외 육류 수입 확대 우려', publisher='다른 매체', body=CPTPP * 3)
        self.assertTrue(d._same_domestic_article(first, second))

    def test_independent_same_topic_is_not_a_duplicate(self):
        first = article('first', body=CPTPP * 2)
        second = article('second', title='CPTPP 가입 협의 속 멕시코 돼지고기 수출시장 변화',
                         publisher='다른 매체', body=PORK * 2)
        self.assertFalse(d._same_domestic_article(first, second))

    def test_recovery_excludes_reserved_original_and_its_reprint(self):
        main = article('main', title='미국 돼지고기 수급과 가격 동향 분석', body='미국 돼지고기 공급과 수요를 확인했다. ' * 5)
        used = article('used')
        reprint = article('republished', title='“CPTPP 가입과 해외 축산물 수입 증가 가능성”')
        valid = article('pork', title='EU 돼지고기 공급 증가로 국제 가격 하락', body=PORK)
        found = d._verified_summary_alternatives(main, d.SPECS_BY_KEY['domestic_pork'],
            date(2026, 10, 4), date(2026, 10, 10), [used, reprint, valid], (used,))
        self.assertEqual([item['url'] for item in found], [valid['url']])


class DomesticSelectionTests(unittest.TestCase):
    def collect(self, found, *, extra=None):
        def supplemental(spec, *_args, **_kwargs):
            return extra if spec.key == 'domestic_pork' else None
        with patch.object(d, '_usmef_pair', return_value={}), \
             patch.object(d, '_find_section', side_effect=lambda spec, *_: found.get(spec.key)), \
             patch.object(d, '_search_article', side_effect=supplemental) as search, \
             patch.object(s, '_ensure_ollama_ready', return_value={'available': False, 'message': 'offline'}), \
             patch.object(s, '_summarize_report_sentence', side_effect=AssertionError('No model call required')):
            result = d.collect_weekly_livestock_report_draft(DAY)
        return result, search

    def test_existing_pork_specific_alternate_replaces_shared_article(self):
        shared = article('shared')
        pork = article('pork', title='EU 돼지고기 공급 증가로 국제 가격 하락', body=PORK)
        result, _ = self.collect({'domestic': shared, 'domestic_pork': {**shared, 'alternatives': [pork]}})
        beef, selected_pork = (result['sections'][key] for key in ('domestic', 'domestic_pork'))
        self.assertEqual(beef['status'], 'completed')
        self.assertEqual(selected_pork['status'], 'completed')
        self.assertEqual(selected_pork['article']['url'], pork['url'])
        self.assertNotEqual(beef['summary'], selected_pork['summary'])
        self.assertEqual(selected_pork['diagnostics']['modelCalls'], 0)
        self.assertFalse(any(link['url'] == shared['url'] for link in selected_pork['candidateLinks']))

    def test_bounded_supplemental_search_recovers_a_different_original(self):
        # Equivalent original/Naver aliases must not evade the reservation.
        shared = article('shared')
        duplicate = {**shared, 'url': 'https://n.news.naver.com/article/001/0012345678',
                     'originalUrl': shared['url']}
        pork = article('pork', title='EU 돼지고기 공급 증가로 국제 가격 하락', body=PORK)
        result, search = self.collect({'domestic': shared, 'domestic_pork': duplicate}, extra=pork)
        sections = result['sections']
        self.assertEqual(sections['domestic']['status'], 'completed')
        self.assertEqual(sections['domestic_pork']['status'], 'completed')
        self.assertEqual(sections['domestic_pork']['article']['url'], pork['url'])
        self.assertLessEqual(sum(call.args[0].key == 'domestic_pork' for call in search.call_args_list), 2)

    def test_no_valid_replacement_reports_duplicate_instead_of_double_completion(self):
        shared = article('shared')
        result, _ = self.collect({'domestic': shared, 'domestic_pork': shared})
        sections = [result['sections'][key] for key in ('domestic', 'domestic_pork')]
        self.assertEqual(sum(item['status'] == 'completed' for item in sections), 1)
        failed = next(item for item in sections if item['status'] != 'completed')
        self.assertIn('동일 기사', failed['summaryError'])
        self.assertFalse(failed.get('summary'))

    def test_exhausted_native_recovery_reserves_new_original_before_next_species(self):
        # Actual failure sequence: pork spends two calls on its primary, then
        # recovers via a ready multi-species Wikitree original. Beef finishes
        # discovery afterwards and must choose its different verified source.
        shared = article('shared')
        pork_main = article('pork-failed', title='미국 돼지고기 수급과 가격 동향 분석',
                            body='미국 돼지고기 공급 감소와 수요 증가로 가격이 상승했다. ' * 5)
        beef_alternate = article('beef-distinct', title='중국 브라질산 쇠고기에 추가 관세', body=BEEF)
        failed, release_links, recovering_pork = Event(), Event(), Event()
        original_alternatives = d._verified_summary_alternatives
        original_native = s._native_report_sentence

        def find(spec, *_args):
            if spec.key == 'domestic_pork':
                return pork_main
            if spec.key == 'domestic':
                self.assertTrue(recovering_pork.wait(4))
                return {**shared, 'alternatives': [beef_alternate]}
            return None

        def enrich(current, *_args, **_kwargs):
            if current['url'] == pork_main['url']:
                self.assertTrue(release_links.wait(4))
                current['_candidateLinkOriginals'] = [shared]
                current['_candidateLinksSearched'] = True
            return []

        def alternatives(*args, **kwargs):
            snapshot = original_alternatives(*args, **kwargs)
            if failed.is_set():
                release_links.set()
            return snapshot

        def native(kind, body):
            if body == pork_main['body']:
                return None  # exercise bounded inference, not extractive completion
            if kind == 'domestic_pork' and body == CPTPP and failed.is_set():
                recovering_pork.set()
            return original_native(kind, body)

        def fail_two_calls(*_args):
            s._ollama_generate('first bounded draft')
            s._ollama_generate('second bounded draft')
            failed.set()
            raise s.ArticleSummaryValidationError('요약 검증 미완료: 최소 40자 미달.')

        with patch.object(d, '_usmef_pair', return_value={}), \
             patch.object(d, '_find_section', side_effect=find), \
             patch.object(d, '_search_article', return_value=None), \
             patch.object(d, '_candidate_links', side_effect=enrich), \
             patch.object(d, '_verified_summary_alternatives', side_effect=alternatives), \
             patch.object(s, '_native_report_sentence', side_effect=native), \
             patch.object(s, '_ensure_ollama_ready', return_value={'available': True}), \
             patch.object(s, '_request_json', return_value={'response': 'too short'}) as model, \
             patch.object(s, '_summarize_report_sentence', side_effect=fail_two_calls):
            result = d.collect_weekly_livestock_report_draft(DAY)
        beef, pork = (result['sections'][key] for key in ('domestic', 'domestic_pork'))
        self.assertEqual(pork['status'], 'completed')
        self.assertEqual(pork['article']['url'], shared['url'])
        self.assertEqual(pork['diagnostics']['modelCalls'], 2)
        self.assertEqual(beef['status'], 'completed')
        self.assertEqual(beef['article']['url'], beef_alternate['url'])
        self.assertEqual(model.call_count, 2)

    def test_stale_search_snippet_and_wrong_species_are_not_replacements(self):
        main = article('main')
        for changes in ({'publishedDate': date(2026, 10, 3)}, {'searchResult': True},
                        {'sourceLanguage': 'en'}, {'url': 'javascript:alert(1)'},
                        {'body': '미국 계란 가격 상승과 공급량 감소를 확인했다. ' * 5}):
            with self.subTest(changes=changes):
                replacement = article('bad', title='EU 돼지고기 공급 증가로 국제 가격 하락', body=PORK)
                replacement.update(changes)
                result, _ = self.collect({'domestic': main, 'domestic_pork': main}, extra=replacement)
                self.assertEqual(result['readyCount'], 1)


if __name__ == '__main__':
    unittest.main()
