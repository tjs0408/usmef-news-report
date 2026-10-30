"""Offline domestic recovery reserves the existing budget for a new original."""
from contextlib import ExitStack
from datetime import date
import unittest
from unittest.mock import patch

from src import livestock_article_draft as d
from src import overseas_article_digest as s


DAY = date(2026, 10, 7)
START, END = date(2026, 10, 4), date(2026, 10, 10)


def original(name, species="돼지고기", **changes):
    # All evidence is synthetic. The dedicated model retry harness explicitly
    # disables native summaries rather than relying on unsupported source text.
    # Distinct headlines/bodies prevent accidentally treating two independent
    # originals as reprints while leaving the production relevance gate active.
    return {
        "url": "https://example.org/" + name,
        "title": f"미국 {species} 공급과 가격 동향 {name}",
        "publisher": "검증 매체",
        "sourceLanguage": "ko",
        "publishedDate": date(2026, 10, 6),
        "body": (f"미국 {species} 공급은 출하 지연과 현지 수요 회복으로 부족해져 가격이 상승했다. "
                 f"{name} 원문은 수요와 생산 추이를 함께 살펴보고 수입 여건을 설명했다. "
                 "현지 업계는 시장의 여러 변화를 관찰하며 향후 공급 상황을 점검하고 있다고 전했다."),
        "_candidateLinksSearched": True,
        **changes,
    }


