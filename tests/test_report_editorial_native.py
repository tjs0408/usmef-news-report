"""Offline, current-source editorial frames with mutation counterexamples."""

import unittest
from unittest.mock import patch

from src.article_hwpx_layout import summary_reference_layout
from src.report_editorial_native import (
    editorial_native_brief, editorial_native_source_excerpt, _us_broiler_demand_placements,
)
from src import overseas_article_digest as digest
from src import livestock_article_draft as collector


# Source clauses from the saved Oct21 and Sep4 pipeline originals. Keep them
# here so the regression tests do not depend on ignored diagnostic files.
US_BEEF_OCT = (
    "90CL 트리밍육은 7월 둘째 주 4.63달러로 역대 최고가를 기록한 후 하락세를 "
    "이어왔으나, 암소 도축 감소로 인한 lean beef 공급 부족으로 인해 여전히 "
    "높은 가격 수준을 유지하고 있다. "
    "아울러 지난 8월 트럼프 행정부는 분쇄육(ground beef)용 lean beef 공급을 위해 "
    "‘기타(others)’ 쿼터 카테고리 수입 물량 총 30만 톤에 대해 9월부터 11월까지 "
    "쿼터 외 관세(out-of-quota duty)를 한시적으로 철폐하는 행정명령을 발표했다."
)
US_BEEF_SEP = (
    "90CL 트리밍육 가격은 7월 둘째 주 4.63달러로 사상 최고가를 기록한 후 "
    "소폭 조정을 받았으나 암소 도축 감소로 인한 빠듯한 국내산 lean beef 공급과 "
    "견조한 수요가 가격을 지지하며, 여전히 역대 최고가 수준을 유지하고 있다. "
    "지난주에는 전주 대비 0.5% 소폭 하락한 4.52달러를 기록했다."
)
US_EGG_OCT = (
    "The USDA says 9.203 billion eggs were produced in September, up 6% on the year, "
    "with a 5% increase in the average number of layers to 385.065 million head "
    "and 1% rise in the rate of production per 100 layers. "
    "Egg production numbers have been up every month this year, in-line with USDA expectations "
    "as the industry continues to rebuild flocks after widespread Highly Pathogenic Avian "
    "Influenza infections while also trying to meet consumer demand for protein."
)
AU_EXPORTS_SEP = (
    "RECENT imported beef tariff impacts in China and the United States are clearly evident "
    "in Australia’s August beef export statistics released late yesterday. "
    "Total exports for the month to all markets reached 128,832 tonnes, a sizeable "
    "15,000t or 10pc decline on the previous month – but that can largely be attributed "
    "to lower mid-winter production, rather than any decline in overall demand."
)
DOMESTIC_BEEF = ('한우 대신 찾던 수입 소고기도 사정은 비슷하다. 미국 농무부(USDA) 등에 따르면 '
                 '미국은 가뭄과 사료비 부담으로 소 사육 규모가 75년 만에 최소 수준으로 줄었다. '
                 '호주산은 올해 낮은 관세를 적용받는 기준물량이 지난 7월에 모두 소진됐다.')
BRAZIL_OUTLOOK = ('Para 2027, as primeiras projeções do Departamento de Agricultura dos Estados Unidos (USDA), '
                  'apresentadas no relatório do Itaú BBA, indicam crescimento de 1,9% na produção brasileira '
                  'de carne de frango e de 0,9% nas exportações. Esse cenário considera a manutenção das '
                  'restrições de acesso ao mercado europeu durante todo o próximo ano.')
AU_TARIFF = ('국내 수입 소고기 시장의 한 축인 호주산 소고기에 지난 7월 하순부터 24%의 관세가 붙고 있습니다. '
             '한·호주 자유무역협정(FTA)에 따라 올해 적용되는 관세는 5.3%이지만, 낮은 관세로 들여올 수 있는 '
             '물량이 7월에 일찌감치 바닥났기 때문입니다.')
