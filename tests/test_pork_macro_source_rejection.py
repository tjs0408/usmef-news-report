"""CPI headlines use original-body relevance, not a title blacklist."""
from datetime import date
import unittest
from unittest.mock import patch

from src import livestock_article_draft as d, overseas_article_digest as s


START, END = date(2026, 10, 11), date(2026, 10, 17)
DAY = date(2026, 10, 16)
SPEC = d.SPECS_BY_KEY["domestic_pork"]
MACRO_BODY = (
    "중국 국가통계국은 9월 소비자물가지수(CPI)가 전년 동월 대비 0.9% 상승했다고 발표했다. "
    "휘발유 가격은 14.9% 상승했다. 9월 식품 가격은 전년 대비 1.7% 떨어졌으며 "
    "돼지고기 가격과 신선 채소 가격은 각각 10.0%, 8.1% 하락했다. "
    "생산자물가지수(PPI)는 전년 동월 대비 5.0% 상승했다."
)
PORK_BODY = (
    "독일 돼지고기 공급은 출하 증가로 확대됐다. "
    "독일 돼지고기 도매가격은 소비 수요 부진으로 하락했다. "
    "현지 돼지고기 가공업계는 생산 비용 절감과 해외 수출 시장 회복을 추진했다. "
) * 2
CONTEXT_BODY = (
    "중국 국가통계국은 9월 소비자물가지수(CPI)가 전년 동월 대비 0.9% 상승했다고 발표했다. "
    "돼지고기 가격은 공급이 충분하고 소비가 부진한 영향으로 전년 동월보다 10.0% 하락했다. "
    "중국 현지에서는 식품별 소비 회복 속도와 공급 조정 추이를 주시하고 있다."
)
MACRO_SUMMARY = "중국 9월 CPI 전년 동월비 0.9% 상승, 돼지고기 가격은 10.0% 하락"


def article(name, title, body=MACRO_BODY, **changes):
    return {"url": "https://example.org/" + name, "title": title,
            "publisher": "검증 매체 " + name, "publishedDate": date(2026, 10, 14),
            "sourceLanguage": "ko", "body": body, **changes}


def macro(name="macro"):
    return article(name, "휘발유값 급등에도 중국 물가 0.9% 상승 그쳐")


def pork(name="pork"):
    return article(name, "독일 돼지고기 공급 증가와 도매가격 동향", PORK_BODY)


