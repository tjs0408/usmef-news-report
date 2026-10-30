"""Species focus, same-story alternatives and bounded focused search."""
from datetime import date
import unittest
from unittest.mock import patch

from src import livestock_article_draft as d


START, END = date(2026, 10, 11), date(2026, 10, 17)
SPEC = d.SPECS_BY_KEY['domestic_pork']
LEAD = ('독일 돼지고기 공급은 도축 물량 증가로 전월보다 5% 늘었다. '
        '독일 돼지고기 도매가격은 전주보다 4% 하락했다. '
        '현지 양돈농가는 출하 시기를 조절하고 있으며 수출 시장의 수요 회복을 기다리고 있다. ')


def article(name, **changes):
    return {'title': '독일 돼지고기 공급 증가로 도매가격 하락 전망',
            'url': f'https://example.org/{name}', 'publisher': '보도매체',
            'body': LEAD * 2, 'publishedDate': START, 'sourceLanguage': 'ko', **changes}


class PorkCandidateReprintTests(unittest.TestCase):
    def test_reprint_of_primary_is_not_an_optional_alternative(self):
        main = article('main', publisher='연합뉴스')
        copy = article('copy', publisher='MBC 뉴스', body=LEAD + '별도의 짧은 방송 안내.')
        different = article('different', title='브라질 돼지고기 수출량 증가',
                            body='브라질 돼지고기 수출량은 아시아 수요 증가로 전년보다 8% 늘었다. ' * 3)
        main['alternatives'] = [copy, different]
        links = d._candidate_links(main, SPEC, START, END, search_missing=False)
        self.assertEqual([link['url'] for link in links], [different['url']])

    def test_reprints_cannot_take_both_optional_link_slots(self):
        main = article('main', title='브라질 돼지고기 수출량 증가',
                       body='브라질 돼지고기 수출량은 전년보다 8% 늘었다. ' * 4)
        one = article('one', title='독일 돼지고기 공급 증가로 도매가격 하락 전망 | 연합뉴스', publisher='연합뉴스')
        copy = article('copy', publisher='MBC 뉴스', body=LEAD + '추가 방송 안내.')
        distinct = article('distinct', title='미국 돼지고기 생산량 확대',
                           body='미국 돼지고기 생산량은 출하 체중 증가로 전년보다 3% 늘었다. ' * 4)
        main['alternatives'] = [one, copy, distinct]
        links = d._candidate_links(main, SPEC, START, END, search_missing=False)
        self.assertEqual([link['url'] for link in links], [one['url'], distinct['url']])

    def test_independent_coverage_is_not_collapsed_just_for_same_species(self):
        one = article('one')
        independent = article('other', title='독일 양돈업계, 돼지고기 수출 회복 대응',
            body='독일 양돈업계는 아시아로의 돼지고기 수출을 확대하기 위한 검역 협의를 진행했다. ' * 4)
        self.assertFalse(d._same_candidate_story(one, independent))

    def test_independent_updated_figures_are_not_a_shortened_reprint(self):
        first = article('first', publisher='연합뉴스', body=LEAD + '현지 유통업계는 주간 시장 변화를 예의 주시하고 있다.')
        updated = article('updated', publisher='MBC 뉴스', body=LEAD.replace('5%', '7%').replace('4%', '2%'))
        self.assertFalse(d._same_candidate_story(first, updated))

    def test_paraphrased_same_headline_and_measurements_are_the_same_event(self):
        first = article('first', publisher='연합뉴스', body=LEAD + '현지 유통업계는 시장 변화를 주시하고 있다.')
        second = article('second', publisher='MBC 뉴스', body=(
            '독일의 도축 물량이 증가하면서 돼지고기 공급도 전월 대비 5% 늘어난 것으로 나타났습니다. '
            '돼지고기 도매가격 역시 지난주에 비해 4% 낮아졌다고 현지 유통업계는 전했습니다. '
            '양돈농가가 출하를 조절하며 해외의 수요 회복 여부를 지켜보고 있습니다.'))
        self.assertTrue(d._same_candidate_story(first, second))

    def test_same_generic_headline_and_numbers_do_not_equate_countries_or_metrics(self):
        title = '해외 돼지고기 시장 가격 및 수급 동향, 현지 업계 전망'
        first = article('first', title=title, publisher='연합뉴스', body=(
            '독일 돼지고기 도매가격은 전주보다 5% 하락했고 생산량은 전년보다 4% 증가했다. '
            '현지 양돈업계는 도축 물량과 유통 가격의 변화를 지켜보며 향후 출하 계획을 조정하고 있다.'))
        second = article('second', title=title, publisher='뉴스1', body=(
            '미국 돼지고기 수출액은 전년보다 5% 증가했고 냉동 재고는 전월보다 4% 감소했다. '
            '수출업체들은 해외 수요를 분석하고 냉동창고의 재고 조절을 검토하고 있다고 밝혔다.'))
        self.assertFalse(d._same_candidate_story(first, second))

    def test_same_outlet_long_headline_does_not_hide_updated_figures(self):
        title = '독일 돼지고기 공급 증가로 도매가격 하락 전망, 현지 양돈업계 출하 조절'
        first = article('first', title=title)
        second = article('second', title=title, body=LEAD.replace('5%', '7%').replace('4%', '2%'))
        self.assertFalse(d._same_candidate_story(first, second))

    def test_same_outlet_generic_series_does_not_merge_different_metrics(self):
        title = '독일 돼지고기 시장 가격 및 수급 동향, 현지 업계 전망'
        first = article('first', title=title, body=(
            '독일 돼지고기 도매가격은 전주보다 5% 하락했고 생산량은 전년보다 4% 증가했다. '
            '현지 양돈업계는 도축 물량과 유통 가격의 변화를 지켜보며 향후 출하 계획을 조정하고 있다.'))
        second = article('second', title=title, body=(
            '독일 돼지고기 수출액은 전년보다 5% 증가했고 냉동 재고는 전월보다 4% 감소했다. '
            '수출업체들은 해외 수요를 분석하고 냉동창고의 재고 조절을 검토하고 있다고 밝혔다.'))
        self.assertFalse(d._same_candidate_story(first, second))

    def test_a_different_article_title_does_not_cure_comparison_only_body(self):
        for title in ('돼지고기를 제친 닭고기 소비', '돼지고기도 부담…일본 소비자는 닭고기 선택'):
            with self.subTest(title=title):
                candidate = article('comparison', title=title,
                    body='일본 닭고기 소비가 돼지고기를 추월했다. 닭고기는 돼지고기보다 저렴해 닭고기 수요가 늘었다. ' * 4)
                self.assertLess(d._relevance(candidate, SPEC), 0)

    def test_coequal_multi_species_tariff_consequence_remains_valid(self):
        candidate = article('trade', title='CPTPP, 호주 쇠고기·캐나다 돼지고기 관세 철폐 우려',
            body='CPTPP 가입 시 호주 쇠고기·캐나다 돼지고기 등의 관세 철폐로 수입 증가와 국내 생산 감소가 예상된다.')
        self.assertGreaterEqual(d._relevance(candidate, SPEC), 0)

    def test_mixed_fallback_does_not_end_pork_specific_discovery_early(self):
        fallback = article('cpi', title='중국 소비자물가 발표',
            body='중국 9월 소비자물가지수(CPI)는 전년 동월 대비 0.9% 상승했다. 돼지고기(-10.0%) 가격은 하락했다.')
        dedicated = article('dedicated')
        queries = []
        def search(query, *_):
            queries.append(query)
            return [dedicated] if query == '미국 돈육 가격' else [fallback]
        def choose(items, *_args, **_kwargs):
            return dedicated if any(item['url'] == dedicated['url'] for item in items) else fallback
        with patch.object(d.source, '_search_naver_news', side_effect=search), \
             patch.object(d, '_choose_original', side_effect=choose):
            found = d._search_article(SPEC, START, END)
        self.assertEqual(found['url'], dedicated['url'])
        for query in ('미국 돈육 가격', '돼지고기 공급 과잉', '중국 돼지고기 가격'):
            self.assertEqual(queries.count(query), 1)


if __name__ == '__main__':
    unittest.main()