US_BROILER_DEMAND = (
    'U.S. broiler sets and placements were up on both the week and the year, continuing '
    'to point towards higher production as poultry producers try to meet demand. '
    'U.S. broiler numbers continue to rise. '
    'The USDA says placements of broiler-type chicks into meat production of 193.298 million '
    'head were up 2.494 million head on the week and 2% on the year, with those birds '
    'heading to market starting in mid-November. '
    'Cumulative 2026 placements are holding 2% ahead of 2025. '
    '245.764 million broiler-type eggs were set into incubation, 883,000 more than the '
    'previous week and 3% larger than last year.'
)
US_BROILER_BODY = US_BROILER_DEMAND.split('demand. ', 1)[1]


class EditorialNativeTests(unittest.TestCase):
    def test_broiler_demand_signal_and_placements_pass_real_pipeline_and_two_line_gates(self):
        summary = editorial_native_brief('us_chicken', US_BROILER_DEMAND)
        self.assertIn('수요 충족을 위한 생산 확대 시사', summary)
        self.assertIn('병아리 입식수 1억 9329만 8000마리로 전년비 2% 증가', summary)
        self.assertNotIn('생산량 증가', summary)
        self.assertNotIn('245', summary)
        self.assertTrue(digest._valid_brief(summary, 'us_chicken', US_BROILER_DEMAND),
                        digest.brief_validation_reasons(summary, 'us_chicken', US_BROILER_DEMAND))
        self.assertTrue(40 <= len(summary) <= 95)
        layout = summary_reference_layout(summary, 'us_chicken')
        self.assertTrue(layout['withinLineLimit'], layout)
        self.assertEqual(layout['estimatedLines'], 2)
        self.assertEqual(digest._native_report_sentence('us_chicken', US_BROILER_DEMAND), summary)
        evidence = editorial_native_source_excerpt(US_BROILER_DEMAND, summary)
        self.assertIn('try to meet demand.', evidence)
        self.assertIn('193.298 million', evidence)
        self.assertIn('2% on the year', evidence)
        self.assertIn(evidence, US_BROILER_DEMAND)
        self.assertNotIn('Cumulative', evidence)
        self.assertNotIn('245.764', evidence)
        self.assertEqual(digest._native_source_excerpt(US_BROILER_DEMAND, summary), evidence)
        self.assertTrue(digest._valid_brief(summary, 'us_chicken', evidence))

    def test_broiler_placements_use_current_values_in_two_alternate_sources(self):
        for amount, annual, heads in (('195.405', '3.5', '1억 9540만 5000'),
                                     ('204.125', '1.7', '2억 412만 5000')):
            with self.subTest(amount=amount, annual=annual):
                body = US_BROILER_DEMAND.replace('193.298', amount).replace('and 2% on the year', f'and {annual}% on the year')
                summary = editorial_native_brief('us_chicken', body)
                self.assertIn(f'입식수 {heads}마리로 전년비 {annual}% 증가', summary)
                self.assertNotIn('9329만', summary)
                self.assertTrue(digest._valid_brief(summary, 'us_chicken', body))
                self.assertTrue(summary_reference_layout(summary, 'us_chicken')['withinLineLimit'])
                evidence = editorial_native_source_excerpt(body, summary)
                self.assertIn(amount, evidence)
                self.assertIn(f'{annual}% on the year', evidence)
                self.assertNotIn('193.298', evidence)

    def test_broiler_demand_frame_abstains_without_its_own_us_causal_and_observed_block(self):
        for body in (
            US_BROILER_DEMAND.split('U.S. broiler numbers', 1)[1],
            US_BROILER_DEMAND.replace('as poultry producers try to meet demand', 'as the industry changes'),
            US_BROILER_DEMAND.replace('try to meet demand', 'do not try to meet demand'),
            US_BROILER_DEMAND.replace('U.S. broiler sets', 'Canadian broiler sets'),
            US_BROILER_DEMAND.replace('U.S. broiler sets', 'In Canada, U.S. broiler sets'),
            US_BROILER_DEMAND.replace('The USDA says placements', 'The USDA says Canadian placements'),
            US_BROILER_DEMAND.replace('broiler-type chicks', 'turkey poults'),
            US_BROILER_DEMAND.replace('The USDA says placements', 'Another Canadian chicken report follows. The USDA says placements'),
            US_BROILER_DEMAND.replace('head were up 2.494', 'head will be up 2.494'),
            US_BROILER_DEMAND.replace('head were up 2.494', 'head were not up 2.494'),
            US_BROILER_DEMAND.replace('head were up 2.494', 'head were down 2.494'),
            US_BROILER_DEMAND.replace('and 2% on the year', 'and 2% on the month'),
            US_BROILER_DEMAND.replace('and 2% on the year', 'and 0% on the year'),
        ):
            with self.subTest(body=body[:180]):
                self.assertIsNone(_us_broiler_demand_placements(body))

    def test_broiler_body_keeps_observed_placements_and_their_forward_market_date(self):
        with patch.object(digest, '_ollama_generate', side_effect=AssertionError('No AI needed')) as ai:
            summary = editorial_native_brief('us_chicken', US_BROILER_BODY)
            self.assertIn('입식수는 1억 9329만 8000마리로 전년비 2% 증가', summary)
            self.assertIn('11월 중순부터 출하 예정', summary)
            self.assertNotIn('수요', summary)
            self.assertNotIn('생산 확대', summary)
            self.assertNotIn('종란', summary)
            self.assertTrue(digest._valid_brief(summary, 'us_chicken', US_BROILER_BODY),
                            digest.brief_validation_reasons(summary, 'us_chicken', US_BROILER_BODY))
            self.assertEqual(digest._native_report_sentence('us_chicken', US_BROILER_BODY), summary)
            self.assertTrue(40 <= len(summary) <= 95)
            layout = summary_reference_layout(summary, 'us_chicken')
            self.assertTrue(layout['withinLineLimit'], layout)
            self.assertEqual(layout['estimatedLines'], 2)
            evidence = editorial_native_source_excerpt(US_BROILER_BODY, summary)
            self.assertIn(evidence, US_BROILER_BODY)
            self.assertTrue(evidence.startswith('U.S. broiler numbers continue to rise.'))
            self.assertIn('193.298 million', evidence)
            self.assertIn('starting in mid-November.', evidence)
            self.assertNotIn('245.764', evidence)
            self.assertEqual(digest._native_source_excerpt(US_BROILER_BODY, summary), evidence)
            self.assertTrue(digest._valid_brief(summary, 'us_chicken', evidence))
            ai.assert_not_called()

    def test_broiler_body_month_period_and_placement_values_follow_each_new_source(self):
        for amount, annual, timing, expected_heads, expected_time in (
            ('195.405', '3.5', 'early-May', '1억 9540만 5000', '5월 초'),
            ('204.125', '1.7', 'late-September', '2억 412만 5000', '9월 말'),
        ):
            body = US_BROILER_BODY.replace('193.298', amount).replace('and 2% on the year', f'and {annual}% on the year').replace('mid-November', timing)
            with self.subTest(amount=amount, timing=timing):
                summary = editorial_native_brief('us_chicken', body)
                self.assertIn(f'입식수는 {expected_heads}마리로 전년비 {annual}% 증가', summary)
                self.assertIn(f'{expected_time}부터 출하 예정', summary)
                self.assertNotIn('11월', summary)
                self.assertTrue(digest._valid_brief(summary, 'us_chicken', body))
                self.assertTrue(summary_reference_layout(summary, 'us_chicken')['withinLineLimit'])

    def test_broiler_body_requires_its_own_us_observation_and_same_birds_future_date(self):
        self.assertNotIn(11.0, digest._brief_numeric_values('November'))
        for body in (
            US_BROILER_BODY.replace('U.S. broiler', 'Canadian broiler'),
            US_BROILER_BODY.replace('U.S. broiler', 'In Canada, U.S. broiler'),
            US_BROILER_BODY.replace('The USDA says placements', 'The USDA says Canadian placements'),
            US_BROILER_BODY.replace('broiler-type chicks', 'turkey poults'),
            US_BROILER_BODY.replace('The USDA says placements', 'A separate Canadian poultry report follows. The USDA says placements'),
            US_BROILER_BODY.replace('head were up 2.494', 'head will be up 2.494'),
            US_BROILER_BODY.replace('head were up 2.494', 'head were not up 2.494'),
            US_BROILER_BODY.replace('head were up 2.494', 'head were down 2.494'),
            US_BROILER_BODY.replace('and 2% on the year', 'and 2% on the month'),
            US_BROILER_BODY.replace(', with those birds heading to market starting in mid-November', ''),
            US_BROILER_BODY.replace('those birds', 'Canadian birds'),
            US_BROILER_BODY.replace('heading to market', 'not heading to market'),
            US_BROILER_BODY.replace('heading to market starting in', 'sent to market last'),
        ):
            with self.subTest(body=body[:180]):
                self.assertIsNone(editorial_native_brief('us_chicken', body))
                self.assertNotIn(11.0, digest._brief_numeric_values(body))

    def test_broiler_visible_publisher_summary_is_not_needed_or_merged_with_body(self):
        from bs4 import BeautifulSoup

        html = ('<html lang="en"><head><meta property="article:published_time" '
                'content="2031-05-14T12:00:00-05:00"><meta property="og:title" '
                'content="Broiler placements rise"></head><body><main><div id="post_content">'
                '<div class="tldl_wrapper"><h2>Summary</h2>'
                + US_BROILER_DEMAND.split('U.S. broiler numbers', 1)[0]
                + '</div><p class="wp-block-paragraph">' + US_BROILER_BODY
                + '</p></div></main></body></html>')
        with patch.object(digest, '_download_soup', return_value=BeautifulSoup(html, 'html.parser')), \
                patch.object(digest, '_ollama_generate', side_effect=AssertionError('No AI needed')) as ai:
            article = collector._read_original_article(
                {'url': 'https://brownfieldagnews.com/news/current-broiler-placements/'},
                collector.SPECS_BY_KEY['us_chicken'])
            self.assertNotIn('try to meet demand', article['body'])
            summary = digest._native_report_sentence('us_chicken', article['body'])
            self.assertIn('입식수', summary)
            self.assertIn('출하 예정', summary)
            self.assertNotIn('종란', summary)
            self.assertTrue(summary_reference_layout(summary, 'us_chicken')['withinLineLimit'])
            evidence = digest._native_source_excerpt(article['body'], summary)
            self.assertIn('U.S. broiler numbers continue to rise.', evidence)
            self.assertIn('starting in mid-November.', evidence)
            self.assertNotIn('try to meet demand', evidence)
            ai.assert_not_called()

    def test_broiler_retracted_disputed_or_unconfirmed_figures_abstain(self):
        statement_end = 'heading to market starting in mid-November.'
        for correction in ('These figures were retracted.', 'That claim was false.',
                           'This report was incorrect.', 'These numbers are disputed.',
                           'This statement is unconfirmed.', 'Those figures have not been confirmed.',
                           'This remains unconfirmed.', 'These were denied.'):
            for original in (US_BROILER_DEMAND, US_BROILER_BODY):
                body = original.replace(statement_end, statement_end + ' ' + correction)
                with self.subTest(correction=correction, demand=original == US_BROILER_DEMAND):
                    self.assertIsNone(editorial_native_brief('us_chicken', body))

    def test_new_foreign_market_source_frames_pass_real_pipeline_gates(self):
        for kind, body in (('domestic', DOMESTIC_BEEF), ('domestic', AU_TARIFF), ('brazil_chicken', BRAZIL_OUTLOOK)):
            summary = editorial_native_brief(kind, body)
            self.assertTrue(digest._valid_brief(summary, kind, body), digest.brief_validation_reasons(summary, kind, body))
            self.assertTrue(summary_reference_layout(summary, kind)['withinLineLimit'])
            self.assertEqual(digest._native_report_sentence(kind, body), summary)
            self.assertIn(editorial_native_source_excerpt(body, summary), body)
            self.assertEqual(digest._native_source_excerpt(body, summary), editorial_native_source_excerpt(body, summary))

    def test_tariff_frame_preserves_import_policy_not_retailer_promotion(self):
        summary = editorial_native_brief('domestic', AU_TARIFF)
        self.assertIn('5.3%에서 24%로 인상', summary)
        self.assertIn('지난 7월 소진', summary)
        self.assertNotIn('할인', summary)
        for changed in (AU_TARIFF.replace('호주산', '한국산'), AU_TARIFF.replace('붙고 있습니다', '붙지 않습니다'),
                        AU_TARIFF.replace('붙고 있습니다', '붙을 전망입니다'), AU_TARIFF.replace('24%', '3%'),
                        AU_TARIFF.replace('물량이 7월에', '물량이 8월에'), AU_TARIFF.replace('바닥났기', '늘어났기')):
            self.assertIsNone(editorial_native_brief('domestic', changed))

    def test_domestic_cattle_cause_and_period_must_be_in_the_same_observed_clause(self):
        for changed in (DOMESTIC_BEEF.replace('미국은', '한국은'), DOMESTIC_BEEF.replace('가뭄과', '가뭄과 무관한'),
                        DOMESTIC_BEEF.replace('줄었다.', '줄지 않았다.'), DOMESTIC_BEEF.replace('줄었다.', '줄어들 전망이다.'),
                        DOMESTIC_BEEF.replace('사료비 부담으로', '사료비 부담이 아니다. 그 외 다른 사정으로')):
            self.assertIsNone(editorial_native_brief('domestic', changed))
        summary = editorial_native_brief('domestic', DOMESTIC_BEEF.replace('75년', '70년'))
        self.assertIn('70년', summary)
        self.assertNotIn('75년', summary)

    def test_brazil_outlook_keeps_future_and_the_eu_access_premise(self):
        summary = editorial_native_brief('brazil_chicken', BRAZIL_OUTLOOK)
        self.assertIn('유럽 시장 접근 제한 연중 유지 시', summary)
        self.assertIn('2027년', summary)
        self.assertIn('0.9%', summary)
        self.assertTrue(summary.endswith('전망'))
        for changed in (BRAZIL_OUTLOOK.replace('crescimento de', 'queda de'), BRAZIL_OUTLOOK.replace('brasileira', 'chinesa'),
                        BRAZIL_OUTLOOK.replace('considera a manutenção', 'não considera a manutenção'),
                        BRAZIL_OUTLOOK.replace('próximo ano', 'próximo mês'), BRAZIL_OUTLOOK.split('Esse cenário')[0]):
            self.assertIsNone(editorial_native_brief('brazil_chicken', changed))

    def test_native_evidence_never_selects_unrelated_month_eight_prime_grade(self):
        unrelated = 'Prime 등급 비중은 7월과 8월에 낮아졌다. '
        body = unrelated + US_BEEF_OCT
        summary = editorial_native_brief('us', body)
        evidence = digest._native_source_excerpt(body, summary)
        self.assertNotIn('Prime', evidence)
        self.assertIn('암소 도축 감소', evidence)
        self.assertIn('지난 8월', evidence)
        self.assertIn('쿼터 외 관세', evidence)

    def test_domestic_research_import_background_is_not_a_direct_foreign_market_story(self):
        body = ('세계 4위의 소고기 수입국인 우리나라는 소고기를 해외에서 많이 수입하는 나라인 만큼 '
                '수입 고기를 대신하고 가격을 안정시킬 수 있는 독자적인 배양육 기술이 필요했다.')
        candidate = {'title': '한우 등심 절반 가격…스테이크 배양육 개발', 'body': body}
        profile = collector._selection_profile(candidate, collector.SPECS_BY_KEY['domestic'])
        self.assertIsNotNone(profile)
        self.assertEqual(profile[0], 2)
        foreign = {'title': '미국, 배양 소고기 판매 승인해 공급 확대',
                   'body': '미국 정부는 배양 소고기 판매를 승인했다. 미국의 배양 소고기 공급이 늘어날 전망이다.'}
        self.assertEqual(collector._selection_profile(foreign, collector.SPECS_BY_KEY['domestic'])[0], 0)

    def test_actual_source_frames_preserve_context_and_nominal_ending(self):
        for kind, body in (("us", US_BEEF_OCT), ("us", US_BEEF_SEP),
                           ("us_egg", US_EGG_OCT), ("australia", AU_EXPORTS_SEP)):
            with self.subTest(kind=kind, body=body[:30]):
                result = editorial_native_brief(kind, body)
                self.assertIsNotNone(result)
                self.assertGreaterEqual(len(result), 40)
                self.assertLessEqual(len(result), 95 if kind == "us" else 55)
                self.assertFalse(result.endswith(("다", ".")))
                self.assertTrue(summary_reference_layout(result, kind)["withinLineLimit"], result)

    def test_beef_has_supply_price_context_not_recurring_output_numbers(self):
        result = editorial_native_brief("us", US_BEEF_OCT)
        for term in ("암소 도축 감소", "저지방 쇠고기 공급", "높은 가격 수준 유지", "지난 8월", "쿼터 외 관세", "철폐 발표"):
            self.assertIn(term, result)
        for term in ("30만", "90CL", "4.63", "급등", "공급 개선"):
            self.assertNotIn(term, result)

    def test_beef_observed_context_also_handles_other_saved_week_and_spacing(self):
        result = editorial_native_brief("us", US_BEEF_SEP)
        self.assertIn("높은 가격 수준 유지", result)
        self.assertNotIn("관세", result)
        self.assertEqual(result, editorial_native_brief("us", US_BEEF_SEP.replace(" ", "")))

    def test_policy_retains_its_own_observed_announcement_month(self):
        changed = US_BEEF_OCT.replace("지난 8월", "지난 11월")
        result = editorial_native_brief("us", changed)
        self.assertIn("지난 11월 분쇄육 원료", result)
        self.assertNotIn("지난 8월", result)
        self.assertLessEqual(len(result), 95)
        self.assertTrue(summary_reference_layout(result, "us")["withinLineLimit"])
        for changed in (
            US_BEEF_OCT.replace("지난 8월", "최근"),
            US_BEEF_OCT.replace("지난 8월", "지난해 8월"),
            US_BEEF_OCT.replace("지난 8월", "지난 13월"),
            US_BEEF_OCT.replace("지난 8월 트럼프 행정부는", "정부는"),
            US_BEEF_OCT.replace("지난 8월 트럼프 행정부는", "지난 8월 발표가 있었다. 트럼프 행정부는"),
        ):
            with self.subTest(changed=changed):
                result = editorial_native_brief("us", changed)
                self.assertIsNotNone(result)
                self.assertNotIn("관세", result)

    def test_beef_requires_positive_causal_construction_in_one_sentence(self):
        for changed in (
            US_BEEF_OCT.replace("암소 도축 감소로 인한", "암소 도축 증가로 인한"),
            US_BEEF_OCT.replace("암소 도축 감소로 인한", "암소 도축 감소와 무관한"),
            US_BEEF_OCT.replace("lean beef 공급 부족", "lean beef 공급 증가"),
            US_BEEF_OCT.replace("lean beef 공급 부족으로 인해", "lean beef 공급 부족이 아니지만"),
            US_BEEF_OCT.replace("높은 가격 수준을 유지하고 있다", "낮은 가격 수준을 유지하고 있다"),
            US_BEEF_OCT.replace("높은 가격 수준을 유지하고 있다", "높은 가격 수준을 유지하지 않고 있다"),
            US_BEEF_OCT.replace("높은 가격 수준을 유지하고 있다", "높은 가격 수준을 유지하고 있다는 주장은 사실이 아니다"),
            US_BEEF_OCT.replace("lean beef 공급 부족으로 인해 여전히", "lean beef 공급 부족이 아니다. 여전히"),
        ):
            with self.subTest(changed=changed):
                self.assertIsNone(editorial_native_brief("us", changed))

    def test_beef_rejected_future_or_negated_policy_does_not_invalidate_observed_supply(self):
        for changed in (
            US_BEEF_OCT.replace("한시적으로 철폐하는", "한시적으로 철폐하지 않는"),
            US_BEEF_OCT.replace("한시적으로 철폐하는", "영구적으로 철폐하는"),
            US_BEEF_OCT.replace("발표했다", "발표할 계획이다"),
            US_BEEF_OCT.replace("발표했다", "발표했다는 주장은 사실이 아니다"),
            US_BEEF_OCT.replace("쿼터 외 관세(out-of-quota duty)", "일반 관세"),
            US_BEEF_OCT.replace("분쇄육(ground beef)용 lean beef 공급을 위해", "분쇄육용 공급과 무관하게"),
        ):
            with self.subTest(changed=changed):
                result = editorial_native_brief("us", changed)
                self.assertIsNotNone(result)
                self.assertNotIn("관세", result)

    def test_egg_retains_same_month_annual_comparison_and_two_observed_drivers(self):
        result = editorial_native_brief("us_egg", US_EGG_OCT)
        for term in ("9월 계란 생산량", "산란계 수·산란율 증가와 함께", "전년 동월비 6% 증가"):
            self.assertIn(term, result)
        self.assertNotIn("HPAI", result)  # Article-wide context is not a quantified monthly cause.
        changed = US_EGG_OCT.replace("September", "February").replace("up 6%", "up 7.5%")
        result = editorial_native_brief("us_egg", changed)
        self.assertIn("2월", result)
        self.assertIn("7.5%", result)
        self.assertNotIn("9월", result)
        self.assertNotIn("6%", result)

    def test_egg_rejects_forecast_negation_regional_scope_and_changed_directions(self):
        for changed in (
            US_EGG_OCT.replace("were produced", "will be produced"),
            US_EGG_OCT.replace("were produced", "were not produced"),
            US_EGG_OCT.replace("in September", "in California in September"),
            US_EGG_OCT.replace("USDA says", "USDA says Canada produced"),
            US_EGG_OCT.replace("on the year", "on the month"),
            US_EGG_OCT.replace("up 6%", "down 6%"),
            US_EGG_OCT.replace("5% increase", "5% decrease"),
            US_EGG_OCT.replace("1% rise", "1% decline"),
            US_EGG_OCT.replace(", with a 5%", ". A separate report has a 5%"),
            US_EGG_OCT.replace("up 6%", "up 0%"),
        ):
            with self.subTest(changed=changed):
                self.assertIsNone(editorial_native_brief("us_egg", changed))

    def test_australia_winter_source_not_tariff_headline_supplies_the_cause(self):
        result = editorial_native_brief("australia", AU_EXPORTS_SEP)
        for term in ("호주 8월 전체 쇠고기 수출량", "겨울철 생산 감소", "전월비 10% 감소"):
            self.assertIn(term, result)
        self.assertNotIn("관세", result)
        self.assertNotIn("수요 감소", result)
        changed = AU_EXPORTS_SEP.replace("August", "July").replace("10pc", "7.5%")
        result = editorial_native_brief("australia", changed)
        self.assertIn("7월", result)
        self.assertIn("7.5%", result)

    def test_australia_rejects_other_scope_direction_cause_and_non_adjacent_anchor(self):
        for changed in (
            AU_EXPORTS_SEP.replace("Australia’s", "Brazil’s"),
            AU_EXPORTS_SEP.replace("all markets", "US ports"),
            AU_EXPORTS_SEP.replace("decline on the previous month", "increase on the previous month"),
            AU_EXPORTS_SEP.replace("previous month", "previous year"),
            AU_EXPORTS_SEP.replace("lower mid-winter production", "higher mid-winter production"),
            AU_EXPORTS_SEP.replace("can largely be attributed", "cannot be attributed"),
            AU_EXPORTS_SEP.replace("production, rather than any decline in overall demand", "demand"),
            AU_EXPORTS_SEP.replace("yesterday. Total", "yesterday. Another market report follows. Total"),
        ):
            with self.subTest(changed=changed):
                self.assertIsNone(editorial_native_brief("australia", changed))

    def test_unsupported_types_kinds_or_incomplete_sources_abstain(self):
        for kind, body in (("domestic", US_BEEF_OCT), ("us_pork", US_BEEF_OCT),
                           ("us", "지난주 소고기 생산량은 전주비 3.5% 증가했다."),
                           ("australia", "Australian exports fell as winter production declined."),
                           ("us_egg", "The USDA says egg production increased by 6%."),
                           ("us", ""), ("us", None)):
            with self.subTest(kind=kind, body=body):
                self.assertIsNone(editorial_native_brief(kind, body))


if __name__ == "__main__":
    unittest.main()
