"""Verified-source fallbacks keep species, scope, temporal and modal bounds."""
import unittest

from src.foreign_week_recovery_facts import native_recovery_fact
from src import overseas_article_digest as digest
from src.article_hwpx_layout import summary_reference_layout


PORK = ('지난주 돼지고기 컷아웃 가격은 전주 대비 0.4% (-0.01달러) 소폭 하락한 0.87달러로 '
        '2024년 2월 이래 최저가를 기록했다. 이는 전년 대비 22%, 2024년 대비 8% 하락한 수준이다. '
        '돼지고기 컷아웃 가격은 7월 넷째 주 1.04달러로 연중 최고가를 기록한 이후 하락세를 이어가며, '
        '지난 5월 중순 이래 매주 전년 동기 수준을 밑돌고 있다. 대분할 belly 와 ham 부위에 더해 '
        '최근 몇 주간은 picnic과 loin 부위의 가격 약세 역시 전체 컷아웃 가격을 끌어내리는 요인으로 작용하고 있다.')
GUIDE = ('IN AN effort to optimise feedlot performance, a new best practice guide has been developed '
         'for producers, outlining how to best prepare cattle for a feedlot. '
         'The guide was developed by Meat & Livestock Australia and authored by well-known Queensland '
         'feedlot veterinarian, Dr Kev Sullivan. The guide outlines the challenges feedlot cattle face '
         'and the strategies that help reduce health and wellbeing risks in a feedlot to improve performance.')
AU_QUOTA = ('China has put a 205,000t quota on Australian beef, with a 55pc tariff when it is triggered '
            '– which happened in June this year. Since then export volumes have declined drmatically. '
            'And Korea has applied a24pc Safeguard tariff on Australian beef.')
EGG = ('The Agricultural Marketing Service, in its Daily National Shell Egg Index Report dated October 1, 2026, '
       'reported mixed national free-on-board weighted average prices for shell eggs . According to the USDA AMS '
       'MyMarketNews report, only caged Extra Large and Large grades were well tested, while the overall market '
       'undertone was mostly steady. Demand from retail channels was described as seasonally moderate to at times '
       'fairly good. Domestic loose egg demand was light to moderate, and export interest was moderate to good. '
       'Offerings were moderate, supplies were generally moderate, and market activity was moderate to slow.')
BRAZIL = ('O excesso de oferta levou as cotações do suíno vivo e da carcaça a recuarem de forma contínua e produziu, '
          'em setembro, uma inversão pouco comum no mercado: a carcaça de frango passou a ser negociada acima da '
          'carcaça suína no atacado de São Paulo. Segundo dados do Centro de Estudos Avançados em Economia Aplicada '
          '(Cepea), o preço médio da carcaça de frango resfriado chegou a R$ 7,81/kg em setembro, considerando os '
          'dados até 18 de setembro, enquanto a carcaça suína especial ficou em R$ 7,42/kg.')
BRAZIL_MONTHLY = ('A avicultura de corte apresentou um mês de setembro de preços mais altos no atacado e mercados '
                  'independentes do vivo. No atacado, os principais cortes também acumularam valorização, refletindo '
                  'uma melhora no fluxo das vendas. “A entrada dos salários favoreceu o consumo e a reposição entre '
                  'atacado e varejo durante a primeira metade do mês”, afirma. “As exportações permaneceram como '
                  'importante fator de sustentação, mantendo parte relevante da produção direcionada ao exterior”, '
                  'destaca. A recuperação, entretanto, ocorreu de maneira desigual, com preços ainda fragilizados '
                  'no Nordeste e em parte da Região Sul. O levantamento mensal realizado por Safras & Mercado nas '
                  'principais praças de comercialização do Brasil apontou que o quilo vivo em São Paulo subiu '
                  'de R$ 5,20 para R$ 5,70.')