class PorkMacroBodySelectionTests(unittest.TestCase):
    def test_macro_title_with_an_independent_pork_price_is_a_low_priority_fallback(self):
        for title in (
            "휘발유값 급등에도 중국 물가 0.9% 상승 그쳐",
            "중국 소비자물가 발표, 식품별 가격 차별화",
            "중국 CPI 상승 제한…돼지고기는 10% 하락",
            "중국 생산자물가 PPI 상승과 돼지고기 가격 하락",
            "국제유가 상승에도 중국 돼지고기 가격 안정",
        ):
            with self.subTest(title=title):
                candidate = article("indicator", title)
                profile = d._selection_profile(candidate, SPEC)
                self.assertIsNotNone(profile)
                self.assertEqual(profile[0], 2)
                self.assertGreaterEqual(d._relevance(candidate, SPEC), 0)

    def test_pork_headline_is_still_the_direct_market_tier(self):
        candidate = pork()
        self.assertEqual(d._domestic_pork_focus(candidate), 2)
        self.assertEqual(d._selection_profile(candidate, SPEC)[0], 0)
        self.assertGreater(d._relevance(candidate, SPEC), d._relevance(macro(), SPEC))

    def test_macro_listing_must_be_downloaded_before_judging_its_body(self):
        original = article("context", "[올댓차이나] 9월 中 소비자물가 0.9% 상승", CONTEXT_BODY)
        candidate = {**original, "body": "중국 돼지고기 등 식품 가격 동향", "searchResult": True}
        diagnostics, attempted = {}, set()
        with patch.object(d, "_original_article", return_value=original) as read, \
             patch.object(s, "_ollama_generate") as model:
            selected = d._choose_original([candidate], SPEC, START, END,
                                          diagnostics=diagnostics, attempted_urls=attempted)
        self.assertEqual(selected["url"], original["url"])
        self.assertEqual(selected["selectionTier"], 1)
        self.assertEqual(diagnostics.get("originalsChecked"), 1)
        self.assertEqual(attempted, {original["url"]})
        read.assert_called_once()
        model.assert_not_called()

    def test_original_and_optional_links_accept_valid_cpi_as_fallback_not_as_priority(self):
        main, fallback = pork(), macro()
        main["alternatives"] = [fallback]
        with patch.object(d, "_original_article", side_effect=lambda candidate, _spec: candidate), \
             patch.object(s, "_ollama_generate") as model:
            selected = d._choose_original([fallback, main], SPEC, START, END)
        self.assertEqual(selected["url"], main["url"])
        self.assertEqual(selected["selectionTier"], 0)
        with patch.object(d, "_search_article") as search:
            links, originals, searched = d.read_candidate_links(main, SPEC, START, END, search_missing=False)
        self.assertEqual([item["url"] for item in links], [fallback["url"]])
        self.assertEqual([item["url"] for item in originals], [fallback["url"]])
        self.assertFalse(searched)
        search.assert_not_called()
        model.assert_not_called()

    def test_online_native_readiness_does_not_promote_indicator_above_a_direct_primary(self):
        main, fallback = pork(), macro()
        main["alternatives"] = [fallback]
        with patch.object(s, "_native_report_sentence", side_effect=lambda _key, body:
                          MACRO_SUMMARY if body == MACRO_BODY else None), \
             patch.object(s, "_fit_report_summary", side_effect=lambda native, *_args: native), \
             patch.object(s, "_valid_brief", return_value=True), \
             patch.object(s, "_ollama_generate") as model, \
             patch.object(d, "_search_article") as search:
            selected = d._prefer_native_summary_candidate(main, SPEC, START, END, True)
        self.assertEqual(selected["url"], main["url"])
        self.assertEqual(selected["selectionTier"], 0)
        self.assertNotIn("_nativeReadySummary", selected)
        search.assert_not_called()
        model.assert_not_called()

    def test_recovery_prefers_direct_but_keeps_dated_indicator_available(self):
        main, fallback, direct = pork(), macro(), pork("another")
        direct["title"] = "미국 돈육 수출 회복과 생산량 증가"
        direct["body"] = ("미국 돈육 수출량은 아시아 수요 회복으로 전년보다 8% 증가했다. "
                          "현지 양돈농가는 돼지고기 생산 확대에 맞춰 출하 시기를 조정했다. ") * 2
        main["alternatives"] = [fallback]
        for prefer_focus in (True, False):
            with self.subTest(prefer_focus=prefer_focus), patch.object(s, "_ollama_generate") as model:
                alternatives = d._verified_summary_alternatives(main, SPEC, START, END,
                    [fallback, direct], prefer_pork_focus=prefer_focus)
            self.assertEqual([item["url"] for item in alternatives], [direct["url"], fallback["url"]])
            self.assertEqual([item["selectionTier"] for item in alternatives], [0, 2])
            model.assert_not_called()

    def test_offline_collector_can_complete_a_verified_native_cpi_fallback(self):
        fallback = macro()
        with patch.object(d, "_usmef_pair", return_value={}), \
             patch.object(d, "_find_section", side_effect=lambda spec, *_:
                          fallback if spec.key == SPEC.key else None), \
             patch.object(d, "_search_article", return_value=None), \
             patch.object(s, "_ensure_ollama_ready", return_value={"available": False, "message": "offline"}), \
             patch.object(s, "_summarize_report_sentence") as summarize, \
             patch.object(s, "_ollama_generate") as model:
            result = d.collect_weekly_livestock_report_draft(DAY)
        section = result["sections"][SPEC.key]
        self.assertEqual(section["status"], "completed")
        self.assertEqual(section["summary"], MACRO_SUMMARY)
        self.assertEqual(section["article"]["selectionTier"], 2)
        self.assertEqual(section["diagnostics"]["modelCalls"], 0)
        self.assertEqual(result["readyCount"], 1)
        summarize.assert_not_called()
        model.assert_not_called()


if __name__ == "__main__":
    unittest.main()
