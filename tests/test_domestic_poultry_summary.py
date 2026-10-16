import unittest
from unittest.mock import patch
from src import livestock_article_draft as d
from src import overseas_article_digest as s


class DomesticPoultrySummaryTests(unittest.TestCase):
    def tearDown(self):
        s._summarize_report_sentence.cache_clear()

    def test_local_egg_farming_is_not_overseas_market(self):
        article = {'title': '지방소멸 위기 지역 토종닭 계란으로 새 소득원',
                   'body': '수입을 통해 가격을 조정하기보다 국내 농가를 지원해 합리적인 가격에 계란이 유통될 수 있도록 해야 한다.'}
        self.assertFalse(d._domestic_overseas_focus(article, d.SPECS_BY_KEY['domestic_egg']))

    def test_import_instead_of_local_support_is_not_a_trade_event(self):
        article = {'title': '계란 농가 지원 기준 개선',
                   'body': '수입을 통해 가격을 조정하기보다 국내 농가를 지원해 합리적인 가격에 계란이 유통될 수 있도록 해야 한다.'}
        self.assertFalse(d._domestic_overseas_focus(article, d.SPECS_BY_KEY['domestic_egg']))

    def test_ingredient_list_does_not_qualify_as_egg_market(self):
        article = {'title': '벨기에 K-푸드 유통 변화',
                   'body': '육류, 계란, 유제품 등 동물성 가공원료가 들어간 제품은 원료 구성에 따라 EU 수입 요건과 서류가 달라진다.'}
        self.assertFalse(d._domestic_overseas_focus(article, d.SPECS_BY_KEY['domestic_egg']))

    def test_real_egg_trade_remains_eligible(self):
        article = {'title': '미국 계란 공급 부족',
                   'body': '미국 계란 가격은 공급 부족으로 상승했고 계란 수입량 확대가 추진되고 있다.'}
        self.assertTrue(d._domestic_overseas_focus(article, d.SPECS_BY_KEY['domestic_egg']))

    def test_stock_trading_article_with_egg_anecdote_is_rejected(self):
        article = {'title': '미 의원보다 많은 트럼프의 주식·채권 거래',
                   'body': '트럼프는 계란 부족 사태 동안 계란 생산업체 주식을 샀다가 2개월 뒤 팔아 이익을 봤다.'}
        self.assertFalse(d._domestic_overseas_focus(article, d.SPECS_BY_KEY['domestic_egg']))

    def test_chicken_summary_keeps_title_country_context_without_new_numbers(self):
        title = '달라지는 벨기에 닭고기 유통'
        body = '특히 닭고기 가공 제품은 검역 협상 이후 닭강정과 닭고기 만두, 소시지 등으로 수출 품목이 넓어졌다.'
        summary = '벨기에 닭고기 가공 제품은 검역 협상 이후 닭강정과 만두 등으로 수출 품목 확대'
        with patch.object(s, '_native_report_sentence', return_value=None), \
             patch.object(s, '_market_fact_excerpt', return_value='닭고기 수출 품목 확대'), \
             patch.object(s, '_compose_report_sentence', return_value=summary) as compose:
            self.assertEqual(s._summarize_report_sentence('domestic_chicken', title, body), summary)
        self.assertIn(title, ' '.join(compose.call_args.kwargs['facts']))
        self.assertTrue(s._valid_brief(summary, 'domestic_chicken', body))
        self.assertFalse(s._valid_brief(summary.replace('확대', '50% 확대'), 'domestic_chicken', body))

    def test_qualitative_source_compaction_needs_no_model(self):
        body = '특히 닭고기 가공 제품은 검역 협상 이후 닭강정과 닭고기 만두, 소시지 등으로 수출 품목이 넓어졌다.'
        with patch.object(s, '_ollama_generate') as model:
            summary = s._summarize_report_sentence('domestic_chicken', '벨기에 가공식품 수출', body)
        model.assert_not_called()
        self.assertTrue(summary.startswith('벨기에 닭고기'))
        self.assertTrue(summary.endswith('확대'))
        self.assertTrue(s._valid_brief(summary, 'domestic_chicken', body))
