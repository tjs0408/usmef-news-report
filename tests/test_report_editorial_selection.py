import unittest

from src.report_editorial_selection import (
    MAX_BODY_CHARACTERS,
    MAX_EDITORIAL_BONUS,
    editorial_candidate_link_supported,
    editorial_selection_bonus,
    editorial_selection_profile,
)


class EditorialSelectionTests(unittest.TestCase):
    def test_source_explanation_beats_bare_numeric_density(self):
        indicator = "미국 돼지고기 생산량은 120만 톤, 도축두수는 200만 두, 재고량은 30만 톤."
        linked = "미국 돼지고기 공급 부족으로 인해 소매가격이 전월보다 4% 상승했다."
        self.assertLess(editorial_selection_bonus("us_pork", "주간 돼지고기 시장", indicator),
                        editorial_selection_bonus("us_pork", "주간 돼지고기 시장", linked))
        profile = editorial_selection_profile("us_pork", "주간 시장", linked)
        self.assertEqual(profile["pattern"], "linked_market_change")
        self.assertIn(profile["evidence"], linked)

    def test_no_cause_is_generated_for_plain_source_price_change(self):
        source = "미국 돼지고기 소매가격은 전월보다 4% 상승했다."
        profile = editorial_selection_profile("domestic_pork", "미국 소비자물가 상승", source)
        self.assertEqual(profile["bonus"], 4)
        self.assertEqual(profile["pattern"], "price_or_trade_change")
        self.assertEqual(profile["evidence"], source)
        self.assertNotIn("공급 부족", profile["evidence"])

    def test_unrelated_oil_cause_does_not_explain_pork_price(self):
        source = "미국 휘발유 가격은 원유 공급 부족으로 인해 10% 상승했다.\n미국 돼지고기 가격은 2% 하락했다."
        profile = editorial_selection_profile("domestic_pork", "미국 소비자물가 발표", source)
        self.assertEqual(profile["bonus"], 4)
        self.assertNotIn("휘발유", profile["evidence"])
        self.assertNotIn("공급 부족", profile["evidence"])

    def test_another_species_explanation_is_not_transferred(self):
        source = "미국 닭고기 공급 부족으로 인해 닭고기 가격이 10% 상승했다.\n미국 돼지고기 생산량은 120만 톤이다."
        profile = editorial_selection_profile("domestic_pork", "미국 육류 시장", source)
        self.assertEqual(profile["bonus"], 1)
        self.assertNotIn("닭고기", profile["evidence"])

    def test_same_sentence_does_not_borrow_another_product_cause(self):
        for prefix in ("미국 휘발유 공급 부족으로 인해 물가가 상승했고 ",
                       "미국 닭고기 공급 부족으로 인해 가격이 상승했고 "):
            source = prefix + "돼지고기 가격은 2% 하락했다."
            profile = editorial_selection_profile("domestic_pork", "미국 소비자물가 발표", source)
            self.assertEqual(profile["bonus"], 4)
            self.assertNotIn("공급 부족", profile["evidence"])
            self.assertNotIn("상승", profile["evidence"])

    def test_consumer_word_does_not_double_count_demand_dimension(self):
        source = "미국 돼지고기 소비자가격은 조정 때문에 전월보다 4% 상승했다."
        profile = editorial_selection_profile("domestic_pork", "미국 소비자물가", source)
        self.assertEqual(profile["bonus"], 4)
        self.assertNotIn("demand", profile["themes"])

    def test_no_species_evidence_is_zero_even_with_many_numbers(self):
        source = "미국 휘발유 공급 감소로 인해 소비자물가가 3%, 유가가 7%, 운송비가 9% 상승했다."
        self.assertEqual(editorial_selection_bonus("domestic_pork", "미국 돼지고기 시장", source), 0)

    def test_domestic_source_needs_foreign_context(self):
        korean = "국내 돼지고기 공급 부족으로 인해 소매가격이 전월보다 4% 상승했다."
        self.assertEqual(editorial_selection_bonus("domestic_pork", "돼지고기 가격", korean), 0)
        self.assertGreater(editorial_selection_bonus("domestic_pork", "돼지고기 가격", korean.replace("국내", "중국")), 0)

    def test_foreign_macro_price_article_with_product_body_is_useful(self):
        source = "돼지고기 소비자가격은 전년 동월보다 12% 하락했고 생산량 증가와 공급 과잉이 배경이다."
        profile = editorial_selection_profile("domestic_pork", "중국 9월 소비자물가 상승", source)
        self.assertGreater(profile["bonus"], 0)
        self.assertIn("돼지고기", profile["evidence"])

    def test_foreign_headline_does_not_override_explicit_korean_paragraph(self):
        source = "국내 돼지고기 소매가격은 공급 부족으로 인해 4% 상승했다."
        self.assertEqual(editorial_selection_bonus("domestic_pork", "미국 소비자물가 상승", source), 0)

    def test_english_market_link_is_bound_to_commodity(self):
        source = "US cattle supply fell due to drought, pushing wholesale beef prices higher."
        profile = editorial_selection_profile("us", "US cattle market", source)
        self.assertEqual(profile["bonus"], MAX_EDITORIAL_BONUS)
        self.assertEqual(profile["pattern"], "linked_market_change")

    def test_processing_labor_disruption_is_not_outscored_by_repeated_counts(self):
        source = "미국 이민 단속 강화로 인해 쇠고기 가공업체 근로자의 결근이 늘면서 소 운송과 도축에 차질 발생이 우려된다."
        profile = editorial_selection_profile("us", "쇠고기 가공업계 현안", source)
        self.assertEqual(profile["bonus"], MAX_EDITORIAL_BONUS)
        self.assertIn("cost_risk_policy", profile["themes"])
        self.assertIn("supply", profile["themes"])

    def test_medical_egg_vaccine_is_not_a_market_reference(self):
        source = "미국 계란 변이 없는 세포배양 백신 수요가 증가하며 소비자 관심과 판매가 확대됐다."
        self.assertEqual(editorial_selection_bonus("domestic_egg", "독감 백신 주목", source), 0)

    def test_old_company_history_and_metadata_do_not_gain_bonus(self):
        self.assertEqual(editorial_selection_bonus("us_pork", "회사 소식", "돼지고기 업체는 2011년 미국 회사를 인수해 생산량을 200만 톤으로 확대했다."), 0)
        title = "US pork prices rise on tight supply"
        metadata = title + "\nPublished October 1, 2026\nShare Facebook\nhttps://example.com/news\n2026-10-01"
        self.assertEqual(editorial_selection_bonus("us_pork", title, metadata), 0)

    def test_bounded_score_and_body_scan(self):
        paragraph = "US pork supply fell due to drought and retail prices rose 3%."
        self.assertLessEqual(editorial_selection_bonus("us_pork", "market", paragraph * 200), MAX_EDITORIAL_BONUS)
        self.assertEqual(editorial_selection_bonus("us_pork", "market", "x" * MAX_BODY_CHARACTERS + "\n" + paragraph), 0)
        self.assertEqual(editorial_selection_bonus("unknown", "market", paragraph), 0)

    def test_embedded_english_species_strings_are_not_species_evidence(self):
        source = "US pigment prices rose 20% due to supply restrictions and nugget production increased."
        self.assertEqual(editorial_selection_bonus("us_pork", "market", source), 0)
        self.assertEqual(editorial_selection_bonus("us_egg", "market", source), 0)

    def test_alternative_link_rejects_poultry_headline_with_background_meat_list(self):
        title = "브라질 닭고기 수입 확대 전망"
        body = "브라질 닭고기 수입량은 검역 완화로 인해 10% 증가할 전망이다.\n회사의 대표 취급 품목에는 쇠고기, 돼지고기, 닭고기 등이 포함된다."
        self.assertFalse(editorial_candidate_link_supported("domestic_pork", title, body))
        self.assertTrue(editorial_candidate_link_supported("domestic_chicken", title, body))

    def test_alternative_link_accepts_macro_title_with_actual_pork_price_fact(self):
        title = "중국 소비자물가 예상 하회"
        body = "휘발유 소비자가격은 전년보다 5% 올랐다.\n중국 돼지고기 가격은 공급 확대로 인해 12% 하락했다."
        self.assertTrue(editorial_candidate_link_supported("domestic_pork", title, body))

    def test_alternative_link_accepts_shared_import_change_not_background_list(self):
        body = "캐나다산 돼지고기와 닭고기의 수입 증가로 국내 축산업 생산 감소가 전망된다."
        self.assertTrue(editorial_candidate_link_supported("domestic_pork", "통상 협정 영향 분석", body))
        self.assertTrue(editorial_candidate_link_supported("eu_pork", "Trade outlook", "Pork and chicken imports will increase by 10%."))

    def test_alternative_link_does_not_borrow_following_poultry_fact(self):
        body = "미국 회사는 돼지고기와 닭고기를 취급한다. 닭고기 생산량은 20% 증가했다."
        self.assertFalse(editorial_candidate_link_supported("domestic_pork", "미국 닭고기 생산 증가", body))

    def test_alternative_link_is_not_another_eligibility_check(self):
        body = "국내 돼지고기 가격이 공급 부족으로 인해 4% 상승했다."
        # Existing eligibility owns source/date/foreign-context checks.  This
        # helper must not reject a general headline or add a full-text fetch.
        self.assertTrue(editorial_candidate_link_supported("domestic_pork", "국내 물가", body))
        self.assertTrue(editorial_candidate_link_supported("domestic_pork", "돼지고기 시장", ""))
        self.assertTrue(editorial_candidate_link_supported("domestic_pork", "중국 소비자물가 예상 하회", ""))
        self.assertTrue(editorial_candidate_link_supported("domestic_pork", "돼지고기·닭고기 수입 전망", ""))

    def test_competing_headline_keeps_actual_target_fact_without_new_foreign_gate(self):
        body = "돼지고기 소매가격은 전월보다 4% 상승했다."
        self.assertTrue(editorial_candidate_link_supported("domestic_pork", "미국 닭고기 가격 변화", body))


if __name__ == "__main__":
    unittest.main()
