"""Offline one-line compaction; no facts may be traded for document fit."""
import unittest
import re
from unittest.mock import patch

from src import overseas_article_digest as s
from src.report_brief_style import (
    SECTION_AUDIENCES, SUMMARY_LIMITS, SUMMARY_MIN_LENGTH,
    SUMMARY_TARGET_LENGTH, STYLE_VERSION, style_prompt, TWO_LINE_SECTIONS,
)


class OneLineBriefTests(unittest.TestCase):
    def tearDown(self):
        s._summarize_report_sentence.cache_clear()

    def test_twelve_prompts_follow_role_targets_without_lowering_the_minimum(self):
        self.assertEqual(STYLE_VERSION, "livestock-brief-v19")
        self.assertEqual(SUMMARY_MIN_LENGTH, 40)
        self.assertEqual(SUMMARY_TARGET_LENGTH, 50)
        for kind in SECTION_AUDIENCES:
            with self.subTest(kind=kind):
                prompt = style_prompt(kind)
                if kind in TWO_LINE_SECTIONS:
                    self.assertIn('65~85자', prompt)
                    self.assertNotIn('우선 40~50자', prompt)
                else:
                    self.assertIn("40~50자", prompt)
                    self.assertIn("40~45자", prompt)
                self.assertIn(f"40~{SUMMARY_LIMITS[kind]}자", prompt)
                self.assertIn("부정·승인 대기·전망", prompt)
                self.assertIn("최대 길이를 채우려고", prompt)
                self.assertIn("띄어쓰기를 없애지", prompt)

    def test_saved_production_brief_keeps_both_comparisons_and_exact_pounds(self):
        cases = (
            ("us", "지난주 소고기 생산량은 전주비 13.2% 큰 폭으로 증가했으나 전년비 2.8% 감소한 4억 8,700만 파운드를 기록"),
            ("us_pork", "지난주 돼지고기 생산량은 전주비 0.5% 증가했으나 전년비 2.3% 감소한 5억 4,570만 파운드를 기록"),
        )
        for kind, original in cases:
            with self.subTest(kind=kind):
                result = s.compact_report_summary(original, kind, target=45)
                self.assertTrue(40 <= len(result) <= 50, result)
                self.assertIn("지난주", result)
                self.assertIn("전주비", result)
                self.assertIn("전년비", result)
                self.assertIn("파운드(전주비 ", result)
                self.assertTrue(result.endswith(") 생산"), result)
                self.assertEqual(s._brief_numeric_values(result), s._brief_numeric_values(original))
                self.assertEqual(s._numeric_unit_facts(result), s._numeric_unit_facts(original))
                self.assertEqual(s._percent_directions(result), s._percent_directions(original))
                self.assertTrue(s._valid_brief(result, kind, original))

    def test_australian_export_keeps_period_mass_change_and_record(self):
        original = "호주의 9개월 누적 쇠고기 수출량은 전년 동기비 7% 증가한 120만9000톤으로 역대 최고치를 기록"
        result = s.compact_report_summary(original, "australia", target=45)
        self.assertTrue(40 <= len(result) <= 55, result)
        self.assertLess(len(result), len(original))
        for fact in ("9개월", "누적", "전년 동기비", "7%↑", "120만 9000톤", "역대 최고"):
            self.assertIn(fact, result)
        self.assertEqual(s._numeric_unit_facts(result), s._numeric_unit_facts(original))

    def test_placements_keep_exact_animals_not_eggs_or_percent(self):
        body = "189.689 million broiler-type chicks were placed into meat production, 3.632 million less than the previous week."
        with patch.object(s, "_ollama_generate") as model:
            result = s._native_report_sentence("us_chicken", body)
        model.assert_not_called()
        # Exact compound quantities take more space after natural grouping.
        # The target is soft: keep facts/spaces and allow two lines as needed.
        self.assertTrue(40 <= len(result) <= SUMMARY_LIMITS['us_chicken'], result)
        self.assertIn("363만 2000마리 줄어", result)
        self.assertIn("1억 8968만 9000마리", result)
        self.assertTrue(s._valid_brief(result, "us_chicken", body))

    def test_domestic_import_keeps_all_named_origins_and_does_not_add_sum(self):
        original = "정부는 올해 9월까지 미국에서 계란 1억2578만개를 수입했으며 태국·브라질·덴마크에서도 수입"
        result = s.compact_report_summary(original, "domestic_egg")
        self.assertTrue(40 <= len(result) <= 50, result)
        for fact in ("정부", "올해 9월까지", "미국", "1억 2578만개", "태국·브라질·덴마크"):
            self.assertIn(fact, result)
        self.assertEqual(s._brief_numeric_values(result), s._brief_numeric_values(original))

    def test_egg_quote_keeps_market_basis_supply_qualifier_and_direction(self):
        for direction in ("보합~하락", "보합~상승"):
            original = f"미국 계란의 전국 FOB 가중평균 가격은 {direction} 흐름을 보이는 가운데 공급은 대체로 보통 수준"
            result = s.compact_report_summary(original, "us_egg")
            self.assertTrue(40 <= len(result) <= 50, result)
            for fact in ("전국 FOB 가중평균", direction, "공급은 대체로 보통 수준"):
                self.assertIn(fact, result)

    def test_existing_eu_assessment_compacts_without_inventing_market_effect(self):
        original = "덴마크의 돼지 산업 전략 중단은 덴마크가 돼지고기 생산 모델에 대한 보다 넓은 평가를 준비하고 있음을 시사"
        result = s.compact_report_summary(original, "eu_pork")
        self.assertTrue(40 <= len(result) <= 45, result)
        self.assertIn("평가 준비 시사", result)
        self.assertNotIn("생산 감소", result)
        self.assertNotIn("가격", result)

    def test_brazil_approval_condition_and_sanitary_evaluation_both_remain(self):
        original = "브라질산 닭고기의 EU 수출은 위생 평가가 긍정적이지만 재개에 남은 행정 절차 완료 필요"
        result = s.compact_report_summary(original, "brazil_chicken", target=45)
        self.assertTrue(40 <= len(result) <= 50, result)
        for fact in ("브라질 닭고기", "EU 수출", "위생 평가 긍정적", "행정 절차 완료 필요"):
            self.assertIn(fact, result)
        self.assertNotIn("승인 완료", result)
        self.assertNotIn("재개 확정", result)

    def test_spacing_repair_only_changes_whitespace_and_preserves_number_commas(self):
        original = "전주비13.2% 증가·전년비2.8% 감소,4억 8,700만파운드 기록,역대최고치"
        result = s.normalize_report_spacing(original)
        self.assertEqual(result, "전주비 13.2% 증가·전년비 2.8% 감소, 4억 8,700만 파운드 기록, 역대 최고치")
        self.assertEqual(re.sub(r"\s+", "", original), re.sub(r"\s+", "", result))
        self.assertIn("8,700", result)
        self.assertEqual(s._brief_numeric_values(original), s._brief_numeric_values(result))
        self.assertEqual(s._numeric_unit_facts(original), s._numeric_unit_facts(result))
        self.assertEqual(s.normalize_report_spacing(result), result)

    def test_already_compacted_v14_production_reflows_without_pasted_words(self):
        original = "지난주 소고기 생산량 전주비13.2% 증가·전년비2.8% 감소,4억 8,700만파운드 기록"
        result = s.compact_report_summary(original, "us", target=45)
        self.assertEqual(result, "지난주 소고기 4억 8,700만 파운드(전주비 13.2%↑·전년비 2.8%↓) 생산")
        self.assertTrue(s._valid_brief(result, "us", original))
        self.assertFalse(s._valid_brief(result.replace("13.2%↑", "13.2%↓"), "us", original))
        self.assertFalse(s._valid_brief(result.replace("2.8%↓", "2.8%↑"), "us", original))

    def test_already_compacted_export_keeps_natural_spacing_and_both_clauses(self):
        original = "호주 9개월 누적 쇠고기 수출량 전년동기비7% 증가, 120만9000톤으로 역대최고치 기록"
        result = s.compact_report_summary(original, "australia", target=45)
        self.assertIn("(전년 동기비 7%↑), 역대 최고 기록", result)
        self.assertEqual(s._brief_numeric_values(original), s._brief_numeric_values(result))
        self.assertTrue(s._valid_brief(result, "australia", original))

    def test_near_overflow_v15_statistic_keeps_all_periods_amounts_and_qualifiers(self):
        original = "호주 9개월 누적 쇠고기 수출 120만9000톤(전년 동기비 7% 증가)으로 역대 최고치 기록"
        result = s.compact_report_summary(original, "australia", target=40)
        self.assertEqual(result, "호주 9개월 누적 쇠고기 수출 120만 9000톤(전년 동기비 7%↑), 역대 최고 기록")
        self.assertTrue(40 <= len(result) <= 50, result)
        self.assertEqual(s._brief_numeric_values(result), s._brief_numeric_values(original))
        self.assertEqual(s._brief_qualifiers(result), s._brief_qualifiers(original))
        self.assertEqual(s._percent_directions(result), s._percent_directions(original))
        self.assertEqual(s.compact_report_summary(result, "australia", target=40), result)

    def test_near_overflow_brazil_keeps_pending_approval_and_positive_assessment(self):
        original = "브라질산 닭고기 EU 수출은 위생 평가 긍정적이나 재개에 남은 행정 절차 완료 필요"
        result = s.compact_report_summary(original, "brazil_chicken", target=40)
        self.assertEqual(result, "브라질 닭고기 EU 수출 위생 평가 긍정적이나 재개에 행정 절차 완료 필요")
        self.assertTrue(40 <= len(result) <= 45, result)
        self.assertTrue(s._valid_brief(result, "brazil_chicken", original))
        self.assertIn("긍정적이나", result)
        self.assertIn("행정 절차 완료 필요", result)
        self.assertNotIn("재개 확정", result)

    def test_known_temporal_contraction_is_not_loss_of_the_weather_cause(self):
        original = "폭염 이후 가축 성장률 회복으로 유럽산 돼지고기 공급 증가, 육류 가격지수 하락"
        result = s.compact_report_summary(original, "domestic_pork", target=40)
        self.assertEqual(result, original.replace("폭염 이후", "폭염 후"))
        self.assertTrue(40 <= len(result) <= 44, result)
        self.assertTrue(s._valid_brief(result, "domestic_pork", original))

    def test_short_spacing_defect_is_repaired_not_used_to_satisfy_minimum(self):
        original = "계란 전주비5% 하락,공급은 보통 수준"
        result = s.compact_report_summary(original, "us_egg")
        self.assertEqual(result, "계란 전주비 5% 하락, 공급은 보통 수준")
        self.assertLess(len(result), 40)
        self.assertFalse(s._valid_brief(result, "us_egg", original))

    def test_unknown_negation_and_pending_conditions_are_not_cut_or_padded(self):
        originals = (
            ("brazil_chicken", "브라질산 닭고기의 EU 수출 재개 가능성이 제기됐으나 실제 재개에는 추가 승인 절차 필요"),
            ("us", "미국 소고기 수입 확대를 검토하지 않는 가운데 공급 부족 가능성을 둘러싼 가격 상승 우려"),
            ("domestic_chicken", "CPTPP 가입 시 회원국산 닭고기 수입 증가가 국내 생산 감소로 이어질 가능성"),
        )
        for kind, original in originals:
            with self.subTest(kind=kind):
                result = s.compact_report_summary(original, kind, target=40)
                if kind == 'brazil_chicken':
                    self.assertEqual(s._brief_qualifiers(result), s._brief_qualifiers(original))
                    for caveat in ('재개 가능성', '실제 재개', '추가 승인 절차 필요'):
                        self.assertIn(caveat, result)
                    self.assertGreaterEqual(len(result), 40)
                else:
                    self.assertEqual(result, original)
        short = "계란 가격 하락"
        self.assertEqual(s.compact_report_summary(short, "us_egg"), short)

    def test_original_evidence_is_rechecked_before_accepting_compaction(self):
        original = "호주의 9개월 누적 쇠고기 수출량은 전년 동기비 7% 증가한 120만9000톤으로 역대 최고치를 기록"
        # The helper is not a source validator or a way to repair unsupported
        # facts: it must leave rejection to the normal publication gate.
        unrelated = "Australia beef exports fell 5% compared with last year."
        self.assertEqual(s.compact_report_summary(original, "australia", source=unrelated), s.normalize_report_spacing(original))
        self.assertFalse(s._valid_brief(original, "australia", unrelated))


if __name__ == "__main__":
    unittest.main()
