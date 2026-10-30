from datetime import date
import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup
from src import livestock_article_draft as d, overseas_article_digest as s
from src.regional_market_brief_facts import native_regional_market_brief as native, us_pork_primary_market
from src.article_hwpx_layout import summary_reference_layout


US = ('After several weeks of declining wholesale pork values, the cutout closed Friday '
      'at $80.55/cwt, virtually unchanged from $80.50 the previous week. '
      'National negotiated cash hog prices fell to $67.09/cwt, the CME Lean Hog Index declined to $75.09. '
      'Sources: USDA Agricultural Marketing Service, USDA Foreign Agricultural Service, CME Group.')
EU = ('In recent years, due to various factors, we have lost approximately one million pigs produced in Italy, '
      'and our level of self-sufficiency has further declined. '
      'If this trend is not stopped, the Italian production system will become increasingly dependent on foreign markets.')
BR = ('A recuperação dos preços da carne de frango em setembro melhorou as margens da agroindústria brasileira, '
      'em um mês marcado pelo crescimento das exportações e pela oferta interna elevada. '
      'Segundo o relatório Agro Mensal de outubro, da Consultoria Agro do Itaú BBA, '
      'o preço médio mensal da ave avançou 11%, superando a alta de 3,5% no custo de produção da avicultura. '
      'Com isso, o spread do frango abatido passou de 32% para 37%.')


class RegionalMarketBriefFactsTests(unittest.TestCase):
    def test_brazil_regional_recovery_keeps_scope_and_cause_not_recommended_statistics(self):
        body = ('O preço médio da carne de frango apresentou recuperação em agosto na maior parte das praças '
                'acompanhadas pelo Centro de Estudos Avançados em Economia Aplicada (Cepea). '
                'O movimento foi sustentado principalmente pelo aumento da demanda no mercado interno, '
                'especialmente no início do mês, e pelo bom ritmo das exportações. '
                'Os indicadores do Cepea consideram os preços da carne negociada no atacado, com média '
                'das regiões da Grande São Paulo, São José do Rio Preto e Descalvado.')
        summary, evidence = native('brazil_chicken', body)
        self.assertIn('조사 지역 대부분', summary)
        self.assertIn('내수 증가·양호한 수출 흐름', summary)
        self.assertIn('8월 닭고기 가격 회복', summary)
        self.assertNotIn('11%', summary)
        self.assertTrue(s._valid_brief(summary, 'brazil_chicken', body))
        self.assertTrue(summary_reference_layout(summary, 'brazil_chicken')['withinLineLimit'])
        self.assertIn('São Paulo', evidence)
        shifted, _ = native('brazil_chicken', body.replace('agosto', 'julho'))
        self.assertIn('7월', shifted)
        for bad in (body.replace('apresentou recuperação', 'não apresentou recuperação'),
                    body.replace('carne de frango', 'carne suína'),
                    body.replace('pelo bom ritmo das exportações', 'pela queda das exportações'),
                    body.replace('Grande São Paulo', 'Nova York')):
            with self.subTest(body=bad):
                self.assertIsNone(native('brazil_chicken', bad))

    def test_three_original_grammars_complete_without_ai_and_fit_one_line(self):
        for key, body in (('us_pork', US), ('eu_pork', EU), ('brazil_chicken', BR)):
            with self.subTest(key=key), patch.object(s, '_ollama_generate', side_effect=AssertionError('no AI')):
                fact = native(key, body)
                self.assertIsNotNone(fact)
                summary, evidence = fact
                self.assertGreaterEqual(len(summary), 40)
                self.assertTrue(s._valid_brief(summary, key, body), s.brief_validation_reasons(summary, key, body))
                self.assertTrue(summary_reference_layout(summary, key)['withinLineLimit'])
                self.assertEqual(s._summarize_report_sentence.__wrapped__(key, 'market report', body), summary)
                self.assertEqual(s._native_source_excerpt(body, summary), evidence)

    def test_us_price_is_dynamic_without_unstated_comparison_or_100lb_conversion(self):
        fact = native('us_pork', US.replace('80.55', '82.41'))
        self.assertIn('82.41달러', fact[0])
        self.assertNotIn('80.55', fact[0])
        self.assertNotIn('100', fact[0])
        self.assertNotIn('전년', fact[0])
        for body in (US.replace('virtually unchanged', 'not virtually unchanged'),
                     US.replace('prices fell', 'prices did not fall'), US.replace('USDA Agricultural Marketing Service', 'other service')):
            self.assertIsNone(native('us_pork', body))

    def test_other_countries_are_not_us_news_by_an_incidental_us_price(self):
        for title in ('Ontario Hog Prices Fall', 'Canadian pork values', 'Japan Hog Herd Outlook', 'Ukraine Pork Industry'):
            self.assertFalse(us_pork_primary_market(US, title))
        self.assertTrue(us_pork_primary_market(US, 'Pork Cutout Executive Market Brief'))
        self.assertTrue(us_pork_primary_market('U.S. pork production expanded.', 'US pork news'))

    def test_eu_counts_country_scale_and_approximation_remain_source_bound(self):
        summary, _ = native('eu_pork', EU.replace('one million', '1.5 million').replace('Italy', 'Germany'))
        self.assertIn('독일', summary)
        self.assertIn('약 150만마리', summary)
        self.assertNotIn('이탈리아', summary)
        self.assertNotIn('의존', summary)  # conditional consequence is not an observed fact
        for body in (EU.replace('lost approximately', 'not lost approximately'), EU.replace('pigs', 'cattle'),
                     EU.replace('Italy', 'Canada'), EU.replace('has further declined', 'has not declined')):
            self.assertIsNone(native('eu_pork', body))

    def test_brazil_month_prices_and_spread_are_dynamic_not_net_profit(self):
        changed = BR.replace('setembro', 'agosto').replace('11%', '12%').replace('32%', '31%').replace('37%', '39%')
        summary, evidence = native('brazil_chicken', changed)
        self.assertIn('8월', summary)
        self.assertIn('12%', summary)
        self.assertIn('31%→39%', summary)
        self.assertNotIn('순이익', summary)
        self.assertNotIn('전월비', summary)
        self.assertIn('3,5%', evidence)
        self.assertTrue(s._valid_brief(summary, 'brazil_chicken', changed))
        for body in (BR.replace('avançou', 'não avançou'), BR.replace('37%', '29%'),
                     BR.replace('11%', '2%'), BR.replace('brasileira', 'argentina'),
                     BR.replace('frango abatido', 'suíno abatido')):
            self.assertIsNone(native('brazil_chicken', body))

    def test_listing_links_are_discovered_from_actual_publisher_dom(self):
        start, end = date(2026, 10, 18), date(2026, 10, 24)
        cases = (('https://www.portaldoagronegocio.com.br/', '<article><a href="/frango-preco"><h2 class="titleArticle">Preço do frango sobe no Brasil</h2></a></article>'),
                 ('https://opresenterural.com.br/', '<a href="/frango-preco" rel="bookmark"><div>Preço do frango sobe no Brasil</div></a>'))
        for url, html in cases:
            with self.subTest(url=url):
                links = d._listing_candidates(BeautifulSoup(html, 'html.parser'), url, d.SPECS_BY_KEY['brazil_chicken'], start, end)
                self.assertTrue(any(item['url'].endswith('/frango-preco') for item in links))


if __name__ == '__main__':
    unittest.main()
