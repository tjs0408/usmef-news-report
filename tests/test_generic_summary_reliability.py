"""Date-independent source proposals, nominal style and hatchery variants."""
import unittest
from unittest.mock import patch

from src import overseas_article_digest as s
from src.article_hwpx_layout import summary_reference_layout
from src.grounded_korean_brief import genuine_foreign_context, korean_source_proposals
from src.regional_egg_quote_facts import native_new_york_egg_quote


# Public Brownfield original, 2026-09-02. Numbers are fixtures, not application
# rules: changed values/directions and other weeks are exercised below.
HATCHERY = (
    'The USDA says 250.686 million broiler-type eggs were set into incubators, '
    'falling 1.237 million on the week partially due to high temperatures in some '
    'states, but up slightly on the year thanks to a larger number of laying hens. '
    '194.367 million broiler-type chicks went into meat production, 668,000 less '
    'than the previous week, but modestly more than a year ago, with cumulative '
    'placements holding 2% faster than last year.'
)
NEW_YORK = (
    'The USDA Agricultural Marketing Service released its daily New York shell egg report '
    'for September 1, 2026, covering caged white eggs delivered to store doors. '
    'According to the report, prices for extra large and large eggs declined by one cent '
    'per dozen compared to the previous trading day, while medium egg prices remained unchanged.'
)


