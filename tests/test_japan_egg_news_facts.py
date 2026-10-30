import unittest

from src.japan_egg_news_facts import native_japan_egg_news_brief


RETAIL = """名古屋市中区の生鮮食品館サノヤを取材しました。
卵の仕入れ価格は変動なし
●卵（M1パック）店頭価格301円（前週比±0円）
続いて卵の価格です。卵の店頭価格は前週から据え置きとなっています。
生鮮食品館サノヤ 百武さん：
「前週・前々週は例年の年末にかけての需要の高まりが徐々に始まっていましたが、
今は少し需要が落ち着いていますので、10月末頃まではこのぐらいの価格で
推移していくのではないかと思っています」"""

COSTS = (
    "タマゴの価格は今後、トリのエサ代や運送代などの値上げ、年末の需要期も重なるため、"
    "一時的に上昇する可能性があるということです。"
)


class JapanEggNewsFactsTests(unittest.TestCase):
    def assert_brief(self, source):
        result = native_japan_egg_news_brief(source)
        self.assertIsNotNone(result)
        summary, evidence = result
        self.assertGreaterEqual(len(summary), 40)
        self.assertLessEqual(len(summary), 95)
        self.assertNotIn("\n", summary)
        self.assertIn(evidence, source)
        return summary, evidence

    def test_retail_is_local_attributed_outlook_not_national_claim(self):
        summary, evidence = self.assert_brief(RETAIL)
        self.assertIn("나고야 소매점은", summary)
        self.assertIn("계란 수요 진정", summary)
        self.assertIn("10월 말까지 현 수준의 판매가격 유지 전망", summary)
        self.assertNotIn("일본", summary)
        self.assertNotIn("확정", summary)
        self.assertIn("名古屋市", evidence)

    def test_retail_month_comes_from_source_and_quote_units_are_omitted_together(self):
        summary, _ = self.assert_brief(RETAIL.replace("301円", "428円").replace("10月", "11月").replace("M1", "L1"))
        self.assertIn("11월 말", summary)
        self.assertNotIn("301", summary)
        self.assertNotIn("428", summary)
        self.assertNotIn("엔", summary)
        self.assertNotIn("규격", summary)
        self.assertNotIn("팩", summary)
        self.assertNotIn("10월", summary)

    def test_retail_no_country_or_city_is_invented(self):
        summary, _ = self.assert_brief(RETAIL.split("\n", 1)[1])
        self.assertTrue(summary.startswith("소매점 측은"))
        self.assertNotIn("나고야", summary)
        self.assertNotIn("전국", summary)

    def test_another_foods_demand_outlook_cannot_follow_the_egg_quote(self):
        price = '卵（M1パック）店頭価格301円（前週比±0円）。\n'
        outlook = ('生鮮食品館の店長さん：\n今は少し需要が落ち着いていますので、'
                   '10月末頃まではこのぐらいの価格で推移していくのではないかと思っています。')
        for food in ('新米', 'お米', 'サケ', 'カジカの卵', 'キャベツ', '牛乳', '豚肉'):
            with self.subTest(food=food):
                body = price + '続いて' + food + 'の価格です。\n' + outlook
                self.assertIsNone(native_japan_egg_news_brief(body))

    def test_disconnected_egg_sections_cannot_share_a_retail_outlook(self):
        body = ('卵（M1パック）店頭価格301円（前週比±0円）。\n'
                'コメの価格は5キロ2500円になりました。\n'
                '生鮮食品館の店長さん：\n'
                '今は少し需要が落ち着いていますので、10月末頃まではこのぐらいの価格で'
                '推移していくのではないかと思っています。')
        self.assertIsNone(native_japan_egg_news_brief(body))

    def test_cost_prediction_preserves_possibility(self):
        summary, evidence = self.assert_brief(COSTS)
        self.assertTrue(summary.endswith("상승 가능성"))
        self.assertIn("일시적", summary)
        self.assertIn("사료·운송비", summary)
        self.assertNotIn("315", summary)
        self.assertNotIn("도쿄", summary)
        self.assertEqual(evidence, COSTS[:-1])

    def test_retail_passes_digest_species_support_and_native_integration(self):
        from src.overseas_article_digest import _native_report_sentence, _valid_brief

        summary, _ = self.assert_brief(RETAIL)
        self.assertIn("계란", summary)
        self.assertTrue(_valid_brief(summary, "japan_egg", RETAIL))
        self.assertEqual(_native_report_sentence("japan_egg", RETAIL), summary)

    def test_retail_fits_one_line_for_each_supported_location_and_without_location(self):
        from src.article_hwpx_layout import summary_reference_layout
        from src.overseas_article_digest import _fit_report_summary

        cases = {
            "no_location": RETAIL.split("\n", 1)[1],
            "nagoya": RETAIL,
            "sapporo": RETAIL.replace("名古屋市中区", "札幌市"),
            "tokyo": RETAIL.replace("名古屋市中区", "東京都"),
            "hokkaido": RETAIL.replace("名古屋市中区", "北海道"),
        }
        for place, source in cases.items():
            with self.subTest(place=place):
                summary, _ = self.assert_brief(source)
                self.assertLessEqual(len(summary), 50)
                self.assertTrue(summary_reference_layout(summary, "japan_egg")["withinLineLimit"])
                self.assertIsNotNone(_fit_report_summary(summary, "japan_egg", source))

    def test_single_digit_month_remains_grounded_and_meets_minimum_without_padding(self):
        summary, _ = self.assert_brief(RETAIL.split("\n", 1)[1].replace("10月", "9月"))
        self.assertEqual(len(summary), 40)
        self.assertIn("9월 말", summary)

    def test_cost_outlook_passes_digest_without_becoming_a_certain_increase(self):
        from src.overseas_article_digest import _native_report_sentence, _valid_brief

        summary, _ = self.assert_brief(COSTS)
        self.assertTrue(_valid_brief(summary, "japan_egg", COSTS))
        self.assertEqual(_native_report_sentence("japan_egg", COSTS), summary)

    def test_evidence_keeps_fullwidth_digits_and_original_linebreaks(self):
        source = RETAIL.replace("M1", "Ｍ１").replace("301", "３０１").replace("10月", "１０月")
        summary, evidence = self.assert_brief(source)
        self.assertIn("10월 말", summary)
        self.assertIn("３０１円", evidence)
        self.assertIn("\n", evidence)
        self.assertIn("Ｍ１パック", evidence)

    def test_cost_frame_accepts_semantically_equivalent_explicit_costs(self):
        summary, _ = self.assert_brief(COSTS.replace("トリのエサ代や運送代", "飼料費や輸送費"))
        self.assertIn("사료·운송비", summary)

    def test_mixed_report_fish_and_rice_are_not_summary_evidence(self):
        mixed = "コメが値下がりしました。\nカジカの卵は安いです。\n" + ("本文。" * 40) + COSTS
        summary, evidence = self.assert_brief(mixed)
        self.assertNotIn("コメ", evidence)
        self.assertNotIn("カジカ", evidence)
        self.assertNotIn("쌀", summary)
        self.assertNotIn("어란", summary)

    def test_unsupported_inputs_fail_closed(self):
        for body in ("", None, "卵価格上昇", "JA全農たまご 東京 M 320円 入荷760t", "魚卵が値上がり"):
            with self.subTest(body=body):
                self.assertIsNone(native_japan_egg_news_brief(body))

    def test_retail_requires_correct_pack_unit_zero_change_and_retailer(self):
        for source in (
            RETAIL.replace("M1パック", "M1kg"),
            RETAIL.replace("前週比±0円", "前週比+4円"),
            RETAIL.replace("前週比±0円", "前月比±0円"),
            RETAIL.replace("生鮮食品館サノヤ 百武さん：", "担当者："),
            RETAIL.replace("301円", "0円"),
            RETAIL.replace("10月末", "13月末"),
        ):
            with self.subTest(source=source):
                self.assertIsNone(native_japan_egg_news_brief(source))

    def test_retail_does_not_change_negative_or_opposite_demand_into_calm(self):
        for source in (
            RETAIL.replace("需要が落ち着いていますので", "需要が落ち着いていないので"),
            RETAIL.replace("需要が落ち着いていますので", "需要が高まっていますので"),
            RETAIL.replace("思っています", "思っていません"),
            RETAIL + "という発言は事実ではないと訂正しました。",
        ):
            with self.subTest(source=source):
                self.assertIsNone(native_japan_egg_news_brief(source))

    def test_missing_cost_or_demand_fact_is_not_padded(self):
        for source in (
            COSTS.replace("トリのエサ代や", ""),
            COSTS.replace("や運送代", ""),
            COSTS.replace("年末の需要期も重なるため、", ""),
            COSTS.replace("一時的に", ""),
            COSTS.replace("可能性がある", "見通しである"),
            COSTS.replace("上昇する", "下落する"),
        ):
            with self.subTest(source=source):
                self.assertIsNone(native_japan_egg_news_brief(source))

    def test_negated_retracted_hypothetical_and_medical_frames_rejected(self):
        for source in (
            COSTS.replace("可能性がある", "可能性はない"),
            COSTS + "ということではない。",
            COSTS + "との報道は誤りでした。",
            "仮定の話として、" + COSTS,
            "ワクチンに使う卵について。" + COSTS,
            "受精卵について。" + COSTS,
            "魚卵について。" + COSTS,
        ):
            with self.subTest(source=source):
                self.assertIsNone(native_japan_egg_news_brief(source))

    def test_japanese_language_foreign_market_is_not_japanese_market(self):
        for country in ("米国", "中国", "ブラジル", "ドイツ", "オーストラリア", "台湾"):
            with self.subTest(country=country):
                self.assertIsNone(native_japan_egg_news_brief(country + "では、" + COSTS))
                self.assertIsNone(native_japan_egg_news_brief(RETAIL.replace("名古屋市中区の", country + "の")))

    def test_retail_outlook_cannot_be_joined_from_other_grocery_subsection(self):
        source = RETAIL.replace("生鮮食品館サノヤ 百武さん：", "次にキャベツの価格です。\n生鮮食品館サノヤ 百武さん：")
        self.assertIsNone(native_japan_egg_news_brief(source))


if __name__ == "__main__":
    unittest.main()
