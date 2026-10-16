"""Offline source reuse and bounded collector summary recovery."""
from contextlib import ExitStack
from datetime import date
import unittest
from unittest.mock import patch

from src import livestock_article_draft as d
from src import overseas_article_digest as s


REPORT_DAY = date(2026, 10, 7)
START, END = date(2026, 10, 4), date(2026, 10, 10)


def article(name, **extra):
    return {"title": "US egg prices and supply " + name,
            "url": "https://example.org/" + name, "publisher": "Test",
            "publishedDate": date(2026, 10, 6),
            "body": "US egg prices fell as production and supplies recovered. " * 4,
            **extra}


class CollectorRetryBudgetTests(unittest.TestCase):
    def test_exhausted_budget_preserves_layout_error_without_another_model_call(self):
        budget = s.ArticleModelBudget(max_calls=0)
        with patch.object(s, "_summarize_report_sentence_content", return_value="원문에 근거한 장문 요약") as content, \
             patch.object(s, "_fit_report_summary", return_value=None), \
             patch.object(s, "_repair_korean_report_sentence") as repair, \
             s.article_model_budget(budget):
            with self.assertRaises(s.ArticleSummaryLayoutError):
                s._summarize_report_sentence.__wrapped__("eu_pork", "title", "source")
        content.assert_called_once()
        repair.assert_not_called()

    def collect(self, main, summarize, *, search_result=None, key="us_egg", native=None):
        events = []
        with ExitStack() as stack:
            stack.enter_context(patch.object(d, "_usmef_pair", return_value={}))
            stack.enter_context(patch.object(d, "_find_section", side_effect=lambda spec, start, end:
                                            main if spec.key == key else None))
            search = stack.enter_context(patch.object(d, "_search_article", side_effect=lambda spec, *args, **kwargs:
                                                      search_result if spec.key == key else None))
            stack.enter_context(patch.object(s, "_ensure_ollama_ready", return_value={"available": True}))
            if native is None:
                stack.enter_context(patch.object(s, "_native_report_sentence", return_value=None))
            else:
                stack.enter_context(patch.object(s, "_native_report_sentence", side_effect=native))
            summary = stack.enter_context(patch.object(s, "_summarize_report_sentence", side_effect=summarize))
            result = d.collect_weekly_livestock_report_draft(REPORT_DAY, progress=lambda **event: events.append(event))
        return result["sections"][key], search, summary, events

    def test_layout_error_keeps_original_and_never_searches_for_recovery(self):
        main = article("main", alternatives=[article("one"), article("two")])
        section, search, summary, _ = self.collect(main, s.ArticleSummaryLayoutError("layout overflow"))
        self.assertEqual(section["status"], "summary_error")
        self.assertEqual(section["article"]["url"], main["url"])
        self.assertEqual(section["retryCount"], 0)
        self.assertEqual(section["diagnostics"]["alternativeAttempts"], 0)
        self.assertEqual(len(section["candidateLinks"]), 2)
        self.assertEqual(summary.call_count, 1)
        self.assertFalse(any(call.args[0].key == "us_egg" for call in search.call_args_list))

    def test_three_verified_originals_allow_only_one_alternate_attempt(self):
        main = article("main", alternatives=[article("one"), article("two")])
        section, search, summary, _ = self.collect(main, s.ArticleDigestError("invalid facts"))
        self.assertEqual(section["status"], "summary_error")
        self.assertEqual(summary.call_count, 2)
        self.assertEqual([call.args[1] for call in summary.call_args_list], [main["title"], main["alternatives"][0]["title"]])
        self.assertEqual(section["retryCount"], 1)
        self.assertEqual(section["diagnostics"]["alternativeAttempts"], 1)
        self.assertFalse(any(call.args[0].key == "us_egg" for call in search.call_args_list))

    def test_original_and_alternate_share_two_model_calls(self):
        main = article("main", alternatives=[article("one")])

        def too_many_model_calls(*_args):
            for _ in range(4):
                s._ollama_generate("brief")
            raise s.ArticleDigestError("invalid facts")

        with patch.object(s, "_request_json", return_value={"response": "draft"}) as request:
            section, _, summary, _ = self.collect(main, too_many_model_calls)
        self.assertEqual(section["status"], "summary_error")
        self.assertEqual(section["diagnostics"]["modelCalls"], 2)
        self.assertGreaterEqual(section["diagnostics"]["modelSeconds"], 0)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(summary.call_count, 1)

    def test_enrichment_downloads_are_reused_with_one_supplemental_search(self):
        main = article("main")
        extra = article("one", alternatives=[article("two")])
        def summarize(key, title, body):
            if title == main["title"]:
                raise s.ArticleDigestError("invalid facts")
            return "미국 계란 공급 회복으로 가격이 하락함"
        section, search, summary, events = self.collect(main, summarize, search_result=extra)
        self.assertEqual(section["status"], "completed")
        self.assertEqual(section["article"]["url"], extra["url"])
        self.assertEqual(summary.call_count, 2)
        self.assertEqual(len([call for call in search.call_args_list if call.args[0].key == "us_egg"]), 1)
        self.assertEqual(section["article"]["publishedDate"], "2026-10-06")
        self.assertEqual(len(section["candidateLinks"]), 2)
        self.assertEqual(section["retryCount"], 1)
        self.assertEqual(section["diagnostics"]["alternativeAttempts"], 1)
        self.assertGreaterEqual(section["diagnostics"]["sourceSeconds"], 0)
        self.assertGreaterEqual(section["diagnostics"]["summarySeconds"], 0)
        self.assertNotIn("_candidateLinkOriginals", str(section))
        self.assertNotIn("_candidateLinksSearched", main)
        self.assertIsNot(events[0]["sections"]["us_egg"]["diagnostics"], section["diagnostics"])

    def test_failed_enrichment_search_is_not_repeated_by_summary_recovery(self):
        section, search, summary, _ = self.collect(article("main"), s.ArticleDigestError("invalid facts"))
        self.assertEqual(section["status"], "summary_error")
        self.assertEqual(summary.call_count, 1)
        self.assertEqual(len([call for call in search.call_args_list if call.args[0].key == "us_egg"]), 1)
        self.assertEqual(section["retryCount"], 0)
        self.assertEqual(section["diagnostics"]["alternativeAttempts"], 0)

    def test_optional_link_failure_is_bounded_and_does_not_fail_report(self):
        with patch.object(d, "_candidate_links", side_effect=RuntimeError("private upstream detail")):
            section, search, summary, _ = self.collect(article("main"), s.ArticleDigestError("invalid facts"))
        self.assertEqual(section["status"], "summary_error")
        self.assertEqual(summary.call_count, 1)
        self.assertFalse(any(call.args[0].key == "us_egg" for call in search.call_args_list))
        self.assertNotIn("private", str(section))
        self.assertEqual(section["diagnostics"]["alternativeAttempts"], 0)

    def test_native_recovery_uses_full_original_and_retains_date(self):
        main = article("main", title="Brazil chicken prices main", body="Brazil chicken prices and supply. " * 6)
        extra = article("native", title="Brazil chicken prices native", body="Brazil chicken prices and supply. " * 6 + "FULL ORIGINAL APPROVAL",
                        briefBody="Brazil chicken supply excerpt.")
        main["alternatives"] = [extra, {**extra, "url": "https://example.org/second"}]
        native_text = "브라질 닭고기 수출은 원문에 따른 추가 승인을 기다리고 있음"
        def native(key, body):
            return native_text if "FULL ORIGINAL APPROVAL" in body else None
        with patch.object(s, "_fit_report_summary", return_value=native_text) as fit, \
             patch.object(s, "_native_source_excerpt", return_value="FULL ORIGINAL APPROVAL") as excerpt:
            section, _, summary, _ = self.collect(main, s.ArticleDigestError("invalid facts"), key="brazil_chicken", native=native)
        self.assertEqual(section["status"], "completed")
        self.assertEqual(section["article"]["publishedDate"], extra["publishedDate"].isoformat())
        self.assertEqual(section["article"]["sourceExcerpt"], "FULL ORIGINAL APPROVAL")
        self.assertIn("FULL ORIGINAL APPROVAL", fit.call_args.args[2])
        self.assertIn("FULL ORIGINAL APPROVAL", excerpt.call_args.args[0])
        self.assertEqual(summary.call_count, 1)
        self.assertEqual(section["diagnostics"]["alternativeAttempts"], 1)

    def test_link_reader_retains_dated_originals_and_never_reuses_unsafe_candidates(self):
        main = article("main")
        extra = article("one", alternatives=[article("two")])
        with patch.object(d, "_search_article", return_value=extra) as search:
            links, originals, searched = d.read_candidate_links(main, d.SPECS_BY_KEY["us_egg"], START, END)
        self.assertTrue(searched)
        self.assertEqual(len(links), 2)
        self.assertEqual([candidate["body"] for candidate in originals], [extra["body"], extra["alternatives"][0]["body"]])
        search.assert_called_once()
        main["alternatives"] = [article("unsafe", url="javascript:alert(1)"),
                                article("stale", publishedDate=date(2026, 10, 3))]
        self.assertEqual(d._verified_summary_alternatives(main, d.SPECS_BY_KEY["us_egg"], START, END, []), [])

    def test_repeated_optional_link_reads_do_not_repeat_failed_searches(self):
        main = article("main")
        with patch.object(d, "_search_article", return_value=None) as search:
            self.assertEqual(d._candidate_links(main, d.SPECS_BY_KEY["us_egg"], START, END), [])
            self.assertEqual(d._candidate_links(main, d.SPECS_BY_KEY["us_egg"], START, END), [])
        search.assert_called_once()
        self.assertTrue(main["_candidateLinksSearched"])


if __name__ == "__main__":
    unittest.main()
