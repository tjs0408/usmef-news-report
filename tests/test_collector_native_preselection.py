"""Prefer immediately valid briefs within already verified original pools."""
from copy import deepcopy
from datetime import date
import unittest
from unittest.mock import patch

from src import livestock_article_draft as d
from src import overseas_article_digest as s


START, END = date(2026, 10, 4), date(2026, 10, 10)
REPORT_DAY = date(2026, 10, 7)
BEEF_TARIFF = (
    "중국이 남미의 친중 국가인 브라질의 소고기 수입품에 대해 1일부터 55%의 추가 관세를 부과한다고 상무부가 발표했다. "
    "상무부는 올해 브라질 소고기 수입 할당량이 100% 소진됐다고 이유를 밝혔다."
)
CPTPP_IMPORTS = (
    "정부는 CPTPP 가입 논의를 시작했다. 호주산 쇠고기, 멕시코산 쇠고기·돼지고기, "
    "캐나다산 돼지고기·닭고기, 뉴질랜드산 전지분유 등의 수입 증가가 국내 생산 감소로 이어질 수 있다는 전망이다."
)
BRAZIL_PENDING = (
    "As exportações de frango e mel do Brasil para a União Europeia ainda dependem de etapas administrativas, "
    "apesar da avaliação sanitária favorável. O governo brasileiro busca acelerar a liberação dos embarques "
    "ao mercado europeu. As compras poderão ser retomadas no curto prazo, após a conclusão dos procedimentos burocráticos."
)


def article(name, **extra):
    return {"title": "미국 돼지고기 공급과 수요 논의", "url": "https://example.org/" + name,
            "publisher": "Test", "publishedDate": date(2026, 10, 6),
            "body": "미국 돼지고기 수요와 공급 및 가격 추이를 분석했다. " * 5,
            "sourceLanguage": "ko", "searchResult": False, "headlineOnly": False, **extra}


