"""Local Japanese egg stories, not incidental fish/rice or medical prose."""
import unittest

from src.market_issue_selection import issue_queries, market_issue_profile, market_issue_rank
from src.report_editorial_selection import (
    editorial_selection_profile, japanese_egg_editorial_passages,
)


class JapaneseEggIssueRankingTests(unittest.TestCase):
    def test_three_queries_cover_local_report_spellings_without_extra_requests(self):
        queries = issue_queries("japan_egg")
        self.assertEqual(len(queries), 3)
        self.assertIn("日本", queries[0])
        self.assertIn("卵", queries[0])
        self.assertIn("タマゴ", queries[1])
        self.assertIn("たまご", queries[2])
        self.assertTrue(any("日本" not in query for query in queries))
        self.assertTrue(all("site:" not in query and "2026" not in query for query in queries))

    def test_nagoya_store_demand_explanation_beats_daily_ja_quote(self):
        source = (
            "新米の販売価格は５キロ２５００円を切る水準で下落しています。\n"
            "卵の仕入れ価格は変動なし\n"
            "卵（M１パック）店頭価格３０１円（前週比±０円）\n"
            "続いて卵の価格です。卵の店頭価格は前週から据え置きとなっています。\n"
            "生鮮食品館サノヤ 百武さん：\n"
            "「今は少し需要が落ち着いていますので、１０月末頃まではこのぐらいの価格で"
            "推移していくのではないかと思っています」"
        )
        profile = market_issue_profile("japan_egg", "新米値下がり、卵も紹介", source)
        daily = "鶏卵相場はＭ基準値３１５円で前日比横ばい。"
        self.assertEqual(profile["level"], 3)
        self.assertEqual(profile["pattern"], "linked_market_change")
        self.assertIn("需要が落ち着", profile["evidence"])
        self.assertIn("百武さん", profile["evidence"])
        self.assertNotIn("新米", profile["evidence"])
        self.assertNotIn("２５００", profile["evidence"])
        self.assertGreater(market_issue_rank("japan_egg", "", source),
                           market_issue_rank("japan_egg", "", daily))
        self.assertEqual(editorial_selection_profile("japan_egg", "", source)["bonus"], 8)

    def test_hokkaido_report_uses_chicken_egg_costs_not_fish_roe(self):
        source = (
            "カジカの卵の価格は安く、サケは平年より１割高くなっています。\n"
            "農林水産省が発表した１パック１０個入りのタマゴの価格は３０９円で、"
            "前の月と比べて４円高くなりました。\n"
            "これは平年と比べて１９％高い価格となっています。\n"
            "タマゴの価格は今後、トリのエサ代や運送代などの値上げ、"
            "年末の需要期も重なるため、一時的に上昇する可能性があるということです。"
        )
        profile = market_issue_profile("japan_egg", "旬の魚とタマゴの値上げ", source)
        self.assertEqual(profile["level"], 3)
        self.assertIn("cost_risk_policy", profile["themes"])
        self.assertIn("エサ代", profile["evidence"])
        self.assertIn("可能性", profile["evidence"])
        self.assertNotIn("サケ", profile["evidence"])
        self.assertNotIn("カジカ", profile["evidence"])

    def test_bare_egg_spellings_only_gain_for_food_market_passages(self):
        for spelling in ("卵", "タマゴ", "たまご"):
            with self.subTest(spelling=spelling):
                source = f"{spelling}の店頭価格は需要増により値上がりしています。"
                self.assertEqual(market_issue_profile("japan_egg", "", source)["level"], 3)
                self.assertTrue(japanese_egg_editorial_passages("", source))
        for source in (
            "卵の形は丸くて白い。",
            "カジカの卵は需要増により価格が上昇しました。",
            "サケの卵は品薄の影響で価格が上昇しました。",
            "魚卵の供給不足によりイクラの価格は上昇しました。",
            "卵を使ったワクチンの価格が需要増により上昇しました。",
            "卵子の細胞培養技術が進み、臨床需要が上昇しました。",
        ):
            with self.subTest(source=source):
                self.assertEqual(market_issue_rank("japan_egg", "鶏卵の市場", source), (0, 0, 0))

    def test_rice_cause_cannot_be_borrowed_before_or_after_an_egg_quote(self):
        for source in (
            "新米は需要増により価格が上昇し、卵の店頭価格は３０１円で据え置き。",
            "卵の店頭価格は３０１円で据え置き、新米は需要増により価格が上昇しました。",
            "新米は需要増により価格が上昇しました。卵の店頭価格は３０１円で据え置き。",
            "卵の店頭価格は３０１円で据え置き。新米は需要増により価格が上昇しました。",
        ):
            with self.subTest(source=source):
                profile = market_issue_profile("japan_egg", "食品価格", source)
                self.assertLess(profile["level"], 3)
                self.assertNotIn("需要", profile["evidence"])
                self.assertNotIn("新米", profile["evidence"])

    def test_fish_topic_ends_an_egg_block_before_another_cause(self):
        source = (
            "卵の店頭価格は３０１円で据え置きです。\n"
            "サケの供給は不足しています。\n"
            "価格は需要増の影響で値上がりする可能性があります。"
        )
        profile = market_issue_profile("japan_egg", "食品価格", source)
        self.assertLess(profile["level"], 3)
        self.assertNotIn("供給", profile["evidence"])
        self.assertNotIn("影響", profile["evidence"])

    def test_parenthetical_store_attribution_stays_with_egg_price_quote(self):
        source = (
            "タマゴの価格は３０９円となっています。\n"
            "（北海市場屯田店 平泉友也さん）\n"
            "「この高止まりは鳥インフルの影響による供給不足が考えられます」"
        )
        profile = market_issue_profile("japan_egg", "", source)
        self.assertEqual(profile["level"], 3)
        self.assertIn("平泉友也さん", profile["evidence"])
        self.assertIn("考えられます", profile["evidence"])

    def test_explicit_chicken_egg_in_mixed_list_keeps_its_own_predicate(self):
        profile = market_issue_profile("japan_egg", "", "サケと鶏卵の店頭価格が上昇しました。")
        self.assertEqual(profile["level"], 2)
        self.assertNotIn("サケ", profile["evidence"])

    def test_cause_beyond_evidence_limit_does_not_raise_rank(self):
        source = "卵の店頭価格は３０１円で据え置き。" + "説明が続きます" * 100 + "需要増の影響で値上げ。"
        profile = market_issue_profile("japan_egg", "", source)
        self.assertLess(profile["level"], 3)
        self.assertNotIn("影響", profile["evidence"])

    def test_headline_and_other_species_cannot_supply_egg_themes(self):
        self.assertEqual(market_issue_rank("japan_egg", "卵需要増で値上げ", "新米の店頭価格が上昇。"),
                         (0, 0, 0))
        profile = market_issue_profile("japan_egg", "", "鶏肉は需要増で値上げ、卵の価格は据え置き。")
        self.assertLess(profile["level"], 3)
        self.assertNotIn("需要増", profile["evidence"])

    def test_bare_japanese_egg_path_does_not_broaden_other_foreign_sections(self):
        source = "卵の店頭価格は需要増の影響で上昇しました。"
        self.assertEqual(market_issue_rank("us_egg", "", source), (0, 0, 0))
        self.assertNotIn("country", market_issue_profile("japan_egg", "", source))

    def test_already_grounded_korean_brief_keeps_its_market_context(self):
        brief = "나고야 소매점은 계란 수요 진정에 10월 말까지 현 수준의 판매가격 유지 전망"
        self.assertGreaterEqual(market_issue_profile("japan_egg", "", brief)["level"], 2)
        self.assertGreater(editorial_selection_profile("japan_egg", "", brief)["bonus"], 0)
        self.assertEqual(market_issue_profile("japan_egg", "", brief)["evidence"], brief)

    def test_non_japanese_species_matching_is_not_removed_for_japan_section(self):
        brief = "Japanese egg retail prices rose due to lower supply and growing demand."
        self.assertEqual(market_issue_profile("japan_egg", "", brief)["level"], 3)


if __name__ == "__main__":
    unittest.main()
