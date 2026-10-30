"""Pork-led originals outrank easier mixed briefs only while AI is available.

These tests isolate ranking, not translation or layout validation. Existing
date/language/species gates run normally; summary readiness is mocked offline.
"""
from contextlib import ExitStack, contextmanager
from datetime import date
import unittest
from unittest.mock import patch

from src import livestock_article_draft as d, overseas_article_digest as s


START, END = date(2026, 10, 11), date(2026, 10, 17)
SPEC = d.SPECS_BY_KEY["domestic_pork"]
READY_SUMMARY = "CPTPP 가입 시 캐나다 돼지고기 관세 철폐로 수입 증가와 국내 생산 감소 예상"


def article(name, title, body, **changes):
    return {
        "url": "https://example.org/" + name,
        "title": title,
        "publisher": "검증 매체 " + name,
        "publishedDate": date(2026, 10, 14),
        "sourceLanguage": "ko",
        "body": body,
        **changes,
    }


def pork(name="pork"):
    return article(name, "독일 돼지고기 공급 증가와 도매가격 동향", (
        "독일 돼지고기 공급은 출하 증가로 확대됐다. "
        "독일 돼지고기 도매가격은 소비 수요 부진으로 하락했다. "
        "현지 돼지고기 가공업계는 생산 비용 절감과 해외 수출 시장 회복을 추진했다. "
    ) * 2)


def mixed(name="mixed"):
    return article(name, "CPTPP 가입 논의와 해외 축산물 교역 변화", (
        "정부는 CPTPP 가입을 검토하고 있다. 호주 쇠고기와 캐나다 돼지고기의 관세 철폐로 "
        "수입 증가와 국내 생산 감소가 예상된다. 축산물 수급 영향을 점검하고 있다. "
    ) * 2)


def another_pork(name="another-pork"):
    return article(name, "미국 돈육 수출 회복과 생산량 확대", (
        "미국 돈육 수출량은 아시아 수요 회복으로 전년보다 8% 증가했다. "
        "현지 양돈농가는 돼지고기 생산 확대에 맞춰 출하 시기를 조정했다. "
        "주요 가공업체는 해외 수출 계약을 체결하며 생산비 부담을 줄였다. "
    ) * 2)


@contextmanager
def readiness(*ready_articles):
    ready_bodies = {item["body"] for item in ready_articles}
    with ExitStack() as stack:
        stack.enter_context(patch.object(s, "_native_report_sentence", side_effect=lambda _key, body:
                                        READY_SUMMARY if body in ready_bodies else None))
        stack.enter_context(patch.object(s, "_fit_report_summary", side_effect=lambda native, *_args: native))
        stack.enter_context(patch.object(s, "_valid_brief", return_value=True))
        stack.enter_context(patch.object(s, "_native_source_excerpt", side_effect=lambda body, _summary: body))
        model = stack.enter_context(patch.object(s, "_ollama_generate", side_effect=AssertionError("no inference")))
        search = stack.enter_context(patch.object(d, "_search_article", side_effect=AssertionError("no discovery")))
        yield
        model.assert_not_called()
        search.assert_not_called()


class PorkFocusPreselectionTests(unittest.TestCase):
    def test_online_keeps_pork_led_primary_but_offline_uses_ready_mixed_alternate(self):
        primary, fallback = pork(), mixed()
        primary["alternatives"] = [fallback]
        self.assertEqual(d._domestic_pork_focus(primary), 2)
        self.assertEqual(d._domestic_pork_focus(fallback), 1)
        with readiness(fallback):
            online = d._prefer_native_summary_candidate(primary, SPEC, START, END, True)
            offline = d._prefer_native_summary_candidate(primary, SPEC, START, END, False)
        self.assertEqual(online["url"], primary["url"])
        self.assertNotIn("_nativeReadySummary", online)
        self.assertEqual(offline["url"], fallback["url"])
        self.assertEqual(offline["_nativeReadySummary"][:2], (SPEC.key, fallback["body"]))

    def test_online_replaces_ready_mixed_primary_with_pork_led_original(self):
        fallback, dedicated = mixed(), pork()
        fallback["alternatives"] = [dedicated]
        with readiness(fallback):
            online = d._prefer_native_summary_candidate(fallback, SPEC, START, END, True)
            offline = d._prefer_native_summary_candidate(fallback, SPEC, START, END, False)
        self.assertEqual(online["url"], dedicated["url"])
        self.assertNotIn("_nativeReadySummary", online)
        self.assertEqual(offline["url"], fallback["url"])
        self.assertIn("_nativeReadySummary", offline)

    def test_same_pork_focus_prefers_a_ready_original_without_a_model_call(self):
        primary, ready = pork(), another_pork()
        primary["alternatives"] = [ready]
        self.assertEqual(d._domestic_pork_focus(ready), 2)
        with readiness(ready):
            selected = d._prefer_native_summary_candidate(primary, SPEC, START, END, True)
        self.assertEqual(selected["url"], ready["url"])
        self.assertIn("_nativeReadySummary", selected)

    def test_higher_focus_cannot_bypass_week_or_verified_original_gates(self):
        for changes in ({"publishedDate": date(2026, 10, 18)}, {"sourceLanguage": "en"},
                        {"headlineOnly": True}, {"searchResult": True}, {"url": "javascript:alert(1)"}):
            with self.subTest(changes=changes):
                fallback = mixed()
                invalid = {**pork(), **changes}
                fallback["alternatives"] = [invalid]
                with readiness(fallback):
                    selected = d._prefer_native_summary_candidate(fallback, SPEC, START, END, True)
                self.assertEqual(selected["url"], fallback["url"])


class PorkFocusRecoveryOrderingTests(unittest.TestCase):
    def test_model_available_ranks_pork_led_alternative_before_native_mixed(self):
        failed, fallback, dedicated = another_pork("failed"), mixed(), pork()
        failed["alternatives"] = [fallback, dedicated]
        with readiness(fallback):
            online = d._verified_summary_alternatives(failed, SPEC, START, END, [], prefer_pork_focus=True)
            offline = d._verified_summary_alternatives(failed, SPEC, START, END, [], native_only=True)
        self.assertEqual([item["url"] for item in online], [dedicated["url"], fallback["url"]])
        self.assertEqual([item["url"] for item in offline], [fallback["url"]])

    def test_native_fallback_survives_two_non_native_higher_focus_candidates_offline(self):
        failed = article("failed", "베트남 돼지고기 시장과 수급 동향", (
            "베트남 돼지고기 생산량은 사육 감소로 줄었고 현지 공급 부족으로 가격이 상승했다. "
            "정부는 돼지고기 검역과 수입 정책을 조정하며 시장 수급 안정을 추진했다. "
        ) * 2)
        first, second, fallback = pork(), another_pork(), mixed()
        failed["alternatives"] = [first, second, fallback]
        with readiness(fallback):
            selected = d._verified_summary_alternatives(failed, SPEC, START, END, [], native_only=True)
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["url"], fallback["url"])

    def test_focus_priority_never_restores_an_excluded_original(self):
        failed, fallback, excluded = another_pork("failed"), mixed(), pork()
        failed["alternatives"] = [fallback, excluded]
        with readiness(fallback):
            selected = d._verified_summary_alternatives(failed, SPEC, START, END, [],
                                                       (excluded,), prefer_pork_focus=True)
        self.assertEqual([item["url"] for item in selected], [fallback["url"]])


if __name__ == "__main__":
    unittest.main()
