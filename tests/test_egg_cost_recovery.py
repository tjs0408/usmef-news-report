"""Grounded egg import costs and late verified-candidate recovery, offline."""

from datetime import date
from threading import Event
import unittest
from unittest.mock import patch

from src import livestock_article_draft as d
from src import overseas_article_digest as s
from src.article_hwpx_layout import summary_reference_layout


COST = (
    "브라질 상파울루대 농업경제연구센터(CEPEA)에 따르면 현지 계란 산지가격은 "
    "한 알에 100원 안팎이지만, 항공 운송비와 관세 등이 더해지면서 수입가격이 크게 높아졌다."
)
BODY = "브라질산 계란 수입가격의 적정성에 대한 논의가 이어졌다. " + COST
DAY = date(2026, 10, 14)


def article(name, **changes):
    return {
        "title": "브라질 계란 수입가격과 항공 운송비",
        "url": "https://example.org/" + name,
        "publisher": "Test", "publishedDate": date(2026, 10, 13),
        "body": BODY, "briefBody": COST, "sourceLanguage": "ko",
        "headlineOnly": False, "searchResult": False, **changes,
    }


class EggImportCostTests(unittest.TestCase):
    def test_same_clause_preserves_per_egg_price_approximation_and_costs(self):
        with patch.object(s, "_ollama_generate") as model:
            summary = s._summarize_report_sentence.__wrapped__("domestic_egg", "title", BODY)
        model.assert_not_called()
        for fact in ("브라질 계란", "한 알에 100원 안팎", "항공 운송비·관세", "수입가격 형성"):
            self.assertIn(fact, summary)
        self.assertGreaterEqual(len(summary), 40)
        self.assertLessEqual(len(summary), 80)
        self.assertTrue(s._valid_brief(summary, "domestic_egg", BODY))
        layout = summary_reference_layout(summary, "domestic_egg")
        self.assertTrue(layout["oneLine"])
        self.assertGreaterEqual(layout["tracking"], -20)
        self.assertEqual(s._native_source_excerpt(BODY, summary), COST)
        self.assertNotIn("1300", summary)
        self.assertNotIn("낭비", summary)

    def test_country_price_and_approximation_are_read_not_hardcoded(self):
        changed = COST.replace("브라질 상파울루대", "태국 농업대").replace("100원 안팎", "80원 내외")
        summary = s._native_report_sentence("domestic_egg", changed)
        self.assertIn("태국 계란", summary)
        self.assertIn("80원 내외", summary)
        self.assertNotIn("100", summary)
        self.assertNotIn("브라질", summary)
        self.assertTrue(s._valid_brief(summary, "domestic_egg", changed))

    def test_missing_ambiguous_or_negated_evidence_is_not_a_cost_fact(self):
        invalid = (
            COST.replace("브라질 상파울루대", "현지 연구기관"),
            COST.replace("브라질 상파울루대", "미국·브라질 공동 연구기관"),
            COST.replace("계란", "닭고기"),
            COST.replace("한 알에", "kg당"),
            COST.replace("한 알에 ", ""),
            COST.replace("원 안팎", "달러 안팎"),
            COST.replace("항공 운송비와 관세", "사료비와 관세"),
            COST.replace("항공 운송비와 관세", "항공 운송비"),
            COST.replace("높아졌다.", "높아지지 않았다."),
            COST.replace("높아졌다.", "높아졌다는 주장은 사실이 아니라고 반박했다."),
            COST.replace("높아졌다.", "높아질 것으로 전망했다."),
            COST.replace(
                "이지만, 항공 운송비와 관세 등이 더해지면서 수입가격이 크게 높아졌다.",
                "이다. 항공 운송비와 관세 등이 더해지면서 수입가격이 크게 높아졌다.",
            ),
        )
        for body in invalid:
            with self.subTest(body=body):
                self.assertIsNone(s._korean_egg_import_cost_summary(body))


class EggCandidateRecoveryTests(unittest.TestCase):
    def _collect_with_late_candidate(self, candidate):
        main = article("main", body="브라질 계란 수급과 가격을 둘러싼 논의를 확인했다. " * 5,
                       briefBody="브라질 계란 수급에 대한 논의")
        failed, release_enrichment = Event(), Event()
        original_alternatives = d._verified_summary_alternatives
        original_native = s._native_report_sentence

        def native(kind, body):
            return original_native(kind, body) if COST in body else None

        def enrichment(current, *_args, **_kwargs):
            if current["url"] == main["url"]:
                self.assertTrue(release_enrichment.wait(4), "summary recovery never read its initial candidates")
                current["_candidateLinkOriginals"] = [candidate]
                current["_candidateLinksSearched"] = True
            return []

        def candidates_snapshot(*args, **kwargs):
            snapshot = original_alternatives(*args, **kwargs)
            if failed.is_set():
                # The recovery snapshot is empty BEFORE enrichment finishes.
                # Old code returned here when its two model calls were used.
                release_enrichment.set()
            return snapshot

        def failed_summary(*_args):
            s._ollama_generate("first bounded draft")
            s._ollama_generate("second bounded draft")
            failed.set()
            raise s.ArticleSummaryValidationError("요약 검증 미완료: 최소 40자 미달(26자).")

        with patch.object(d, "_usmef_pair", return_value={}), \
             patch.object(d, "_find_section", side_effect=lambda spec, *_: main if spec.key == "domestic_egg" else None), \
             patch.object(d, "_search_article", return_value=None) as search, \
             patch.object(d, "_candidate_links", side_effect=enrichment), \
             patch.object(d, "_verified_summary_alternatives", side_effect=candidates_snapshot), \
             patch.object(s, "_native_report_sentence", side_effect=native), \
             patch.object(s, "_ensure_ollama_ready", return_value={"available": True}), \
             patch.object(s, "_request_json", return_value={"response": "short draft"}) as request, \
             patch.object(s, "_summarize_report_sentence", side_effect=failed_summary) as summarize:
            result = d.collect_weekly_livestock_report_draft(DAY)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(summarize.call_count, 1)
        self.assertFalse(any(call.args[0].key == "domestic_egg" for call in search.call_args_list))
        return result["sections"]["domestic_egg"]

    def test_exhausted_model_reuses_existing_candidate_future_without_more_calls(self):
        ready = article("late-ready")
        section = self._collect_with_late_candidate(ready)
        self.assertEqual(section["status"], "completed")
        self.assertEqual(section["article"]["url"], ready["url"])
        self.assertEqual(section["article"]["sourceExcerpt"], COST)
        self.assertEqual(section["diagnostics"]["modelCalls"], 2)
        self.assertEqual(section["diagnostics"]["alternativeAttempts"], 1)
        self.assertTrue(s._valid_brief(section["summary"], "domestic_egg", ready["body"]))

    def test_exhausted_recovery_never_accepts_invalid_late_candidates(self):
        for changes in (
            {"publishedDate": date(2026, 10, 10)},
            {"publishedDate": date(2026, 10, 18)},
            {"searchResult": True}, {"headlineOnly": True},
            {"sourceLanguage": "en"}, {"url": "javascript:alert(1)"},
            {"body": "브라질 닭고기 가격과 공급 관련 원문을 확인했다. " * 5},
        ):
            with self.subTest(changes=changes):
                section = self._collect_with_late_candidate(article("invalid", **changes))
                self.assertEqual(section["status"], "summary_error")
                self.assertEqual(section["diagnostics"]["modelCalls"], 2)
                self.assertEqual(section["diagnostics"]["alternativeAttempts"], 0)
                self.assertNotIn("summary", section)


if __name__ == "__main__":
    unittest.main()
