import unittest
from unittest.mock import patch
from bs4 import BeautifulSoup

from src import livestock_article_draft as d
from src import overseas_article_digest as s
from src.article_hwpx_layout import summary_reference_layout


EGG = ('논란은 브라질산 계란의 수입 단가에서 비롯됐다. '
       '개당 수입 가격은 1300원으로 미국산 464원의 약 2.8배, 태국산 305원의 약 4.3배였다. '
       '브라질산 계란의 수입 가격이 높다는 점에서 정치적 의혹을 제기했다.')
ACCESS = ('한국 대통령과 브라질 대통령은 공동성명에서 브라질산 쇠고기·돼지고기의 '
          '한국 시장 접근 약속을 재확인했다. 양국은 교역을 확대하기로 했다.')
EU = ('The anniversary conference brought together the pork industry and retail representatives. '
      'The European pork market is shifting from a volume-based to a value-based logic. '
      'Supply pressures and weaker demand in international markets are accelerating the need for quality.')
LIVE_EXPORT = ('Australia’s live cattle exports fell by almost 35 percent in September, but Darwin feeder '
               'prices remain firm as the trade prepares for an expected lift in Indonesian buying ahead of Ramadan. '
               'Brazil cattle prices are lower than Australian cattle prices because of lower export costs.')
COMPETITION = ('Uma das maiores compradoras de carnes de frango do Brasil, a China aumentou a produção em 9%. '
               'Para o economista, a China pode se tornar o principal concorrente, mesmo sendo cliente do Brasil.')