class NativePreselectionTests(unittest.TestCase):
    def test_valid_native_alternate_beats_selected_article_without_inference(self):
        cases = (
            ("domestic", "미국 피자·햄버거 업계의 쇠고기 공급 논의",
             "미국 쇠고기 시장의 공급과 수요를 살펴봤다. " * 5,
             "중국 브라질산 쇠고기에 추가 관세", BEEF_TARIFF, "ko"),
            ("domestic_pork", "베트남 돼지고기 공급과 수요 논의",
             "베트남 돼지고기 시장의 공급과 수요를 살펴봤다. " * 5,
             "캐나다산 돼지고기 수입 증가 전망", CPTPP_IMPORTS, "ko"),
            ("domestic_chicken", "미국 닭고기 공급과 수요 논의",
             "미국 닭고기 시장의 공급과 수요를 살펴봤다. " * 5,
             "캐나다산 닭고기 수입 증가 전망", CPTPP_IMPORTS, "ko"),
            ("brazil_chicken", "Brazil chicken production outlook",
             "Brazil chicken supply and demand production market commentary. " * 5,
             "Brasil frango exportações UE", BRAZIL_PENDING, "pt"),
        )
        for key, main_title, main_body, ready_title, ready_body, language in cases:
            with self.subTest(key=key):
                ready = article("ready", title=ready_title, body=ready_body,
                                briefBody="A short excerpt omitting the full original conditions.",
                                sourceLanguage=language)
                second = article("second", title=main_title, body=main_body, sourceLanguage=language)
                main = article("main", title=main_title, body=main_body, alternatives=[ready, second],
                               sourceLanguage=language, sourceMethod="naver" if language == "ko" else "preferred")
                before = deepcopy(main)
                events = []
                with patch.object(d, "_usmef_pair", return_value={}), \
                     patch.object(d, "_find_section", side_effect=lambda spec, start, end: main if spec.key == key else None), \
                     patch.object(d, "_search_article", return_value=None) as search, \
                     patch.object(s, "_ensure_ollama_ready", return_value={"available": False, "message": "offline"}), \
                     patch.object(s, "_summarize_report_sentence", side_effect=AssertionError("no model summary needed")) as summarize, \
                     patch.object(s, "_ollama_generate", side_effect=AssertionError("no model call permitted")) as model:
                    result = d.collect_weekly_livestock_report_draft(REPORT_DAY, progress=lambda **event: events.append(event))
                section = result["sections"][key]
                self.assertEqual(section["status"], "completed")
                self.assertEqual(section["article"]["url"], ready["url"])
                self.assertEqual(section["article"]["publishedDate"], ready["publishedDate"].isoformat())
                self.assertEqual(section["diagnostics"]["modelCalls"], 0)
                self.assertEqual(section["diagnostics"]["alternativeAttempts"], 0)
                self.assertEqual(section["retryCount"], 0)
                self.assertEqual({link["url"] for link in section["candidateLinks"]}, {main["url"], second["url"]})
                self.assertTrue(s._valid_brief(section["summary"], key, ready_body))
                self.assertIn("sourceExcerpt", section["article"])
                self.assertEqual(main, before)
                self.assertNotIn("_nativeReadySummary", str(section))
                self.assertFalse(any(call.args[0].key == key for call in search.call_args_list))
                self.assertTrue(all(event["sections"][key]["article"]["url"] == ready["url"]
                                    for event in events if event["sections"][key]["article"]))
                summarize.assert_not_called()
                model.assert_not_called()

    def test_preselection_preserves_date_source_species_and_foreign_focus_guards(self):
        invalid = (
            {"publishedDate": date(2026, 10, 3)},
            {"publishedDate": date(2026, 10, 11)},
            {"url": "javascript:alert(1)"},
            {"originalUrl": "javascript:alert(1)"},
            {"url": "https:missing-host"},
            {"searchResult": True},
            {"headlineOnly": True},
            {"sourceLanguage": "en"},
            {"body": "미국 돼지고기 가격 상승"},
            {"title": "국내 돼지고기 공급 논의", "body": "국내 돼지고기 공급 감소와 가격 상승을 살펴봤다. " * 5},
            {"title": "호주 쇠고기 수출 증가", "body": "호주 쇠고기 수요와 공급 및 수출량 증가. " * 5},
            {"title": "이마트 돼지고기 할인 행사", "body": "미국 돼지고기 수입과 공급 및 가격 상승. " * 5},
        )
        spec = d.SPECS_BY_KEY["domestic_pork"]
        for changes in invalid:
            with self.subTest(changes=changes):
                main = article("main")
                main["alternatives"] = [article("ready", **{"body": main["body"] + " READY", **changes})]
                with patch.object(s, "_native_report_sentence", side_effect=lambda key, body: "ready" if body != main["body"] else None), \
                     patch.object(s, "_fit_report_summary", return_value="ready"), \
                     patch.object(s, "_valid_brief", return_value=True):
                    selected = d._prefer_native_summary_candidate(main, spec, START, END)
                self.assertEqual(selected["url"], main["url"])

    def test_fit_or_fact_validation_failure_keeps_the_existing_selection(self):
        spec = d.SPECS_BY_KEY["domestic_pork"]
        main = article("main", alternatives=[article("ready", body=CPTPP_IMPORTS)])
        for fits, valid in ((None, True), ("ready", False)):
            with self.subTest(fits=fits, valid=valid), \
                 patch.object(s, "_native_report_sentence", side_effect=lambda key, body: "ready" if body == CPTPP_IMPORTS else None), \
                 patch.object(s, "_fit_report_summary", return_value=fits), \
                 patch.object(s, "_valid_brief", return_value=valid):
                selected = d._prefer_native_summary_candidate(main, spec, START, END)
            self.assertEqual(selected["url"], main["url"])

    def test_first_alternate_that_fits_is_used_and_search_completion_is_retained(self):
        main = article("main", alternatives=[article("too_long", body=CPTPP_IMPORTS + " FIRST"),
                                            article("ready", body=CPTPP_IMPORTS + " SECOND")],
                       _candidateLinksSearched=True)
        def fit(native, key, body):
            return None if "FIRST" in body else "ready"
        with patch.object(s, "_native_report_sentence", side_effect=lambda key, body: "ready" if "CPTPP" in body else None), \
             patch.object(s, "_fit_report_summary", side_effect=fit), \
             patch.object(s, "_valid_brief", return_value=True), \
             patch.object(d, "_search_article") as search:
            selected = d._prefer_native_summary_candidate(main, d.SPECS_BY_KEY["domestic_pork"], START, END)
        self.assertTrue(selected["url"].endswith("ready"))
        self.assertTrue(selected["_candidateLinksSearched"])
        self.assertEqual([candidate["url"] for candidate in selected["alternatives"]],
                         [main["url"], main["alternatives"][0]["url"]])
        self.assertEqual(selected["_nativeReadySummary"][:2], ("domestic_pork", main["alternatives"][1]["body"]))
        search.assert_not_called()

    def test_foreign_ready_candidate_cannot_change_the_required_country(self):
        main = article("main", title="Brazil chicken production", sourceLanguage="pt", body=BRAZIL_PENDING)
        other = article("wrong", title="China chicken production", sourceLanguage="pt",
                        body="China chicken prices increased as supplies decreased. " * 5)
        main["alternatives"] = [other]
        with patch.object(s, "_native_report_sentence", side_effect=lambda key, body: "ready" if body == other["body"] else None), \
             patch.object(s, "_fit_report_summary", return_value="ready"), \
             patch.object(s, "_valid_brief", return_value=True):
            selected = d._prefer_native_summary_candidate(main, d.SPECS_BY_KEY["brazil_chicken"], START, END)
        self.assertEqual(selected["url"], main["url"])


if __name__ == "__main__":
    unittest.main()
