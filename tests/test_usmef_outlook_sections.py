"""USMEF's own later outlook must not be hidden behind weekly price charts."""
from unittest import TestCase
from unittest.mock import MagicMock, Mock, patch

from src import overseas_article_digest as s
from src.article_hwpx_layout import summary_reference_layout


FORECAST = (
    "USDA는 이번 보고서에서 2026년 소고기 생산량 전망치를 전월 대비 0.3% 하향 조정한 "
    "1,125만 톤으로 발표했다. "
)
BACKGROUND = (
    "이는 지난 8월 보고서(-1.3%)와 9월 보고서(-0.4%)에 이은 추가 하향 조정이며, "
    "전년 대비로는 4.6% 감소한 수준이다. "
)
CAUSE = (
    "USDA는 당초 예상보다 늘어난 암소 도축량을 상쇄하고도 남을 정도로 거세우 및 미경산우의 "
    "도축 속도가 둔화되고 도체중량 역시 예상치를 밑돈 점을 반영해 2026년 생산량 전망치를 낮추었다고 밝혔다."
)
OUTLOOK = FORECAST + BACKGROUND + CAUSE
WEEKLY_BEEF = (
    "지난주 소고기 생산량은 전주 및 전년 대비 각각 3.1%와 3.4% 감소한 "
    "4억 7,190만 파운드를 기록했으며, 2026년 누계 기준으로는 2025년 대비 4.7% 감소했다. "
    "소고기 가격의 주간 동향을 함께 확인했다. "
    "미국 소고기 공급과 가격 변동을 검토하는 주간 시장동향 보고서의 주요 자료를 함께 확인했다. "
    "미국 소고기 시장의 주간 생산 동향과 도축 현황을 같은 보고서에 정리했다. "
)
PORK_TEXT = "미국 돼지고기 공급 및 수출 전망을 설명한 원문이며 돼지고기 생산량과 도축두수 전망을 확인했다. " * 4


def page(blocks, texts, height=13200):
    result = Mock()
    result.rect = s.pymupdf.Rect(0, 0, 1080, height)
    def get_text(mode="text", **kwargs):
        if mode == "blocks":
            return blocks
        clip = kwargs.get("clip")
        return texts.get(round(clip.y0), "") if clip is not None else "native Korean issue " * 10
    result.get_text.side_effect = get_text
    return result


def document(pages):
    result = MagicMock()
    result.__enter__.return_value = result
    result.__iter__.side_effect = lambda: iter(pages)
    result.__getitem__.side_effect = pages.__getitem__
    return result