class ForeignWeekRecoveryTests(unittest.TestCase):
    def test_australia_quota_keeps_target_rate_and_observed_exports(self):
        summary, evidence = native_recovery_fact('australia', AU_QUOTA)
        self.assertIn('55%', summary)
        self.assertIn('발동 이후', summary)
        self.assertNotIn('24%', summary)
        self.assertNotIn('전망', summary)
        self.assertIn(evidence, AU_QUOTA)
        self.assertTrue(digest._valid_brief(summary, 'australia', AU_QUOTA))
        self.assertTrue(summary_reference_layout(summary, 'australia')['withinLineLimit'])
        self.assertIn('50%', native_recovery_fact('australia', AU_QUOTA.replace('55pc', '50pc'))[0])

    def test_australia_quota_frame_rejects_wrong_market_direction_or_condition(self):
        for changed in (AU_QUOTA.replace('China has put', 'Japan has put'),
                        AU_QUOTA.replace('Australian beef,', 'Brazilian beef,'),
                        AU_QUOTA.replace('which happened', 'which may happen'),
                        AU_QUOTA.replace('have declined', 'have increased'),
                        AU_QUOTA.replace('55pc', '0pc')):
            self.assertIsNone(native_recovery_fact('australia', changed), changed)

    def test_translated_month_is_not_a_license_for_an_invented_bird_count(self):
        self.assertIn(9, digest._brief_numeric_values(BRAZIL))
        self.assertNotIn(9, digest._brief_numeric_values('Uma reunião em setembro.'))
        self.assertFalse(digest._supported_measurements('브라질 닭 9마리 공급', BRAZIL))

    def test_actual_source_passages_are_complete_grounded_and_one_line(self):
        for kind, body in (('us_pork', PORK), ('australia', GUIDE), ('us_egg', EGG),
                           ('brazil_chicken', BRAZIL), ('brazil_chicken', BRAZIL_MONTHLY)):
            with self.subTest(kind=kind):
                result = native_recovery_fact(kind, body)
                self.assertIsNotNone(result)
                summary, evidence = result
                self.assertGreaterEqual(len(summary), 40)
                self.assertTrue(digest._valid_brief(summary, kind, body), digest.brief_validation_reasons(summary, kind, body))
                self.assertTrue(summary_reference_layout(summary, kind)['withinLineLimit'], summary)
                self.assertFalse(summary.endswith(('다', '.')))
                self.assertTrue(evidence)

    def test_pork_cause_and_rate_come_from_the_same_cutout_passage(self):
        summary, evidence = native_recovery_fact('us_pork', PORK)
        self.assertIn('전주비 0.4% 하락', summary)
        self.assertIn('일부 부위 약세', summary)
        self.assertNotIn('0.87달러', summary)  # No unstated dollar denominator.
        changed, _ = native_recovery_fact('us_pork', PORK.replace('0.4%', '1.7%'))
        self.assertIn('1.7%', changed)
        for changed in (PORK.replace('전주 대비', '전년 대비'), PORK.replace('소폭 하락한', '소폭 상승한'),
                        PORK.replace('작용하고 있다.', '작용하지 않고 있다.'),
                        PORK.replace('돼지고기 컷아웃 가격은', '소고기 컷아웃 가격은'),
                        PORK + ' 해당 가격 보도는 오류로 정정됐다.'):
            self.assertIsNone(native_recovery_fact('us_pork', changed))

    def test_industry_guide_fallback_does_not_invent_price_or_observed_performance_gain(self):
        summary, evidence = native_recovery_fact('australia', GUIDE)
        self.assertIn('관리지침 개발 완료', summary)
        for absent in ('가격', '생산량 증가', '건강 개선 실현', '질병 감소'):
            self.assertNotIn(absent, summary)
        for changed in (GUIDE.replace('has been developed', 'will be developed'),
                        GUIDE.replace('Meat & Livestock Australia', 'Beef + Lamb New Zealand'),
                        GUIDE.replace('prepare cattle', 'prepare sheep'),
                        GUIDE.replace('help reduce health', 'do not reduce health')):
            self.assertIsNone(native_recovery_fact('australia', changed))

    def test_national_egg_market_keeps_mostly_qualifier_not_regional_numbers(self):
        summary, evidence = native_recovery_fact('us_egg', EGG)
        self.assertIn('대체로 보합', summary)
        self.assertIn('대체로 보통', summary)
        self.assertIn('보통~한산', summary)
        self.assertNotIn('소매가격', summary)
        for changed in (EGG.replace('mostly steady', 'mostly higher'),
                        EGG.replace('generally moderate', 'generally limited'),
                        EGG.replace('moderate to slow', 'moderate to active'),
                        EGG.replace('reported mixed national', 'reported mixed California'),
                        EGG + ' This report was corrected as incorrect.'):
            self.assertIsNone(native_recovery_fact('us_egg', changed))

    def test_chicken_quote_cannot_inherit_pork_loss_or_oversupply(self):
        summary, evidence = native_recovery_fact('brazil_chicken', BRAZIL)
        for term in ('냉장 닭 도체가격', '9월 18일까지', '7.81헤알'):
            self.assertIn(term, summary)
        for absent in ('돼지', '공급 과잉', '손실', '7.42', '상승', '하락'):
            self.assertNotIn(absent, summary)
        changed, _ = native_recovery_fact('brazil_chicken', BRAZIL.replace('7,81', '8,25').replace('18 de setembro', '20 de setembro'))
        self.assertIn('8.25헤알', changed)
        self.assertIn('20일까지', changed)
        for changed in (BRAZIL.replace('frango resfriado', 'suíno resfriado'),
                        BRAZIL.replace('chegou a R$', 'não chegou a R$'),
                        BRAZIL.replace('no atacado de São Paulo', 'no atacado de Santiago'),
                        BRAZIL.replace('18 de setembro', '18 de outubro'),
                        BRAZIL.replace('18 de setembro', '31 de setembro'),
                        BRAZIL.replace('18 de setembro', '32 de setembro')):
            self.assertIsNone(native_recovery_fact('brazil_chicken', changed))

    def test_unknown_kind_or_incomplete_text_abstains(self):
        for kind, body in (('us', PORK), ('domestic_chicken', BRAZIL), ('us_egg', ''), ('australia', None)):
            self.assertIsNone(native_recovery_fact(kind, body))

    def test_monthly_brazil_recovery_keeps_price_support_and_regional_contrast(self):
        summary, evidence = native_recovery_fact('brazil_chicken', BRAZIL_MONTHLY)
        self.assertIn('9월', summary)
        self.assertIn('내수·수출 지지', summary)
        self.assertIn('지역별 회복 차이', summary)
        self.assertNotIn('전국 가격 상승', summary)
        self.assertNotIn('전망', summary)
        for changed in (BRAZIL_MONTHLY.replace('apresentou um mês', 'deverá apresentar um mês'),
                        BRAZIL_MONTHLY.replace('preços mais altos', 'preços mais baixos'),
                        BRAZIL_MONTHLY.replace('permaneceram como importante fator', 'não permaneceram como importante fator'),
                        BRAZIL_MONTHLY.replace('de maneira desigual', 'de maneira uniforme'),
                        BRAZIL_MONTHLY.replace('do Brasil', 'da Argentina')):
            self.assertIsNone(native_recovery_fact('brazil_chicken', changed))


if __name__ == '__main__':
    unittest.main()
