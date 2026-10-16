"""Offline recovery from explicit source clauses, with no regional fact mixing."""
import unittest
from unittest.mock import patch

from src import overseas_article_digest as s
from src.article_hwpx_layout import summary_reference_layout


US_NATIONAL = (
    "National FOB shell egg weighted average prices are lower. "
    "The undertone remains mixed, generally steady. "
    "Retail demand is moderate to at times fairly good with food service movement "
    "remaining light to at times moderate. Offerings are moderate on mostly moderate supplies. "
    "Market activity is moderate to slow. "
    "California weighted average delivered prices are not well tested. Supplies are light."
)
DENMARK_REVIEW = (
    "A new strategy for Denmark’s pig sector "
    "The suspension comes as Denmark prepares a broader review of its pork production model. "
    "The government has created the Grisefirepart, a negotiating forum that will begin work "
    "after the New Year and will have six months to reach an agreement on the future direction of the sector."
)
EGG_IMPORT_RESPONSE = (
    "한편, 농림축산식품부는 지난 6일 설명자료를 통해 브라질산 계란 수입은 "
    "고병원성 조류인플루엔자(AI)에 따른 공급 부족과 가격 상승에 대응하기 위한 "
    "한시적 조치라고 해명했다."
)


class ScopedNativeRuleTests(unittest.TestCase):
    def tearDown(self):
        s._summarize_report_sentence.cache_clear()

    def test_actual_source_clauses_recover_without_a_model_and_fit_one_line(self):
        cases = (
            ('us_egg', 'National shell egg report', US_NATIONAL),
            ('eu_pork', 'Denmark suspends the construction and expansion of pig farms', DENMARK_REVIEW),
            ('domestic_egg', '브라질산 계란 수입 설명', EGG_IMPORT_RESPONSE),
        )
        for kind, title, body in cases:
            with self.subTest(kind=kind), patch.object(s, '_ollama_generate') as model:
                summary = s._summarize_report_sentence(kind, title, body)
                model.assert_not_called()
                self.assertTrue(s._valid_brief(summary, kind, body), summary)
                self.assertGreaterEqual(len(summary), 40)
                self.assertFalse(summary.endswith('다'))
                self.assertTrue(summary_reference_layout(summary, kind)['withinLineLimit'], summary)

    def test_national_egg_price_reads_all_directions_with_equivalent_supply_wording(self):
        for source, translated in (('steady to lower', '보합~하락'), ('steady to higher', '보합~상승'),
                                   ('steady', '보합'), ('lower', '하락'), ('higher', '상승')):
            for supplies in ('Supplies are mostly moderate.',
                             'Offerings are moderate on mostly moderate supplies.',
                             'Supplies are generally moderate.'):
                body = f'National FOB shell egg weighted average prices are {source}. {supplies}'
                with self.subTest(source=source, supplies=supplies):
                    summary = s._native_report_sentence('us_egg', body)
                    self.assertIn(f'가격은 {translated}', summary)
                    self.assertIn('공급은 대체로 보통 수준', summary)
                    self.assertTrue(s._valid_brief(summary, 'us_egg', body))
                    self.assertTrue(summary_reference_layout(summary, 'us_egg')['withinLineLimit'])

    def test_national_supply_does_not_come_from_california_or_another_paragraph(self):
        price = 'National FOB shell egg weighted average prices are lower. '
        for unrelated in (
            'California weighted average delivered prices are lower. Supplies are mostly moderate.',
            'California supplies are mostly moderate.',
            'Supplies are mostly moderate in California.',
            '\n\nSupplies are mostly moderate.',
            'A separate regional report follows. Supplies are mostly moderate.',
        ):
            with self.subTest(unrelated=unrelated):
                self.assertIsNone(s._national_shell_egg_market_summary(price + unrelated))
                self.assertIsNone(s._native_report_sentence('us_egg', price + unrelated))
        body = price + 'Supplies are light. California prices are lower. Supplies are mostly moderate.'
        self.assertIsNone(s._native_report_sentence('us_egg', body))
        self.assertIn('대체로 보통 수준', s._native_report_sentence('us_egg', US_NATIONAL))

    def test_national_moderate_supply_is_never_inferred_from_offer_volume(self):
        price = 'National FOB shell egg weighted average prices are lower. '
        for supplies in ('Offerings are moderate on light supplies.', 'Supplies are not mostly moderate.',
                         'Offerings are moderate.', 'Offerings are moderate on mostly moderate.',
                         'Supplies are mostly moderate. Supplies are light.'):
            with self.subTest(supplies=supplies):
                self.assertIsNone(s._national_shell_egg_market_summary(price + supplies))
        self.assertIsNone(s._national_shell_egg_market_summary(
            price.replace('are lower', 'are not lower') + 'Supplies are mostly moderate.'))
        plain = s._native_report_sentence('us_egg', price + 'Supplies are moderate.')
        self.assertIsNotNone(plain)
        self.assertNotIn('대체로', plain)
        self.assertTrue(s._valid_brief(plain, 'us_egg', price + 'Supplies are moderate.'))

    def test_large_size_quote_retains_national_scope(self):
        body = ('National FOB shell egg weighted average prices lower for the larger sizes. '
                'The undertone is mixed, mostly steady. Supplies are mostly moderate.')
        summary = s._native_report_sentence('us_egg', body)
        for term in ('전국 FOB', '큰 규격', '하락', '대체로 보통 수준'):
            self.assertIn(term, summary)
        self.assertTrue(s._valid_brief(summary, 'us_egg', body))
        self.assertTrue(summary_reference_layout(summary, 'us_egg')['withinLineLimit'])
        self.assertIsNone(s._native_report_sentence('us_egg', body.replace('prices lower', 'prices higher')))

    def test_danish_review_never_turns_an_unresolved_suspension_into_a_strategy_ban(self):
        summary = s._native_report_sentence('eu_pork', DENMARK_REVIEW)
        for term in ('덴마크', '돼지고기 생산 모델', '전반의 검토 준비', '미래 방향 논의 예정'):
            self.assertIn(term, summary)
        for term in ('전략 중단', '신축', '확장', '중단'):
            self.assertNotIn(term, summary)
        changed = DENMARK_REVIEW.replace('six months', 'eight months').replace('Grisefirepart', 'SectorForum')
        self.assertEqual(summary, s._native_report_sentence('eu_pork', changed))
        self.assertIsNone(s._denmark_pig_policy_summary(DENMARK_REVIEW.replace('pork production', 'poultry production')))
        self.assertIsNone(s._denmark_pig_policy_summary(DENMARK_REVIEW.replace('has created', 'has not created')))
        self.assertIsNone(s._denmark_pig_policy_summary(DENMARK_REVIEW.replace('prepares a broader review', 'does not prepare a broader review')))

    def test_danish_construction_suspension_requires_an_explicit_body_clause(self):
        clause = 'Denmark suspends the construction and expansion of pig farms. '
        body = clause + DENMARK_REVIEW
        summary = s._native_report_sentence('eu_pork', body)
        self.assertIn('돼지농장의 신축·확장 중단', summary)
        self.assertNotIn('전략 중단', summary)
        self.assertIn('전반의 검토 예정', summary)
        self.assertTrue(s._valid_brief(summary, 'eu_pork', body))
        self.assertTrue(summary_reference_layout(summary, 'eu_pork')['withinLineLimit'])
        denied = clause.replace('suspends', 'does not suspend') + DENMARK_REVIEW
        self.assertNotIn('중단', s._native_report_sentence('eu_pork', denied))
        self.assertIsNone(s._denmark_pig_policy_summary(clause))

    def test_temporary_egg_import_response_captures_country_without_dates_or_numbers(self):
        summary = s._native_report_sentence('domestic_egg', EGG_IMPORT_RESPONSE)
        for term in ('브라질산 계란', 'AI에 따른 공급 부족', '가격 상승 대응', '한시적으로 수입'):
            self.assertIn(term, summary)
        self.assertFalse(s._brief_numeric_values(summary))
        self.assertEqual(summary, s._native_report_sentence('domestic_egg', EGG_IMPORT_RESPONSE.replace('6일', '18일')))
        changed = EGG_IMPORT_RESPONSE.replace('브라질산', '미국산')
        dynamic = s._native_report_sentence('domestic_egg', changed)
        self.assertIn('미국산 계란', dynamic)
        self.assertNotIn('브라질', dynamic)
        self.assertTrue(s._valid_brief(dynamic, 'domestic_egg', changed))

    def test_temporary_import_rule_requires_its_own_purpose_and_temporary_status(self):
        for body in (
            EGG_IMPORT_RESPONSE.replace('계란 수입은', '닭고기 수입은'),
            EGG_IMPORT_RESPONSE.replace('한시적 조치', '장기적 조치'),
            EGG_IMPORT_RESPONSE.replace('한시적 조치라고 해명했다', '한시적 조치가 아니라고 해명했다'),
            EGG_IMPORT_RESPONSE.replace('공급 부족과 가격 상승', '공급 증가와 가격 하락'),
            EGG_IMPORT_RESPONSE.replace('대응하기 위한', '무관한'),
            EGG_IMPORT_RESPONSE.replace('조치라고 해명했다', '조치라고 보기는 어렵다고 반박했다'),
            '브라질산 계란을 수입했다. AI에 따른 공급 부족과 가격 상승에 대응하기 위한 한시적 조치라고 해명했다.',
        ):
            with self.subTest(body=body):
                self.assertIsNone(s._korean_egg_import_response_summary(body))


if __name__ == '__main__':
    unittest.main()