class DomesticRetrySelectionTests(unittest.TestCase):
    def collect(self, key, main, summarize):
        """Exercise the real selection, recovery, budget and relevance gates."""
        calls = []

        def request(_url, **kwargs):
            budget = s._article_model_budget.get()
            calls.append({"budget": budget, "timeout": kwargs["timeout"],
                          "attemptLimit": s._article_attempt_call_limit.get()})
            return {"response": "synthetic model result"}

        with ExitStack() as stack:
            stack.enter_context(patch.object(d, "_usmef_pair", return_value={}))
            stack.enter_context(patch.object(d, "_find_section", side_effect=lambda spec, *_:
                                            main if spec.key == key else None))
            search = stack.enter_context(patch.object(d, "_search_article", return_value=None))
            stack.enter_context(patch.object(s, "_ensure_ollama_ready", return_value={"available": True}))
            stack.enter_context(patch.object(s, "_native_report_sentence", return_value=None))
            stack.enter_context(patch.object(s, "_request_json", side_effect=request))
            summary = stack.enter_context(patch.object(s, "_summarize_report_sentence", side_effect=summarize))
            result = d.collect_weekly_livestock_report_draft(DAY)
        return result["sections"][key], calls, summary, search

    def assert_original_budget(self, calls):
        self.assertEqual(len(calls), 2)
        first, second = (call["budget"] for call in calls)
        self.assertIs(first, second, "recovery must not create a fresh allowance")
        self.assertEqual(first.max_calls, 2)
        self.assertEqual(first.max_seconds, 45.0)
        self.assertEqual(first.run_budget.max_seconds, 180.0)
        self.assertEqual(first.calls, 2)
        self.assertGreaterEqual(first.seconds, 0)
        self.assertLessEqual(calls[0]["timeout"], 45.0)
        self.assertLessEqual(calls[1]["timeout"], calls[0]["timeout"])

    def test_failed_primary_leaves_second_call_for_verified_alternate(self):
        for key, species in (("domestic_pork", "돼지고기"),
                             ("domestic_chicken", "닭고기")):
            with self.subTest(key=key):
                alternate = original("수요 회복 소식", species)
                main = original("공급 감소 조사", species, alternatives=[alternate])

                def summarize(_key, title, _body):
                    s._ollama_generate("one bounded model draft")
                    if title == main["title"]:
                        # A second repair of the SAME failed original must be
                        # blocked, leaving this request for the other source.
                        s._ollama_generate("same-source repair must not consume standby call")
                        self.fail("the primary consumed both model calls")
                    return "미국 현지 시장의 공급과 수요 변화로 해당 축종의 가격과 수입 여건 변화 전망"

                section, calls, summary, search = self.collect(key, main, summarize)
                self.assertEqual(section["status"], "completed")
                self.assertEqual(section["article"]["url"], alternate["url"])
                self.assertEqual([call.args[1] for call in summary.call_args_list],
                                 [main["title"], alternate["title"]])
                self.assertEqual(section["retryCount"], 1)
                self.assertEqual(section["diagnostics"]["alternativeAttempts"], 1)
                self.assertEqual(section["diagnostics"]["modelCalls"], 2)
                self.assert_original_budget(calls)
                self.assertEqual(calls[0]["attemptLimit"], 1)
                self.assertIsNone(calls[1]["attemptLimit"])
                self.assertFalse(any(call.args[0].key == key for call in search.call_args_list))

    def test_shared_pool_cannot_reselect_failed_higher_ranked_original_or_alias(self):
        alternate = original("독립 수요 보고")
        main = original("돼지 돈육 공급 감소 조사", alternatives=[alternate])
        alias = {**main, "url": "https://example.org/reprint", "originalUrl": main["url"],
                 "alternatives": []}
        main["alternatives"] = [alias, alternate]
        spec = d.SPECS_BY_KEY["domestic_pork"]
        self.assertGreater(d._relevance(main, spec), d._relevance(alternate, spec))

        def summarize(_key, title, _body):
            s._ollama_generate("bounded draft")
            if title == main["title"]:
                raise s.ArticleSummaryValidationError("요약 검증 미완료: 최소 40자 미달")
            return "미국 돼지고기 시장의 공급과 수요 변화로 현지 가격과 수입 여건 변화 전망"

        section, calls, summary, _ = self.collect("domestic_pork", main, summarize)
        self.assertEqual(section["status"], "completed")
        self.assertEqual(section["article"]["url"], alternate["url"])
        self.assertEqual([call.args[1] for call in summary.call_args_list],
                         [main["title"], alternate["title"]])
        self.assertEqual(summary.call_count, 2)
        self.assert_original_budget(calls)

    def test_unverified_alternates_never_reserve_a_call_or_enter_inference(self):
        invalid = (
            {"publishedDate": START.replace(day=3)},
            {"publishedDate": END.replace(day=11)},
            {"sourceLanguage": "en"},
            {"searchResult": True},
            {"headlineOnly": True},
            {"url": "javascript:alert(1)"},
            {"species": "계란"},
        )
        for changes in invalid:
            with self.subTest(changes=changes):
                values = dict(changes)
                candidate = original("부적합 후보", values.pop("species", "돼지고기"), **values)
                main = original("검증된 원문", alternatives=[candidate])

                def summarize(*_args):
                    s._ollama_generate("first existing allowance")
                    s._ollama_generate("second existing allowance")
                    raise s.ArticleSummaryValidationError("요약 검증 미완료")

                section, calls, summary, search = self.collect("domestic_pork", main, summarize)
                self.assertEqual(section["status"], "summary_error")
                self.assertEqual(section["article"]["url"], main["url"])
                self.assertEqual(summary.call_count, 1)
                self.assertEqual(section["retryCount"], 0)
                self.assertEqual(section["diagnostics"]["alternativeAttempts"], 0)
                self.assertTrue(all(call["attemptLimit"] is None for call in calls))
                self.assert_original_budget(calls)
                # Invalid existing originals never receive inference. Once
                # the same two calls are exhausted, source-only discovery has
                # one independent chance; an empty result stays incomplete.
                recovery_searches = [call for call in search.call_args_list
                                     if call.args[0].key == "domestic_pork"]
                self.assertEqual(len(recovery_searches), 1)
                self.assertTrue(recovery_searches[0].kwargs["native_only"])
                self.assertEqual(recovery_searches[0].args[1:3], (START, END))
                self.assertIn(main["url"], recovery_searches[0].kwargs["exclude_urls"])
                self.assertEqual(section["sourceDiagnostics"]["nativeRecoverySearches"], 1)
                self.assertEqual(section["sourceDiagnostics"]["nativeRecoveryReady"], 0)
                self.assertNotIn("summary", section)

    def test_stale_and_conflicting_species_are_skipped_before_valid_retry(self):
        stale = original("지난주 원문", publishedDate=date(2026, 10, 3))
        egg = original("미국 계란 가격 소식", "계란")
        alternate = original("새로운 수요 보고")
        main = original("돼지 돈육 공급 조사", alternatives=[stale, egg, alternate])

        def summarize(_key, title, _body):
            s._ollama_generate("bounded draft")
            if title == main["title"]:
                raise s.ArticleSummaryValidationError("요약 검증 미완료")
            self.assertEqual(title, alternate["title"])
            return "미국 돼지고기 시장의 공급과 수요 변화로 현지 가격과 수입 여건 변화 전망"

        section, calls, summary, _ = self.collect("domestic_pork", main, summarize)
        self.assertEqual(section["status"], "completed")
        self.assertEqual(section["article"]["url"], alternate["url"])
        self.assertEqual(section["article"]["publishedDate"], "2026-10-06")
        self.assertEqual(summary.call_count, 2)
        self.assert_original_budget(calls)


if __name__ == "__main__":
    unittest.main()
