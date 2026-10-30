"""Original paragraphs, commodity ownership and overseas selection regressions.

Synthetic source excerpts reproduce failure shapes, not weekly answers. No
network, inference, search snippets, copied dates or model responses are used.
"""
from datetime import date
import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup

from src import livestock_article_draft as d


CHICKEN = d.SPECS_BY_KEY['domestic_chicken']
EGG = d.SPECS_BY_KEY['domestic_egg']
PORK = d.SPECS_BY_KEY['domestic_pork']


def article(title, body):
    return dict(title=title, body=body, url='https://example.org/report',
                publisher='검증 매체', publishedDate=date(2026, 9, 2),
                sourceLanguage='ko', searchResult=False, headlineOnly=False)


class CommodityMarketContextTests(unittest.TestCase):
    def test_ramen_export_figures_cannot_become_egg_market_evidence(self):
        title = '달걀 넣는 조리법 인기…K라면 수출 증가'
        blocks = ['남은 국물에 달걀을 넣는 응용 조리법 확산',
                  '상반기 라면 수출은 9억 달러로 전년보다 25% 증가',
                  '미국 소비자들은 컵라면에 달걀 두 개를 넣는다.',
                  '중국으로의 라면 수출도 30% 증가했다.']
        for body in ('\n'.join(blocks), ' '.join(blocks)):
            with self.subTest(paragraphs='\n' in body):
                item = article(title, body)
                self.assertEqual([], d._independent_market_passages(item, EGG))
                self.assertFalse(d._domestic_overseas_focus(item, EGG))
                self.assertFalse(d._related_domestic_market(item, EGG))
                self.assertIsNone(d._selection_profile(item, EGG))

    def test_chicken_standardization_title_without_market_fact_is_not_direct_news(self):
        item = article('한국서 먹던 맛 해외서도 같게…K-치킨 표준화 경쟁',
            '미국 소비자들은 치킨 맛과 품질의 차이를 지적했다. '
            '기업은 해외 매장 확대보다 조리 매뉴얼 표준화에 집중한다. '
            '닭고기 입고·보관·해동·손질·조리·판매의 기준을 정했다. '
            '현지 식자재 공급망과 배송 차량의 위생 관리를 강화했다.')
        self.assertEqual([], d._independent_market_passages(item, CHICKEN))
        self.assertFalse(d._domestic_overseas_focus(item, CHICKEN))
        self.assertIsNone(d._selection_profile(item, CHICKEN))

    def test_company_history_first_export_is_not_a_current_poultry_market(self):
        item = article('재계 포커스 회장의 식품·해운 경영 확장',
            '2011년 미국의 육계업체를 인수했고, 2014년에는 처음으로 닭고기를 미국에 수출했다.\n'
            '이후 중국과 캐나다로 수출시장을 넓혔고 2024년에는 유럽 시장에도 처음 진출했다.\n'
            '그룹은 국내 식품 사업과 해운 계열사를 연결하며 기업 규모를 키웠다.')
        self.assertEqual([], d._independent_market_passages(item, CHICKEN))
        self.assertIsNone(d._selection_profile(item, CHICKEN))
        item['body'] += '\n프랑스 닭고기 생산량은 사육 감소로 전년보다 7% 줄었다.'
        self.assertEqual(1, len(d._domestic_overseas_passages(item, CHICKEN)))
        self.assertIsNotNone(d._selection_profile(item, CHICKEN))

    def test_real_independent_poultry_market_section_is_kept_in_a_broader_story(self):
        item = article('세계 프랜차이즈 치킨 시장 변화',
            '해외 매장은 조리법과 맛 표준화를 추진했다. '
            '프랑스 닭고기 생산량은 사육 감소로 전년보다 7% 줄었다. '
            '프랑스 닭고기 수입량은 현지 공급 부족으로 8% 늘었다.')
        self.assertEqual(2, len(d._domestic_overseas_passages(item, CHICKEN)))
        self.assertIsNotNone(d._selection_profile(item, CHICKEN))

    def test_country_is_not_a_substring_of_a_korean_predicate(self):
        for text in ('것이란 예상이다', '확인도 필요하다', '중국어 중앙 영어 日本語'):
            with self.subTest(text=text):
                # Chinese language/demonym counts for China by design, but
                # single-character abbreviations must not match 日本語/中央.
                terms = ('이란', '인도', '日', '中', '英')
                self.assertEqual(0, d._has_terms(text, terms))
        for text, term in (('이란에서 닭고기 공급 감소', '이란'),
                           ('인도산 닭고기', '인도'), ('미국산 돼지고기', '미국'),
                           ('일본의 계란 시장', '일본'), ('中 소비자물가', '中')):
            with self.subTest(text=text):
                self.assertEqual(1, d._has_terms(text, (term,)))
        local = article('축산물 시장 전망',
                        '돼지가격은 명절 이후 약세로 접어들 것이란 예상이다.')
        self.assertEqual([], d._domestic_overseas_passages(local, PORK))
        self.assertIsNone(d._selection_profile(local, PORK))

    def test_an_unrelated_foreign_headline_cannot_relabel_korean_prices(self):
        item = article('미국 식품 물가 발표',
            '미국 쇠고기 가격은 전년보다 3% 올랐다. '
            '한국 돼지고기 가격은 국내 수요 증가로 전년보다 5% 상승했다.')
        self.assertEqual([], d._domestic_overseas_passages(item, PORK))
        self.assertIsNone(d._selection_profile(item, PORK))

    def test_imported_beef_statistics_cannot_supply_pork_country_context(self):
        item = article('축산물 가격 변화',
            '미국산 쇠고기 수입량은 7% 증가했다. '
            '돼지고기 가격은 국내 공급 감소로 3% 올랐다.')
        self.assertEqual([], d._domestic_overseas_passages(item, PORK))
        self.assertIsNone(d._selection_profile(item, PORK))

    def test_foreign_cpi_and_explicit_shared_trade_consequences_survive(self):
        cpi = article('중국 소비자물가 발표',
            '중국 9월 CPI는 전년 동월보다 0.9% 상승했다. '
            '돼지고기 공급이 충분하고 소비가 부진해 가격은 10% 하락했다.')
        self.assertEqual(1, d._selection_profile(cpi, PORK)[0])
        shared = article('CPTPP 교역 변화',
            '캐나다산 돼지고기·닭고기 등의 수입 증가가 국내 생산 감소로 이어질 수 있다.')
        self.assertIsNotNone(d._selection_profile(shared, PORK))
        self.assertIsNotNone(d._selection_profile(shared, CHICKEN))

    def test_hanwoo_headline_chicken_trade_background_is_related_not_direct(self):
        item = article('한우 홍콩 수출길 확대, 검역 규제 완화',
            '홍콩은 한우 수입 규제 단위를 도에서 시·군으로 축소했다.\n'
            '올해 4월에는 베트남과 열처리 가금육 수출에 합의했고, '
            '7월에는 홍콩으로의 닭고기 수출 재개 협상도 마쳤다.')
        self.assertEqual(2, d._selection_profile(item, CHICKEN)[0])
        self.assertEqual(0, d._selection_profile(item, d.SPECS_BY_KEY['domestic'])[0])

    def test_mixed_local_report_keeps_the_foreign_trade_passage_not_its_price_lead(self):
        foreign = ('일본의 스페인산 돈육 수입 중단과 중국 수요 감소로 '
                   '브라질산 돼지고기의 한국 수입량이 증가했다.')
        body = ('한국 돼지고기 도매가격은 명절 수요로 상승할 전망이다.\n'
                '국내 농가는 출하 시기를 조정하고 있다.\n' + foreign)
        item = article('명절 축산물 가격 전망', body)
        self.assertEqual([foreign], d._domestic_overseas_passages(item, PORK))
        self.assertIsNotNone(d._selection_profile(item, PORK))
        self.assertEqual(foreign, d._editorial_excerpt(body, item['title'], PORK))

    def test_original_reader_keeps_block_boundaries_and_inline_market_phrases(self):
        blocks = ['남은 국물에 달걀을 넣는 조리법이 해외에서 인기를 얻고 있으며 응용 방법도 확산하고 있다',
                  '상반기 라면 수출은 해외 판매 지역이 늘면서 전년보다 25% 증가했다.',
                  '브라질 계란 가격은 공급 감소로 8% 상승했다.']
        markup = ('<html lang="ko"><meta property="article:published_time" content="2026-09-02">'
                  '<h1>해외 식품 시장 변화</h1><article>'
                  f'<p>{blocks[0]}</p><p>{blocks[1]}</p>'
                  '<p>브라질 계란 <b>가격</b>은 공급 감소로 <span>8%</span> 상승했다.</p>'
                  '</article></html>')
        with patch.object(d.source, '_download_soup', return_value=BeautifulSoup(markup, 'html.parser')), \
             patch.object(d.source, '_ollama_generate') as model:
            item = d._read_original_article({'url': 'https://example.org/report'}, EGG)
        model.assert_not_called()
        self.assertIsNotNone(item)
        self.assertEqual(blocks, item['body'].splitlines())
        self.assertEqual([blocks[2]], d._domestic_overseas_passages(item, EGG))
        self.assertNotIn('라면', item['briefBody'])

    def test_primary_body_does_not_borrow_a_newer_recommended_article(self):
        original = ('O preço médio da carne de frango apresentou recuperação em agosto. '
                    'A demanda interna e as exportações sustentaram as cotações. '
                    'Em São Paulo, o preço no atacado foi de R$ 7,52 por quilo.')
        recommended = ('A recuperação dos preços em setembro foi de 11%, '
                       'e o spread do frango passou de 32% para 37%.')
        markup = ('<html lang="pt"><meta property="article:published_time" content="2026-09-04">'
                  '<h1>Preço do frango em agosto</h1><article id="mvp-article-wrap">'
                  f'<div id="mvp-content-main"><p>{original}</p></div>'
                  f'<div><h2>Continue Lendo</h2><p>{recommended}</p></div></article></html>')
        with patch.object(d.source, '_download_soup', return_value=BeautifulSoup(markup, 'html.parser')):
            item = d._read_original_article({'url': 'https://example.org/frango'},
                                          d.SPECS_BY_KEY['brazil_chicken'])
        self.assertEqual(original, item['body'])
        self.assertNotIn('setembro', item['body'])
        self.assertNotIn('11%', item['body'])

    def test_fallback_body_stops_at_visible_portuguese_recommendation_marker(self):
        original = ('O preço médio da carne de frango apresentou recuperação em agosto. '
                    'A demanda interna e as exportações sustentaram as cotações. '
                    'O mercado atacadista apresentou oferta mais ajustada ao consumo.')
        markup = ('<html lang="pt"><meta property="article:published_time" content="2026-09-04">'
                  '<h1>Preço do frango em agosto</h1><article>'
                  f'<p>{original}</p><h2>Continue Lendo</h2>'
                  '<p>Frango em setembro subiu 11% e margem atingiu 37%.</p></article></html>')
        with patch.object(d.source, '_download_soup', return_value=BeautifulSoup(markup, 'html.parser')):
            item = d._read_original_article({'url': 'https://example.org/frango'},
                                          d.SPECS_BY_KEY['brazil_chicken'])
        self.assertEqual(original, item['body'])


if __name__ == '__main__':
    unittest.main()
