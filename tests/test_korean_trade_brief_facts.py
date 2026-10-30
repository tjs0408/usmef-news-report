import unittest

from src.article_hwpx_layout import summary_reference_layout
from src.korean_trade_brief_facts import native_korean_trade_brief


EGG = ("최근 국정감사에서는 브라질산 계란 112만개를 들여오는 데 약 16억원이 투입돼 "
       "한 판(30개)당 수입단가가 약 4만4000원에 달했다는 지적이 나왔다.")
PORK = ("제주양돈농협은 싱가포르와 몽골 수출을 통해 제주산 돼지고기의 우수성을 "
        "해외시장에 알리고 수출시장에 다변화에 힘쓰고 있다 .")
BEEF = ("미국 사육 감소와 환율이 겹치며 수입 쇠고기도 올랐다. "
        "9월 수입 쇠고기 소비자물가는 7.2% 올라 국산(6.6%)보다 오히려 가파르다.")


class KoreanTradeBriefFactsTests(unittest.TestCase):
    def test_import_actual_and_weekly_plan_are_distinct_and_source_bound(self):
        from src import overseas_article_digest as digest
        body = ('올해 들어 지금까지 수입된 신선란은 약 1억800만개이며, '
                '추석 전까지는 매주 1000만개가량을 추가로 들여올 계획이다.')
        summary, evidence = native_korean_trade_brief('domestic_egg', body)
        self.assertEqual(summary, '올해 신선 계란 약 1억800만개 수입, 추석 전 매주 약 1000만개 추가 수입 계획')
        self.assertEqual(evidence, body)
        self.assertTrue(digest._valid_brief(summary, 'domestic_egg', body))
        self.assertTrue(summary_reference_layout(summary, 'domestic_egg')['withinLineLimit'])
        changed = body.replace('1억800만', '9500만').replace('1000만', '600만').replace('추석 전까지', '연말까지')
        revised, _ = native_korean_trade_brief('domestic_egg', changed)
        self.assertIn('9500만개', revised)
        self.assertIn('연말까지 매주 약 600만개', revised)
        self.assertNotIn('1억800만', revised)
        for bad in (body.replace('계획이다', '계획은 없다'), body.replace('신선란', '돼지고기'),
                    body.replace('개이며', '톤이며'),
                    body + ' 그러나 해당 수치는 오류로 정정했다.'):
            with self.subTest(body=bad):
                self.assertIsNone(native_korean_trade_brief('domestic_egg', bad))

    def test_egg_report_preserves_all_units_approximations_and_criticism(self):
        summary, evidence = native_korean_trade_brief("domestic_egg", EGG)
        self.assertEqual(summary, "국감서 브라질산 계란 112만개 수입에 약 16억원 투입·30개당 약 4만4000원 지적")
        self.assertIn("지적이 나왔다", evidence)
        self.assertGreaterEqual(len(summary), 40)
        self.assertTrue(summary_reference_layout(summary, "domestic_egg")["withinLineLimit"])

    def test_egg_values_country_and_package_are_dynamic_not_computed(self):
        changed = (EGG.replace("브라질", "태국").replace("112만", "85만")
                   .replace("16억", "9억").replace("30개", "20개").replace("4만4000", "2만8000"))
        summary, evidence = native_korean_trade_brief("domestic_egg", changed)
        for piece in ("태국산 계란 85만개", "약 9억원", "20개당 약 2만8000원", "지적"):
            self.assertIn(piece, summary)
        self.assertIn("20개", evidence)
        self.assertNotIn("112만", summary)

    def test_egg_no_approximation_is_added_when_not_reported(self):
        summary, _ = native_korean_trade_brief("domestic_egg", EGG.replace("약 ", ""))
        self.assertNotIn("약", summary)
        self.assertIn("16억원", summary)

    def test_egg_needs_one_complete_attributed_clause_with_matching_units(self):
        variants = (
            EGG.replace("국정감사에서는", "관련 통계에서는"),
            EGG.replace("지적이 나왔다", "집계가 나왔다"),
            EGG.replace("112만개", "112만톤"),
            EGG.replace("16억원", "16억달러"),
            EGG.replace("30개", "30kg"),
            EGG.replace("4만4000원", "4만4000달러"),
            EGG.replace("투입돼", "투입됐다. 한편"),
            EGG.replace("112만개", "-112만개"),
            EGG.replace("16억원", "0원"),
            EGG.replace("30개", "0개"),
        )
        for body in variants:
            with self.subTest(body=body):
                self.assertIsNone(native_korean_trade_brief("domestic_egg", body))

    def test_egg_denials_or_linked_corrections_are_not_omitted(self):
        for suffix in (" 그러나 해당 수치는 사실이 아니라고 정정했다.",
                       " 이 지적은 허위라는 반박이 나왔다."):
            with self.subTest(suffix=suffix):
                self.assertIsNone(native_korean_trade_brief("domestic_egg", EGG + suffix))
        self.assertIsNone(native_korean_trade_brief("domestic_egg", EGG.replace("나왔다", "나오지 않았다")))

    def test_export_destinations_origin_and_action_survive_compression(self):
        summary, evidence = native_korean_trade_brief("domestic_pork", PORK)
        self.assertEqual(summary, "제주양돈농협, 싱가포르·몽골에 제주산 돼지고기 수출하며 수출시장 다변화 추진")
        self.assertEqual(evidence, PORK)
        self.assertGreaterEqual(len(summary), 40)
        self.assertTrue(summary_reference_layout(summary, "domestic_pork")["withinLineLimit"])
        changed = PORK.replace("싱가포르와 몽골", "홍콩과 베트남").replace("제주산", "전남산")
        result, _ = native_korean_trade_brief("domestic_pork", changed)
        self.assertIn("홍콩·베트남", result)
        self.assertIn("전남산 돼지고기", result)

    def test_export_claim_does_not_borrow_subjects_from_adjacent_sentences(self):
        variants = (
            PORK.replace("돼지고기", "닭고기"),
            PORK.replace("싱가포르와 몽골", "싱가포르와 싱가포르"),
            PORK.replace("수출을 통해", "수출할 계획을 통해"),
            PORK.replace("통해 제주산", "통했다. 제주산"),
            PORK.replace("힘쓰고 있다", "힘쓰고 있지 않다"),
            "제주산 돼지고기 수출은 없다. " + PORK.replace("제주산 돼지고기", "닭고기"),
        )
        for body in variants:
            with self.subTest(body=body):
                self.assertIsNone(native_korean_trade_brief("domestic_pork", body))

    def test_kind_cannot_transfer_egg_or_pork_fact_to_other_species(self):
        self.assertIsNone(native_korean_trade_brief("domestic_pork", EGG))
        self.assertIsNone(native_korean_trade_brief("domestic_egg", PORK))
        self.assertIsNone(native_korean_trade_brief("domestic_chicken", EGG))

    def test_imported_beef_cause_comparison_and_month_are_preserved(self):
        summary, evidence = native_korean_trade_brief("domestic", BEEF)
        self.assertEqual(summary, "미국 사육 감소·환율로 수입 쇠고기값 상승, 9월 소비자물가 7.2% 올라 국산 6.6% 상회")
        self.assertEqual(evidence, BEEF)
        self.assertNotIn("전년", summary)
        self.assertNotIn("전월", summary)
        self.assertTrue(summary_reference_layout(summary, "domestic")["withinLineLimit"])
        changed = BEEF.replace("미국", "호주").replace("9월", "8월").replace("7.2", "8.4").replace("6.6", "5.5")
        alternative, _ = native_korean_trade_brief("domestic", changed)
        for value in ("호주 사육 감소", "8월", "8.4%", "5.5%"):
            self.assertIn(value, alternative)

    def test_beef_native_can_read_the_relevant_late_paragraph(self):
        text = "한우 국내 판매량과 마블링 조사에 관한 설명이다. " * 200 + BEEF
        summary, evidence = native_korean_trade_brief("domestic", text)
        self.assertIn("수입 쇠고기", summary)
        self.assertEqual(evidence, BEEF)

    def test_beef_cause_and_comparator_are_not_borrowed_or_invented(self):
        variants = (
            BEEF.replace("사육 감소와 환율", "사육 감소"),
            BEEF.replace("미국 사육", "미국 돼지 사육"),
            BEEF.replace("7.2%", "-7.2%"),
            BEEF.replace("7.2%", "5.2%"),
            BEEF.replace("국산(6.6%)", "국산(7.2%)"),
            BEEF.replace("9월", "13월"),
            BEEF.replace("쇠고기도 올랐다", "쇠고기는 오르지 않았다"),
            BEEF.replace("올랐다. ", "올랐다는 추정이다. "),
            BEEF.replace("9월 수입 쇠고기", "9월 국산 쇠고기"),
            BEEF.replace("7.2% 올라", "7.2원 올라"),
            BEEF.replace("국산(6.6%)", "국산(6.6원)"),
            BEEF.replace("올랐다. ", "올랐다. 다른 국가의 사례다. "),
            BEEF + " 해당 수치는 잘못된 것으로 정정했다.",
        )
        for body in variants:
            with self.subTest(body=body):
                self.assertIsNone(native_korean_trade_brief("domestic", body))


if __name__ == "__main__":
    unittest.main()
