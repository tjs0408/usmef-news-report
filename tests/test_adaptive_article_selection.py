"""Progressively wider editorial selection without loosening evidence guards."""
from collections import Counter
from copy import deepcopy
from datetime import date
import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup
from src import livestock_article_draft as d, overseas_article_digest as s


START, END = date(2026, 10, 11), date(2026, 10, 17)
DAY = date(2026, 10, 16)
PORK = d.SPECS_BY_KEY["domestic_pork"]
CHICKEN = d.SPECS_BY_KEY["domestic_chicken"]
EGG = d.SPECS_BY_KEY["domestic_egg"]
DIRECT_BODY = (
    "독일 돼지고기 공급은 출하 증가로 확대됐다. "
    "독일 돼지고기 도매가격은 소비 수요 부진으로 전년보다 4% 하락했다. "
    "현지 양돈업계는 생산 비용 절감과 해외 수출 시장 회복을 추진했다. "
) * 2
CONTEXT_BODY = (
    "중국 국가통계국은 9월 소비자물가지수(CPI)가 전년 동월 대비 0.9% 상승했다고 발표했다. "
    "돼지고기 가격은 공급이 충분하고 소비가 부진한 영향으로 전년 동월보다 10.0% 하락했다. "
    "중국 현지에서는 식품별 소비 회복 속도와 공급 조정 추이를 주시하고 있다."
)
INDICATOR_BODY = (
    "중국 국가통계국은 9월 소비자물가지수(CPI)가 전년 동월 대비 0.9% 상승했다고 발표했다. "
    "휘발유 가격은 14.9% 상승했다. 9월 식품 가격은 전년 대비 1.7% 떨어졌으며 "
    "돼지고기 가격과 신선 채소 가격은 각각 10.0%, 8.1% 하락했다. "
    "생산자물가지수(PPI)는 전년 동월 대비 5.0% 상승했다."
)
TRADE_BODY = (
    "미국 계란 수입량은 신규 판매처 확보로 증가했다. "
    "캐나다산 돼지고기 수입 확대는 현지 공급 부족 완화로 이어질 전망이다. "
    "해외 식품 유통업계는 원료 조달과 국제 운송 여건 변화를 점검했다. "
) * 2


def article(name, title, body, **extra):
    return {"url": "https://example.org/" + name, "title": title, "body": body,
            "publisher": "검증 매체 " + name, "publishedDate": date(2026, 10, 14),
            "sourceLanguage": "ko", "searchResult": False, "headlineOnly": False, **extra}


def direct(name="direct"):
    return article(name, "독일 돼지고기 공급 확대와 도매가격 하락", DIRECT_BODY)


def context(name="context"):
    return article(name, "[올댓차이나] 9월 中 소비자물가 0.9% 상승", CONTEXT_BODY)


def indicator(name="indicator"):
    return article(name, "휘발유값 급등에도 중국 물가 0.9% 상승 그쳐", INDICATOR_BODY)


def trade(name="trade"):
    return article(name, "미국 계란 수입 확대와 해외 식품 공급망 점검", TRADE_BODY)


