import unittest

from src.japan_egg_brief_facts import native_japan_egg_brief
from src.article_hwpx_layout import summary_reference_layout


BODY = """JA全農たまご 鶏卵相場（東京）
2026年10月20日(火) 09:00 発表
東 京 高値 基準値 安値 LL 334 310 ±0 303 L 340 315 ±0 309 M 345 320 +5 314 MS 365 340 +5 334 S 339 315 +5 308 SS 269 245 +5 238 特殊高値 ----- 336 +3 ----- 特殊安値 ----- 197 +3 ----- 市況 上伸 入荷量 740t
単位 円 / kg
"""


class JapanCurrentFactsTests(unittest.TestCase):
    def test_current_signed_price_and_market_tone_are_read_without_ai(self):
        summary, evidence = native_japan_egg_brief(BODY)
        self.assertIn("기준가 kg당 320엔", summary)
        self.assertIn("전일비 5엔 상승", summary)
        self.assertIn("입하량 740톤", summary)
        self.assertNotIn("345엔", summary)
        self.assertNotIn("340엔", summary)
        self.assertGreaterEqual(len(summary), 40)
        self.assertLessEqual(len(summary), 95)
        self.assertTrue(summary_reference_layout(summary, "japan_egg")["withinLineLimit"])
        self.assertIn("M 345 320 +5 314", evidence)
        self.assertIn("市況 上伸 入荷量 740t", evidence)
        self.assertIn("単位 円 / kg", evidence)

    def test_changed_numbers_negative_sign_and_units_remain_dynamic(self):
        body = BODY.replace("M 345 320 +5 314", "M 340 315 −2.5 309")
        body = body.replace("上伸", "下押し").replace("740t", "865.5t")
        summary, evidence = native_japan_egg_brief(body)
        self.assertIn("315엔", summary)
        self.assertIn("전일비 2.5엔 하락", summary)
        self.assertIn("입하량 865.5톤", summary)
        self.assertIn("市況 下押し", evidence)
        self.assertNotIn("320엔", summary)
        self.assertTrue(summary_reference_layout(summary, "japan_egg")["withinLineLimit"])

    def test_zero_does_not_invent_a_price_increase(self):
        for change in ("±0", "+0", "-0"):
            with self.subTest(change=change):
                summary, _ = native_japan_egg_brief(
                    BODY.replace("M 345 320 +5 314", f"M 345 320 {change} 314")
                    .replace("上伸", "保合"))
                self.assertIn("전일 수준 유지", summary)
                self.assertNotIn("5엔 상승", summary)

    def test_market_tone_is_not_inferred_from_individual_size_movement(self):
        summary, evidence = native_japan_egg_brief(BODY.replace("上伸", "保合"))
        self.assertIn("전일비 5엔 상승", summary)
        self.assertNotIn("시장 상승세", summary)
        self.assertIn("市況 保合", evidence)
        unknown, _ = native_japan_egg_brief(BODY.replace("上伸", "不明"))
        self.assertNotIn("시장 상승세", unknown)
        self.assertIn("전일비 5엔 상승", unknown)

    def test_another_size_or_region_cannot_supply_missing_tokyo_m_row(self):
        invalid = BODY.replace("M 345 320 +5 314 ", "")
        osaka = "大 阪 高値 基準値 安値 LL 320 300 ±0 290 M 355 330 +4 310 MS 350 325 +4 300 市況 上伸 入荷量 999t 単位 円 / kg"
        self.assertIsNone(native_japan_egg_brief(invalid + osaka))
        invalid_unit = BODY.replace("単位 円 / kg", "単位 不明")
        self.assertIsNone(native_japan_egg_brief(invalid_unit + osaka))

    def test_missing_units_invalid_dates_and_unverified_values_fail_closed(self):
        variants = (
            BODY.replace("円 / kg", "円 / 100g"),
            BODY.replace("2026年10月20日(火)", "2026年2月30日(火)"),
            BODY.replace("09:00 発表", "09:00 発表予定"),
            BODY.replace("09:00 発表", "09:00 発表なし"),
            BODY.replace("09:00 発表", "09:00 発表 中止"),
            BODY.replace("M 345 320 +5 314", "M 345 320 ±5 314"),
            BODY.replace("M 345 320 +5 314", "M 310 320 +5 314"),
            BODY.replace("M 345 320 +5 314", "M 345 320 +500 314"),
            BODY.replace("740t", "-740t"),
            BODY.replace("740t", "740kg"),
            BODY.replace("市況 上伸", "市況 上伸ではない"),
            BODY.replace("M 345 320 +5 314", "M 345 推定320 +5 314"),
        )
        for body in variants:
            with self.subTest(body=body):
                self.assertIsNone(native_japan_egg_brief(body))


if __name__ == "__main__":
    unittest.main()
