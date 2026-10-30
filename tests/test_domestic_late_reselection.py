"""Bounded retries follow the original actually attempted after enrichment."""
from contextlib import ExitStack
from datetime import date
from threading import Event
import unittest
from unittest.mock import patch

from src import livestock_article_draft as d, overseas_article_digest as s


REPORT_DAY = date(2026, 10, 7)


def article(name, body):
    return {
        "title": "미국 돼지고기 공급 가격 " + name,
        "url": "https://example.org/" + name,
        "originalUrl": "https://example.org/" + name,
        "publisher": "기사" + name,
        "publishedDate": date(2026, 10, 6),
        "sourceLanguage": "ko",
        "body": body * 8,
    }


class DomesticLateReselectionTests(unittest.TestCase):
    def collect(self, primary, *, alternate=None, late=False, summarize):
        summary_started = Event()
        tried = []

        def relevance(candidate, spec, **_kwargs):
            if spec.key != "domestic_pork":
                return -1
            return 10 if late and candidate["url"].endswith("/B") else 5

        def candidate_links(candidate, spec, *_args, **kwargs):
            if kwargs.get("search_missing") is False:
                return []
            if late:
                if not summary_started.wait(timeout=2):
                    raise AssertionError("collector never began summarizing")
                candidate["_candidateLinkOriginals"] = [alternate]
            candidate["_candidateLinksSearched"] = True
            return []

        def progress(**event):
            if "한국어 보고체 요약 중" in event.get("message", ""):
                summary_started.set()

        def record_attempt(kind, title, body, *_args, **_kwargs):
            tried.append(title)
            return summarize(len(tried))

        with ExitStack() as stack:
            stack.enter_context(patch.object(d, "_usmef_pair", return_value={}))
            stack.enter_context(patch.object(d, "_find_section", side_effect=lambda spec, *_args:
                                            primary if spec.key == "domestic_pork" else None))
            search = stack.enter_context(patch.object(d, "_search_article", return_value=None))
            stack.enter_context(patch.object(d, "_candidate_links", side_effect=candidate_links))
            stack.enter_context(patch.object(d, "_relevance", side_effect=relevance))
            stack.enter_context(patch.object(s, "_native_report_sentence", return_value=None))
            stack.enter_context(patch.object(s, "_ensure_ollama_ready", return_value={"available": True}))
            stack.enter_context(patch.object(s, "_summarize_report_sentence", side_effect=record_attempt))
            request = stack.enter_context(patch.object(s, "_request_json", return_value={"response": "draft"}))
            result = d.collect_weekly_livestock_report_draft(REPORT_DAY, progress=progress)
        return result["sections"]["domestic_pork"], tried, request, search

    def test_late_selected_failed_original_is_not_reselected_for_second_call(self):
        primary = article("A", "미국 돼지고기 공급 가격과 수출 동향을 집계한 원문A입니다. ")
        alternate = article("B", "미국 돼지고기 공급 가격과 수출 동향을 별도 확인한 원문B입니다. ")

        def summarize(attempt):
            s._ollama_generate("one bounded call per original")
            if attempt == 1:
                raise s.ArticleSummaryValidationError("first original summary failed")
            return "미국 돼지고기 수급이 원문에 따라 변동한 가운데 시장 공급 확대와 가격 안정세 지속 전망"

        section, tried, request, search = self.collect(primary, alternate=alternate, late=True,
                                                     summarize=summarize)
        self.assertEqual(tried, [alternate["title"], primary["title"]])
        self.assertEqual(section["status"], "completed")
        self.assertEqual(section["article"]["url"], primary["url"])
        self.assertEqual(section["diagnostics"]["alternativeAttempts"], 1)
        self.assertEqual(section["diagnostics"]["modelCalls"], 2)
        self.assertEqual(request.call_count, 2)
        self.assertFalse(any(call.args[0].key == "domestic_pork" for call in search.call_args_list))

    def test_no_alternate_preserves_both_original_repair_calls(self):
        primary = article("A", "미국 돼지고기 공급 가격과 수출 동향을 집계한 원문A입니다. ")

        def summarize(_attempt):
            s._ollama_generate("original first draft")
            s._ollama_generate("original corrected draft")
            return "미국 돼지고기 수급이 원문에 따라 변동한 가운데 시장 공급 확대와 가격 안정세 지속 전망"

        section, tried, request, search = self.collect(primary, summarize=summarize)
        self.assertEqual(tried, [primary["title"]])
        self.assertEqual(section["status"], "completed")
        self.assertEqual(section["diagnostics"]["alternativeAttempts"], 0)
        self.assertEqual(section["diagnostics"]["modelCalls"], 2)
        self.assertEqual(request.call_count, 2)
        self.assertFalse(any(call.args[0].key == "domestic_pork" for call in search.call_args_list))


if __name__ == "__main__":
    unittest.main()