class UsmefOutlookSectionTests(TestCase):
    def setUp(self):
        s._extract_usmef_market_texts.cache_clear()
        s._summarize_report_sentence.cache_clear()

    def tearDown(self):
        s._extract_usmef_market_texts.cache_clear()
        s._summarize_report_sentence.cache_clear()

    def test_tall_issue_later_species_outlooks_are_read_once_without_chart_or_pork_leak(self):
        blocks = [
            (70, 750, 380, 815, "미, 소고기 시장동향"),
            (70, 4000, 900, 4050, "미, 한국으로의 소고기 주간 수출량"),
            (70, 5100, 420, 5190, "미, 돼지고기 시장동향"),
            (70, 7000, 900, 7050, "돼지고기 컷아웃 주간 가격"),
            (70, 8500, 330, 8570, "소고기 생산량 및 수출 전망"),
            (70, 8880, 350, 8910, "돼지고기 생산량 및 수출 전망"),
            (70, 9200, 1010, 9240, "미, 분기별 소고기 생산량 전망\n단위 : 백만톤"),
        ]
        tall = page(blocks, {815: WEEKLY_BEEF, 5190: PORK_TEXT, 8570: OUTLOOK, 8910: PORK_TEXT})
        with patch.object(s, "_download_bytes", return_value=b"same public issue") as download, \
             patch.object(s.pymupdf, "open", return_value=document([tall])):
            texts = s._extract_usmef_market_texts("https://example.org/same-issue.pdf")
        download.assert_called_once()
        tall.get_pixmap.assert_not_called()
        self.assertTrue(texts["beef"].startswith("소고기 생산량 및 수출 전망"))
        self.assertIn(FORECAST.strip(), texts["beef"])
        self.assertIn(CAUSE, texts["beef"])
        self.assertIn("4억 7,190만", texts["beef"], "weekly fallback facts must remain available")
        self.assertNotIn("돼지고기", texts["beef"])
        self.assertNotIn("미경산우", texts["pork"])
        self.assertNotIn("백만톤", texts["beef"])
        clips = [call.kwargs["clip"] for call in tall.get_text.call_args_list if "clip" in call.kwargs]
        outlook_clip = next(clip for clip in clips if round(clip.y0) == 8570)
        self.assertEqual(round(outlook_clip.y1), 8880)
        self.assertGreater(outlook_clip.x1, 1000, "later narrative spans the full page, not the market sidebar crop")

    def test_later_page_outlook_is_added_without_reusing_a_separate_issue(self):
        first = page([(70, 100, 500, 150, "소고기 시장동향"),
                      (70, 700, 900, 750, "소고기 컷아웃 주간 가격")], {150: WEEKLY_BEEF}, 1000)
        later = page([(70, 100, 500, 150, "소고기 생산량 및 수출 전망"),
                      (70, 700, 900, 750, "미, 분기별 소고기 생산량 전망\n단위 : 백만톤")], {150: OUTLOOK}, 1000)
        with patch.object(s, "_download_bytes", return_value=b"one PDF") as download, \
             patch.object(s.pymupdf, "open", return_value=document([first, later])):
            texts = s._extract_usmef_market_texts("https://example.org/one.pdf")
        download.assert_called_once()
        self.assertIn(CAUSE, texts["beef"])
        self.assertIn(WEEKLY_BEEF.strip(), texts["beef"])

    def test_chart_heading_cannot_create_a_supplemental_article(self):
        chart = page([(70, 100, 1010, 150, "미, 분기별 소고기 생산량 전망\n단위 : 백만톤")],
                     {150: OUTLOOK}, 1000)
        self.assertEqual(s._extract_usmef_outlook_texts([chart]), {})
        self.assertFalse(any("clip" in call.kwargs for call in chart.get_text.call_args_list))

    def test_merged_opposite_species_passage_is_not_assigned_to_beef(self):
        merged = page([(70, 100, 500, 150, "소고기 생산량 및 수출 전망")],
                      {150: OUTLOOK + " " + PORK_TEXT}, 1000)
        self.assertEqual(s._extract_usmef_outlook_texts([merged]), {})

    def test_same_year_forecast_preserves_month_revision_tonnage_and_cause_without_model(self):
        body = OUTLOOK + " " + WEEKLY_BEEF
        with patch.object(s, "_ollama_generate", side_effect=AssertionError("native issue needs no inference")):
            summary = s._summarize_report_sentence("us", "Same issue market outlook", body)
        self.assertIn("거세우·미경산우 도축 둔화", summary)
        self.assertIn("도체중량 예상 하회", summary)
        self.assertIn("2026년", summary)
        self.assertIn("1125만 톤", summary)
        self.assertIn("전월비 0.3% 하향", summary)
        self.assertNotIn("3.1%", summary)
        self.assertNotIn("4.6%", summary)
        self.assertTrue(s._valid_brief(summary, "us", body))
        self.assertFalse(s._summary_needs_market_context("us", body, summary))
        evidence = s._native_source_excerpt(body, summary)
        self.assertIn(FORECAST.strip(), evidence)
        self.assertIn(CAUSE, evidence)
        self.assertNotIn("4억 7,190만", evidence)
        layout = summary_reference_layout(summary, "us")
        self.assertEqual(layout["estimatedLines"], 2)
        # Two-line briefs may now tighten only enough to finish the word
        # crossing the first line, rather than split a Korean syllable off.
        self.assertGreaterEqual(layout["tracking"], -20)
        self.assertLessEqual(layout["tracking"], 0)
        if layout["estimatedLineTexts"]:
            self.assertEqual(2, len(layout["estimatedLineTexts"]))

    def test_changed_source_values_are_parsed_not_a_saved_week_summary(self):
        changed = OUTLOOK.replace("2026년", "2028년").replace("0.3%", "1.7%").replace("1,125만", "1,098만")
        fact = s._usmef_slaughter_weight_outlook_fact(changed)
        self.assertIsNotNone(fact)
        self.assertIn("2028년", fact[0])
        self.assertIn("1098만 톤", fact[0])
        self.assertIn("1.7% 하향", fact[0])
        self.assertTrue(s._valid_brief(fact[0], "us", changed))

    def test_forecast_guard_rejects_wrong_year_direction_negation_species_and_missing_cause(self):
        invalid = (
            FORECAST + BACKGROUND + CAUSE.replace("2026년", "2027년"),
            OUTLOOK.replace("하향 조정한", "상향 조정한"),
            OUTLOOK.replace("둔화되고", "둔화되지 않고"),
            OUTLOOK.replace("예상치를 밑돈", "예상치를 웃돈"),
            OUTLOOK.replace("소고기", "돼지고기"),
            FORECAST + BACKGROUND,
            OUTLOOK.replace("낮추었다고 밝혔다", "낮추지 않았다고 밝혔다"),
            "해당 수치가 허위라고 부인했다. " + OUTLOOK,
        )
        for body in invalid:
            with self.subTest(body=body):
                self.assertIsNone(s._usmef_slaughter_weight_outlook_fact(body))

    def test_without_an_outlook_the_existing_weekly_statistic_still_completes_without_model(self):
        with patch.object(s, "_ollama_generate", side_effect=AssertionError("no extra model call")):
            summary = s._summarize_report_sentence("us", "Weekly production", WEEKLY_BEEF)
        self.assertIn("전주비 3.1%", summary)
        self.assertIn("4억 7190만 파운드", summary)
        self.assertNotIn("전망", summary)