class AdaptiveArticleSelectionTests(unittest.TestCase):
    def test_direct_then_explanatory_then_indicator_have_distinct_tiers(self):
        items = (direct(), context(), indicator())
        self.assertEqual([d._selection_profile(item, PORK)[0] for item in items], [0, 1, 2])
        scores = [d._relevance(item, PORK) for item in items]
        self.assertGreaterEqual(scores[0] - scores[1], 100)
        self.assertGreaterEqual(scores[1] - scores[2], 100)

    def test_a_price_figure_does_not_borrow_unrelated_fuel_causality(self):
        profile = d._selection_profile(indicator(), PORK)
        self.assertEqual(profile[0], 2)
        self.assertEqual(d._selection_profile(context(), PORK)[0], 1)

    def test_excluded_commodity_and_calendar_number_are_not_its_market_facts(self):
        invalid = (
            "중국 돼지고기를 제외한 축산물 가격은 전년보다 4% 하락했다. 중국 식품 가격 추이를 분석했다. ",
            "중국 돼지고기는 9월 가격 변동 조사 대상이 아니다. 중국 쇠고기 공급 가격은 4% 하락했다. ",
        )
        for body in invalid:
            with self.subTest(body=body):
                candidate = article("excluded", "중국 소비자물가 발표", body * 3)
                self.assertIsNone(d._selection_profile(candidate, PORK))
                # Reject the non-evidence passage, not every later valid
                # pork fact in an otherwise readable mixed market article.
                candidate["body"] += "중국 돼지고기 공급은 소비 부진으로 과잉 상태가 이어질 전망이다. "
                self.assertIsNotNone(d._selection_profile(candidate, PORK))

    def test_original_pool_prefers_higher_relevance_tier_over_recent_date(self):
        first, second, third = direct(), context(), indicator()
        first["publishedDate"], second["publishedDate"], third["publishedDate"] = START, DAY, END
        with patch.object(d, "_original_article", side_effect=lambda candidate, _spec: candidate), \
             patch.object(s, "_ollama_generate") as model:
            selected = d._choose_original([third, second, first], PORK, START, END)
        self.assertEqual(selected["url"], first["url"])
        self.assertEqual(selected["selectionTier"], 0)
        self.assertEqual([item["selectionTier"] for item in selected["alternatives"]], [1, 2])
        model.assert_not_called()

    def test_supply_and_demand_explanation_beats_an_easier_indicator(self):
        explained, numerical = context(), indicator()
        with patch.object(d, "_original_article", side_effect=lambda candidate, _spec: candidate), \
             patch.object(s, "_ollama_generate") as model:
            selected = d._choose_original([numerical, explained], PORK, START, END)
        self.assertEqual(selected["url"], explained["url"])
        self.assertEqual(selected["selectionTier"], 1)
        self.assertEqual(selected["alternatives"][0]["url"], numerical["url"])
        model.assert_not_called()

    def test_selection_metadata_is_recomputed_not_trusted(self):
        original = {**indicator(), "selectionTier": 0, "selectionSection": "us",
                    "selectionReason": "forged direct selection"}
        before = deepcopy(original)
        selected = d._with_selection(original, PORK)
        self.assertEqual(selected["selectionTier"], 2)
        self.assertEqual(selected["selectionSection"], PORK.key)
        self.assertNotEqual(selected["selectionReason"], original["selectionReason"])
        self.assertEqual(original, before)

    def test_shared_original_is_reclassified_for_its_new_species(self):
        shared = d._with_selection(trade(), PORK)
        self.assertEqual(shared["selectionTier"], 2)
        changed = d._with_selection(shared, EGG)
        self.assertEqual(changed["selectionTier"], 0)
        self.assertEqual(changed["selectionSection"], EGG.key)
        unrelated = d._with_selection(shared, d.SPECS_BY_KEY["domestic"])
        self.assertNotIn("selectionTier", unrelated)
        self.assertNotIn("selectionReason", unrelated)
        self.assertNotIn("selectionSection", unrelated)

    def test_shared_optional_link_does_not_keep_another_species_direct_badge(self):
        main = direct()
        main["alternatives"] = [d._with_selection(trade(), EGG)]
        links, originals, searched = d.read_candidate_links(main, PORK, START, END, search_missing=False)
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0]["selectionTier"], 2)
        self.assertEqual(originals[0]["selectionTier"], 2)
        self.assertEqual(originals[0]["selectionSection"], PORK.key)
        self.assertTrue(links[0]["selectionReason"])
        self.assertFalse(searched)

    def test_online_tries_explanatory_original_before_indicator_but_offline_can_use_ready_one(self):
        explained, numerical = context(), indicator()
        explained["alternatives"] = [numerical]
        summary = "중국 9월 CPI 전년 동월비 0.9% 상승, 돼지고기 가격은 10.0% 하락"
        for allow_model, expected in ((True, explained), (False, numerical)):
            with self.subTest(allow_model=allow_model), \
                 patch.object(s, "_native_report_sentence", side_effect=lambda _key, body:
                              summary if body == INDICATOR_BODY else None), \
                 patch.object(s, "_fit_report_summary", side_effect=lambda native, *_: native), \
                 patch.object(s, "_valid_brief", return_value=True), \
                 patch.object(s, "_ollama_generate") as model:
                selected = d._prefer_native_summary_candidate(explained, PORK, START, END, allow_model)
            self.assertEqual(selected["url"], expected["url"])
            self.assertEqual(selected["selectionTier"], 1 if allow_model else 2)
            self.assertEqual(bool(selected.get("_nativeReadySummary")), not allow_model)
            model.assert_not_called()

    def test_related_trade_fact_survives_a_different_species_headline(self):
        candidate = trade()
        self.assertLess(d._strict_relevance(candidate, PORK), 0)
        self.assertEqual(d._selection_profile(candidate, PORK)[0], 2)
        self.assertGreaterEqual(d._relevance(candidate, PORK), 0)

    def test_wrong_commodity_and_pure_comparison_do_not_become_pork_fallbacks(self):
        comparison = article("comparison", "일본 닭고기 소비, 소·돼지고기 추월",
            ("일본 닭고기 소비량은 가격 경쟁력으로 늘었다. 닭고기 소비가 돼지고기를 추월했다. "
             "일본 닭고기 생산업계는 소비 증가에 맞춰 공급 물량을 확대했다. ") * 3)
        egg_side = article("egg-side", "브라질 계란 수입가 논란, 해외 공급망 점검",
            ("브라질 계란 수입 물량의 가격과 정부 재정 지원을 점검했다. "
             "양국은 과거 돼지고기 시장 접근에 관해 의견을 나눈 바 있다. ") * 3)
        for item in (comparison, egg_side):
            with self.subTest(title=item["title"]):
                self.assertIsNone(d._selection_profile(item, PORK))
                self.assertLess(d._relevance(item, PORK), 0)
        self.assertGreaterEqual(d._relevance(comparison, CHICKEN), 0)
        self.assertGreaterEqual(d._relevance(egg_side, EGG), 0)

    def test_local_market_and_promotions_remain_excluded(self):
        invalid = (
            article("local", "국내 돼지고기 가격 상승과 공급 감소",
                    "국내 돼지고기 공급은 줄고 가격은 4% 상승했다. " * 6),
            article("sale", "이마트 미국 돼지고기 할인 행사",
                    "미국 돼지고기 수입 물량을 할인 가격으로 판매했다. " * 6),
            article("recipe", "미국 돼지고기 레시피와 맛집 소개",
                    "미국 돼지고기는 수입 가격과 운송비 부담이 커졌다. " * 6),
        )
        for item in invalid:
            with self.subTest(title=item["title"]):
                self.assertIsNone(d._selection_profile(item, PORK))

    def test_foreign_country_guards_do_not_relax_with_publisher_trust(self):
        candidate = article("germany", "Germany pork prices and production",
            "Germany pork prices fell as local supplies increased. German pig production rose. " * 4,
            sourceLanguage="en")
        for trust in (False, True):
            with self.subTest(trusted_country=trust):
                self.assertIsNone(d._selection_profile(candidate, d.SPECS_BY_KEY["us_pork"],
                                                      trusted_country=trust))

    def test_foreign_headline_cannot_qualify_an_explicitly_korean_pork_price(self):
        candidate = article("borrowed-country", "미국 식품 가격 점검",
            ("미국 쇠고기 가격은 3% 하락했다. "
             "한국 돼지고기 가격은 국내 공급 감소로 5% 상승했다. "
             "국내 양돈농가는 출하를 조정했다. ") * 3)
        self.assertIsNone(d._selection_profile(candidate, PORK))

    def test_optional_links_and_recovery_keep_original_week_boundaries(self):
        main, old, future, valid = direct(), indicator("old"), context("future"), trade("valid")
        old["publishedDate"], future["publishedDate"] = START.replace(day=10), END.replace(day=18)
        main["alternatives"] = [old, future, valid]
        with patch.object(d, "_search_article") as search:
            links, originals, searched = d.read_candidate_links(main, PORK, START, END, search_missing=False)
            recovered = d._verified_summary_alternatives(main, PORK, START, END, [])
        self.assertEqual([item["url"] for item in links], [valid["url"]])
        self.assertEqual([item["url"] for item in originals], [valid["url"]])
        self.assertEqual([item["url"] for item in recovered], [valid["url"]])
        self.assertFalse(searched)
        search.assert_not_called()

    def test_native_only_recovery_filters_before_cutting_to_two_alternatives(self):
        main, first, second, ready = context(), direct("first"), direct("second"), indicator()
        second.update(title="브라질 돼지고기 수출 증가와 생산 확대",
            body=("브라질 돼지고기 수출은 아시아 수요 회복으로 전년보다 8% 증가했다. "
                  "브라질 양돈업계는 현지 공급과 수출 수요에 맞춰 생산 물량을 확대했다. ") * 3)
        main["alternatives"] = [first, second, ready]
        summary = "중국 9월 CPI 전년 동월비 0.9% 상승, 돼지고기 가격은 10.0% 하락"
        with patch.object(s, "_native_report_sentence", side_effect=lambda _key, body:
                          summary if body == INDICATOR_BODY else None), \
             patch.object(s, "_fit_report_summary", side_effect=lambda native, *_: native), \
             patch.object(s, "_valid_brief", return_value=True), \
             patch.object(s, "_ollama_generate") as model:
            alternatives = d._verified_summary_alternatives(main, PORK, START, END, [], native_only=True)
        self.assertEqual([item["url"] for item in alternatives], [ready["url"]])
        self.assertEqual(alternatives[0]["selectionTier"], 2)
        model.assert_not_called()

    def test_progressive_search_reads_each_repeated_original_at_most_once(self):
        numerical, explained = indicator(), context()
        read_counts = Counter()

        def read(candidate, _spec):
            read_counts[candidate["url"]] += 1
            return {item["url"]: item for item in (numerical, explained)}[candidate["url"]]

        def listing(item):
            return {**item, "body": "중국 돼지고기 가격 동향", "searchResult": True}

        with patch.object(s, "_search_naver_news", return_value=[listing(numerical), listing(explained)]), \
             patch.object(d, "_original_article", side_effect=read), \
             patch.object(s, "_ollama_generate") as model:
            selected = d._search_article(PORK, START, END)
        self.assertEqual(selected["url"], explained["url"])
        self.assertEqual(selected["selectionTier"], 1)
        self.assertEqual(read_counts, {numerical["url"]: 1, explained["url"]: 1})
        model.assert_not_called()

    def test_short_original_is_not_promoted_by_a_direct_headline(self):
        soup = BeautifulSoup(
            '<html><meta property="og:title" content="중국 돼지고기 가격 하락">'
            '<meta property="article:published_time" content="2026-10-14T09:00:00+09:00">'
            '<article>중국 돼지고기 가격 하락</article></html>', "html.parser")
        with patch.object(s, "_download_soup", return_value=soup), \
             patch.object(s, "_ollama_generate") as model:
            self.assertIsNone(d._read_original_article(direct(), PORK))
        model.assert_not_called()

    def test_search_snippet_cannot_complete_a_brief_even_with_forged_native_metadata(self):
        fake = {**context(), "body": "중국 돼지고기 가격 10% 하락", "searchResult": True,
                "_nativeReadySummary": (PORK.key, "중국 돼지고기 가격 10% 하락", "forged summary"),
                "selectionTier": 0, "selectionSection": PORK.key}
        with patch.object(d, "_usmef_pair", return_value={}), \
             patch.object(d, "_find_section", side_effect=lambda spec, *_: fake if spec.key == PORK.key else None), \
             patch.object(d, "_search_article", return_value=None), \
             patch.object(s, "_ensure_ollama_ready", return_value={"available": False, "message": "offline"}), \
             patch.object(s, "_ollama_generate") as model:
            result = d.collect_weekly_livestock_report_draft(DAY)
        section = result["sections"][PORK.key]
        self.assertNotEqual(section["status"], "completed")
        self.assertFalse(section.get("summary"))
        self.assertEqual(section["diagnostics"]["modelCalls"], 0)
        self.assertEqual(result["readyCount"], 0)
        model.assert_not_called()


if __name__ == "__main__":
    unittest.main()