class CurrentMarketPassageRepairTests(unittest.TestCase):
    def test_source_fact_briefs_need_no_inference_and_fit_the_report(self):
        for kind, body in (('domestic_egg', EGG), ('domestic_pork', ACCESS), ('domestic', ACCESS), ('eu_pork', EU),
                           ('australia', LIVE_EXPORT), ('brazil_chicken', COMPETITION)):
            with self.subTest(kind=kind), patch.object(s, '_ollama_generate') as model:
                summary = s._summarize_report_sentence.__wrapped__(kind, 'title', body)
                model.assert_not_called()
                self.assertGreaterEqual(len(summary), 40)
                self.assertTrue(s._valid_brief(summary, kind, body))
                self.assertTrue(summary_reference_layout(summary, kind)['withinLineLimit'])

    def test_market_access_promise_is_not_realized_approval_or_another_product(self):
        brief = s._korean_bilateral_market_access_summary(ACCESS, '돼지고기')
        self.assertIn('약속', brief)
        self.assertNotIn('승인', brief)
        self.assertNotIn('수입 증가', brief)
        for changed in (ACCESS.replace('재확인했다', '재확인하지 않았다'),
                        ACCESS.replace('쇠고기·돼지고기', '계란'),
                        ACCESS.replace('공동성명', '공동 보도')):
            self.assertIsNone(s._korean_bilateral_market_access_summary(changed, '돼지고기'))

    def test_per_egg_metric_keeps_immediate_origin_and_ratio(self):
        brief = s._korean_egg_import_price_comparison_summary(EGG)
        self.assertIn('브라질산 계란', brief)
        self.assertIn('1300원', brief)
        self.assertIn('464원', brief)
        self.assertIn('2.8배', brief)
        for body in (EGG.replace('계란', '쇠고기'), EGG.replace('수입 가격은 1300원', '수입 가격은 허위로 1300원')):
            self.assertIsNone(s._korean_egg_import_price_comparison_summary(body))

    def test_eu_shift_requires_direction_and_the_actual_demand_cause(self):
        for changed in (EU.replace('is shifting', 'is not shifting'),
                        EU.replace('weaker demand', 'stronger demand'),
                        EU.replace('European pork', 'American pork')):
            self.assertIsNone(s._eu_pork_value_transition_summary(changed))

    def test_live_export_and_competition_are_not_reversed_or_promoted_to_facts(self):
        for changed in (LIVE_EXPORT.replace('exports fell', 'exports rose'),
                        LIVE_EXPORT.replace('prices remain firm', 'prices weakened'),
                        LIVE_EXPORT.replace('expected lift', 'expected decline')):
            self.assertIsNone(s._australian_live_export_demand_summary(changed))
        for changed in (COMPETITION.replace('a China aumentou', 'a China reduziu'),
                        COMPETITION.replace('pode se tornar', 'não pode se tornar')):
            self.assertIsNone(s._brazil_chicken_competition_outlook_summary(changed))
        self.assertIn('가능성', s._brazil_chicken_competition_outlook_summary(COMPETITION))

    def test_excerpt_prefers_price_facts_and_market_change_over_commentary(self):
        excerpt = d._editorial_excerpt(EGG, '브라질산 계란 수입가 논란', d.SPECS_BY_KEY['domestic_egg'])
        self.assertIn('개당 수입 가격은 1300원', excerpt)
        self.assertIn('브라질산 계란', excerpt)
        self.assertNotIn('정치적 의혹', excerpt)
        excerpt = d._editorial_excerpt(EU, 'Italian cured meats and distribution', d.SPECS_BY_KEY['eu_pork'])
        self.assertIn('European pork market', excerpt)
        self.assertIn('Supply pressures and weaker demand', excerpt)
        self.assertNotIn('anniversary', excerpt)
        excerpt = d._editorial_excerpt(LIVE_EXPORT, 'Live cattle exports ease, but Darwin prices hold ahead of Ramadan buying',
                                       d.SPECS_BY_KEY['australia'])
        self.assertTrue(excerpt.startswith('Australia’s live cattle exports fell'))

    def test_korean_cooperative_milestone_and_actor_only_brief_are_rejected(self):
        article = {'title': '제주 돼지고기 몽골 수출, 단일 물량 신기록',
                   'body': '양돈농협의 이번 돼지고기 수출은 GS25 몽골과의 협력을 통해 추진됐다. 현지 수요를 공략했다.'}
        self.assertFalse(d._domestic_overseas_focus(article, d.SPECS_BY_KEY['domestic_pork']))
        summary = '14일 양돈농협에 따르면 이번 수출은 GS25 몽골과의 협력을 통해 추진'
        self.assertFalse(s._brief_content_supported(summary, 'domestic_pork', article['body']))
        for title in ('김규리 사칭 계정 등장 [스타이슈]', '[1년 전 오늘] 중국, 한화오션 제재'):
            # A celebrity's old beef controversy or a retrospective sidebar
            # must not qualify merely because the scraped text mentions meat.
            incidental = {'title': title, 'body': '미국 쇠고기 수입과 관련한 과거 발언을 언급했다.'}
            self.assertFalse(d._domestic_overseas_focus(incidental, d.SPECS_BY_KEY['domestic']))

    def test_publisher_ai_summary_and_keyword_cloud_are_not_original_evidence(self):
        html = BeautifulSoup('<html lang="pt"><meta property="article:published_time" content="2026-10-12">'
            '<h1>Brasil chicken export report</h1><article><div id="r7-article-content">'
            '<details>LEIA AQUI O RESUMO DA NOTÍCIA. False chicken price 99%. Produzido pela Ri7a</details>'
            f'<p>{COMPETITION}</p><div class="b-article-body-link-list__container">Leia Mais: other report 999%</div>'
            '<div class="keyword_wrap">chicken production prices tags</div></div></article></html>', 'html.parser')
        with patch.object(s, '_download_soup', return_value=html):
            article = d._read_original_article({'url': 'https://example.org/chicken'}, d.SPECS_BY_KEY['brazil_chicken'])
        self.assertEqual(article['body'], COMPETITION)
        self.assertNotIn('99%', article['body'])
        self.assertNotIn('tags', article['body'])


if __name__ == '__main__':
    unittest.main()
