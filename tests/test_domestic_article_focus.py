from unittest import TestCase
from src import livestock_article_draft as d


class DomesticArticleFocusTests(TestCase):
    def focus(self, title, body, key='domestic_pork'):
        return d._domestic_overseas_focus({'title': title, 'body': body}, d.SPECS_BY_KEY[key])

    def test_general_korean_inflation_is_not_overseas_pork(self):
        self.assertFalse(self.focus('물가 2.9%로 내려왔지만… 정부 석유 최고가격제 없었다면 3.5%',
            '국산쇠고기는 6.6%, 수입쇠고기는 7.2%, 돼지고기는 1.9% 상승했습니다.'))

    def test_other_species_imports_do_not_qualify_pork(self):
        self.assertFalse(self.focus('축산물 가격 상승',
            '수입쇠고기는 7.2%, 돼지고기는 1.9% 상승했습니다.'))

    def test_unrelated_neighbouring_country_does_not_qualify(self):
        self.assertFalse(self.focus('축산물 가격 상승',
            '미국의 석유 수출 가격이 상승했습니다. 돼지고기는 국내 수요로 1.9% 상승했습니다.'))

    def test_us_inflation_can_explain_pork_market_without_a_pork_headline(self):
        self.assertTrue(self.focus('미국 소비자물가 발표',
            '미국 돼지고기 소매가격은 공급 증가로 전년보다 2% 하락했습니다.'))
        self.assertTrue(self.focus('미국 돼지고기 소매가격 하락',
            '미국 돼지고기 소매가격은 공급 증가로 전년보다 2% 하락했습니다.'))

    def test_same_species_trade_and_cptpp_remain_valid(self):
        self.assertTrue(self.focus('돈육 교역 변화', '돼지고기 수입 증가로 공급과 가격에 변화가 예상됩니다.'))
        self.assertTrue(self.focus('CPTPP 가입 검토 재개', '돼지고기 수입 증가로 국내 생산 감소가 예상됩니다.'))

    def test_relevant_country_in_previous_species_sentence(self):
        self.assertTrue(self.focus('돈육 수급 변화',
            '독일 돼지고기 시장에서 변화가 나타났습니다. 돼지고기 출하량 감소로 가격 상승이 이어졌습니다.'))