class GenericSummaryReliabilityTests(unittest.TestCase):
    def tearDown(self):
        s._summarize_report_sentence.cache_clear()

    def test_iran_and_india_inside_korean_grammar_are_not_foreign_context(self):
        for text in ('돼지가격은 명절 이후 약세로 접어들 것이란 예상',
                     '국내 계란 가격은 공급 증가로 하락하고 시장 안정의 견인도 기대'):
            self.assertFalse(genuine_foreign_context(text))
            kind = 'domestic_pork' if '돼지' in text else 'domestic_egg'
            self.assertFalse(s._valid_brief(text, kind, text))
        for text in ('이란 돼지고기 수입', '인도산 계란 수출', '일본의 돼지고기 가격',
                     '브라질·스페인산 돈육 수입', '해외 계란 운송', 'EU 닭고기 검역'):
            self.assertTrue(genuine_foreign_context(text))

    def test_new_affirmative_predicates_nominalize_without_reinterpreting_negation(self):
        examples = {
            '미국 소고기 도축량은 공급 감소 여파로 지난해와 비교해 크게 줄었다.':
            '미국 소고기 도축량은 공급 감소 여파로 지난해와 비교해 크게 감소',
            '미국 소고기 도매가격은 공급 부족으로 상승세를 보였다.':
            '미국 소고기 도매가격은 공급 부족으로 상승세',
            '일본 계란의 전국 생산량은 전년 대비 5% 감소한 것으로 집계됐다.':
            '일본 계란의 전국 생산량은 전년 대비 5% 감소한 것으로 집계',
        }
        for original, expected in examples.items():
            self.assertEqual(s._normalize_report_sentence(original, 'us'), expected)
        for original in ('미국 소고기 도축량은 줄지 않았다.',
                         '일본 계란 생산량은 증가할 수도 있다.',
                         '미국 소고기 가격이 상승할 것이다.',
                         '돼지고기 수입 확대를 검토하지 않았다.'):
            self.assertEqual(s._normalize_report_sentence(original, 'us'), original.rstrip('.'))

    def test_historical_hatchery_cause_is_grounded_fits_and_needs_no_generation(self):
        with patch.object(s, '_ollama_generate', side_effect=AssertionError('no inference needed')):
            summary = s._summarize_report_sentence('us_chicken', 'Broiler numbers', HATCHERY)
        self.assertIn('일부 주 고온 영향 등으로', summary)
        self.assertIn('전주비 123만 7000개 감소했으나', summary)
        self.assertIn('산란계 수 증가로 전년비 소폭 증가', summary)
        self.assertNotIn('전년비 2%', summary)
        self.assertTrue(s._valid_brief(summary, 'us_chicken', HATCHERY))
        self.assertTrue(summary_reference_layout(summary, 'us_chicken')['withinLineLimit'])
        self.assertFalse(s._supported_measurements(summary.replace('개', '마리'), HATCHERY))

    def test_weekly_fact_variants_have_exact_dynamic_totals_and_units(self):
        facts = s._broiler_hatchery_weekly_facts(HATCHERY)
        self.assertIn(('eggs', '250686000', '1237000', 'down'), facts)
        self.assertIn(('chicks', '194367000', '668000', 'down'), facts)
        changed = HATCHERY.replace('250.686', '245.118').replace('falling 1.237', 'rising 0.347')
        summary = s._native_report_sentence('us_chicken', changed)
        self.assertIn('전주비 34만 7000개 증가', summary)
        self.assertTrue(s._valid_brief(summary, 'us_chicken', changed))
        self.assertNotIn('감소했으나', summary)
        for original in (HATCHERY.replace('on the week', 'on the year'),
                         HATCHERY.replace('were set', 'will be set'),
                         HATCHERY.replace('broiler-type eggs', 'turkey eggs')):
            self.assertIsNone(s._broiler_hatchery_context_summary(original))

    def test_qualitative_annual_cause_never_borrows_another_sentence_or_negation(self):
        for original in (HATCHERY.replace('thanks to', 'not thanks to'),
                         HATCHERY.replace('larger number', 'smaller number'),
                         HATCHERY.replace('laying hens', 'pigs'),
                         HATCHERY.replace(', but up slightly', '. Other data are up slightly')):
            self.assertIsNone(s._broiler_hatchery_context_summary(original))

    def test_korean_original_fact_candidates_do_not_invent_overseas_context(self):
        local = '돼지고기 가격은 명절까지 일시적으로 반등한 후 명절 이후 약세로 접어들 것이란 예상이다.'
        overseas = '일본산 돼지고기 수입량은 공급 감소의 영향으로 지난해와 비교해 5% 감소한 것으로 집계됐다.'
        candidates = korean_source_proposals('domestic_pork', local + '\n' + overseas)
        self.assertNotIn(local, candidates)
        self.assertIn(overseas, candidates)
        native = s._native_report_sentence('domestic_pork', local + '\n' + overseas)
        self.assertIsNotNone(native)
        self.assertIn('일본산 돼지고기 수입량', native)
        self.assertTrue(s._valid_brief(native, 'domestic_pork', local + '\n' + overseas))

    def test_proposal_may_select_first_independent_fact_but_not_cut_a_condition(self):
        original = ('일본산 돼지고기 수입량은 공급 감소의 영향으로 지난해와 비교해 5% 감소했으며, '
                    '수입가격도 지난해보다 3% 상승했다.')
        proposals = korean_source_proposals('domestic_pork', original)
        self.assertIn(original.split('했으며')[0] + '했다', proposals)
        conditional = original.replace('5% 감소했으며', '5% 감소할 것으로 예상했으며')
        self.assertEqual(korean_source_proposals('domestic_pork', conditional), [conditional])

    def test_korean_section_heading_is_not_an_asserted_market_body_fact(self):
        heading = '# 돼지고기 시장, 추석 전후 희비 갈리나…특수 후 수입 급증·재고 부담에 약세 전환'
        fact = '돼지고기 가격 상승은 주로 EU 지역 고온 현상으로 가축의 성장이 둔화한 데 따른 것이다.'
        proposals = korean_source_proposals('domestic_pork', heading + '\n' + fact)
        self.assertFalse(any('희비 갈리나' in proposal for proposal in proposals))
        valid = [s._normalize_report_sentence(proposal, 'domestic_pork') for proposal in proposals]
        valid = [proposal for proposal in valid if s._valid_brief(proposal, 'domestic_pork', fact)]
        self.assertTrue(valid)
        self.assertTrue(any(summary_reference_layout(proposal, 'domestic_pork')['withinLineLimit']
                            for proposal in valid))
        self.assertTrue(all('EU' in proposal and '고온' in proposal and '성장 둔화' in proposal
                            for proposal in valid))

    def test_one_asserted_additive_cause_retains_own_subject_and_price_outcome(self):
        original = ('쇠고기는 한육우 사육 마릿수와 도축 가능 물량이 줄어든 데다 '
                    '미국 등 수출국의 생산 감소와 고환율이 겹치면서 가격이 높은 수준을 유지했다.')
        proposals = korean_source_proposals('domestic', original)
        expected = '쇠고기는 미국 등 수출국의 생산 감소와 고환율이 겹치면서 가격이 높은 수준을 유지'
        self.assertIn(expected + '했다', proposals)
        self.assertTrue(s._valid_brief(expected, 'domestic', original))
        self.assertTrue(summary_reference_layout(expected, 'domestic')['withinLineLimit'])
        self.assertNotIn('가격 하락', ' '.join(proposals))
        # A common reporting period/forecast on the omitted clause must not
        # disappear while the retained clause is presented as a current fact.
        for qualifier in ('지난해 ', '올해 9월 ', '감소할 가능성이 있어 '):
            qualified = original.replace('한육우 사육', qualifier + '한육우 사육')
            candidates = korean_source_proposals('domestic', qualified)
            self.assertFalse(any(proposal.startswith('쇠고기는 미국') for proposal in candidates))

    def test_trade_agreement_compaction_keeps_month_destination_and_negotiation_stage(self):
        original = ('올해 4월에는 베트남과 열처리 가금육 수출에 합의했고, '
                    '7월에는 홍콩으로의 닭고기 수출 재개 협상도 마쳤다.')
        proposals = korean_source_proposals('domestic_chicken', original)
        expected = '올해 4월 베트남과 열처리 가금육 수출 합의, 7월 홍콩으로의 닭고기 수출 재개 협상 완료'
        self.assertIn(expected, proposals)
        self.assertTrue(s._valid_brief(expected, 'domestic_chicken', original))
        self.assertTrue(summary_reference_layout(expected, 'domestic_chicken')['withinLineLimit'])
        self.assertIn('협상 완료', expected)
        self.assertNotIn('수출량', expected)
        changed = original.replace('4월', '2월').replace('7월', '8월').replace('베트남', '대만').replace('홍콩', '싱가포르')
        changed_candidates = korean_source_proposals('domestic_chicken', changed)
        changed_expected = expected.replace('4월', '2월').replace('7월', '8월').replace('베트남', '대만').replace('홍콩', '싱가포르')
        self.assertIn(changed_expected, changed_candidates)
        self.assertTrue(s._valid_brief(changed_expected, 'domestic_chicken', changed))
        denial = original.replace('수출에 합의했고', '수출에 합의하지 않았고')
        self.assertEqual(korean_source_proposals('domestic_chicken', denial), [])

    def test_trade_diversion_selects_actual_flow_without_broadening_ban_origin(self):
        original = ('특히 일본의 스페인산 돈육 수입 중단과 중국의 수입 수요 감소 영향으로 '
                    '스페인·브라질산 냉동 전지와 후지가 국내로 우회 유입되면서 국내산 후지 '
                    '가격이 이달 kg당 4800원대로 하락했고 덤핑 판매를 유발하고 있다.')
        expected = ('일본의 스페인산 돈육 수입 중단·중국 수입 수요 감소로 '
                    '냉동 전·후지 국내 우회 유입')
        proposals = korean_source_proposals('domestic_pork', original)
        self.assertIn(expected, proposals)
        self.assertTrue(s._supported_measurements(expected, original))
        self.assertTrue(s._korean_origin_species_pairs(expected).issubset(
            s._korean_origin_species_pairs(original)))
        self.assertTrue(summary_reference_layout(expected, 'domestic_pork')['withinLineLimit'])
        self.assertIn('일본의 스페인산 돈육 수입 중단', expected)
        self.assertNotIn('4800원', expected)
        changed = original.replace('일본', '영국').replace('스페인', '프랑스').replace('중국', '베트남')
        self.assertIn(expected.replace('일본', '영국').replace('스페인', '프랑스').replace('중국', '베트남'),
                      korean_source_proposals('domestic_pork', changed))
        for unasserted in (original.replace('우회 유입되면서', '우회 유입될 것으로 예상되면서'),
                           original.replace('수입 중단과', '수입 중단 가능성과')):
            self.assertNotIn(expected, korean_source_proposals('domestic_pork', unasserted))

    def test_compaction_never_relabels_all_agriculture_survey_as_cattle_farmers(self):
        original = ('호주에서 소고기를 생산하고 있는 가운데 농축산업 종사자 전체를 대상으로 한 '
                    '설문조사 결과 41%가 과도한 업무 압박으로 농축산업 포기나 전업을 검토하고 있다.')
        proposals = korean_source_proposals('domestic', original)
        for proposal in proposals:
            self.assertIn('농축산업 종사자 전체', proposal)
            self.assertNotIn('육우 농가 41%', proposal)
            self.assertNotIn('소고기 농가 41%', proposal)

    def test_regional_daily_egg_quote_keeps_region_sizes_denominator_period(self):
        with patch.object(s, '_ollama_generate', side_effect=AssertionError('no inference needed')):
            summary = s._summarize_report_sentence('us_egg', 'New York shell eggs', NEW_YORK)
        for fact in ('뉴욕', '특대·대란', '전일비', '12개당 1센트 하락', '중란 보합'):
            self.assertIn(fact, summary)
        self.assertNotIn('전국', summary)
        self.assertTrue(s._valid_brief(summary, 'us_egg', NEW_YORK))
        self.assertTrue(summary_reference_layout(summary, 'us_egg')['withinLineLimit'])
        self.assertIn('cents', s._native_source_excerpt(NEW_YORK, summary).replace('cent ', 'cents '))
        self.assertFalse(s._supported_measurements(summary.replace('센트', '달러'), NEW_YORK))

    def test_regional_egg_quote_changes_values_and_never_infers_a_national_weekly_quote(self):
        changed = NEW_YORK.replace('September 1, 2026', 'August 25, 2025').replace('declined by one cent', 'increased by 2 cents')
        summary = native_new_york_egg_quote(changed)[0]
        self.assertIn('12개당 2센트 상승', summary)
        self.assertTrue(s._valid_brief(summary, 'us_egg', changed))
        for original in (NEW_YORK.replace('New York', 'California'),
                         NEW_YORK.replace('previous trading day', 'previous week'),
                         NEW_YORK.replace('remained unchanged', 'increased'),
                         NEW_YORK.replace('prices for', 'prices were not quoted; prices for'),
                         NEW_YORK.replace('cents', 'dollars').replace('cent ', 'dollar ')):
            self.assertIsNone(native_new_york_egg_quote(original))

    def test_generic_native_proposals_do_not_publish_empty_review_or_denial_prose(self):
        for body in ('미국 돼지고기 가격과 공급 관련 원문을 확인했다.',
                     '중국이 브라질 소고기 수입품에 대해 55%의 추가 관세를 부과하지 않는다고 상무부가 발표했다.'):
            self.assertEqual(korean_source_proposals('domestic_pork' if '돼지' in body else 'domestic', body), [])

    def test_following_anaphoric_correction_invalidates_extractive_source_claim(self):
        claim = '미국 쇠고기 도매가격은 수입 감소와 공급 부족의 영향으로 전년보다 8% 상승했다고 발표했다.'
        for correction in ('이후 상무부는 이 발표가 허위라고 부인했다.',
                           '상무부가 내용을 확인했다. 해당 수치는 오류로 정정됐다.'):
            body = claim + ' ' + correction
            self.assertEqual(korean_source_proposals('domestic', body), [])
            self.assertIsNone(s._extract_usmef_source_summary(body, kind='domestic'))
            self.assertIsNone(s._native_report_sentence('domestic', body))

    def test_following_regional_report_retraction_cannot_be_published(self):
        for correction in ('The USDA later corrected this report: those prices were not valid.',
                           'The report was reviewed. This statement was withdrawn by the USDA.'):
            body = NEW_YORK + ' ' + correction
            self.assertIsNone(native_new_york_egg_quote(body))
            self.assertIsNone(s._native_report_sentence('us_egg', body))


if __name__ == '__main__':
    unittest.main()
