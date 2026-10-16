"""Read-only UI rendering checks; no upstream downloads or Excel automation."""
import unittest
from datetime import date
from unittest.mock import patch
from bs4 import BeautifulSoup

import app as web


class WorkspacePageTests(unittest.TestCase):
    def setUp(self):
        self.client = web.app.test_client()

    def page(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        return response.get_data(as_text=True)

    def test_enabled_collection_matches_page(self):
        with patch.object(web, "CEPEA_COLLECTION_ENABLED", True):
            html = self.page()
        self.assertIn("10개 시트 자동 반영 활성화", html)
        self.assertIn("브라질 CEPEA 수집 재개", html)
        self.assertNotIn("동기화 보류</span>", html)

    def test_disabled_collection_matches_page(self):
        with patch.object(web, "CEPEA_COLLECTION_ENABLED", False):
            html = self.page()
        self.assertIn("8개 시트 자동 반영 활성화", html)
        self.assertIn("브라질 CEPEA 수집 보류", html)
        self.assertIn("동기화 보류</span>", html)

    def test_workspace_and_form_contracts(self):
        html = self.page()
        for workspace in ("report", "articles", "sources"):
            self.assertIn(f'data-workspace-tab="{workspace}"', html)
        self.assertIn('name="template_file"', html)
        self.assertIn('id="report-form" action="/start-report"', html)
        self.assertIn("표 8 · 그래프 8", html)
        self.assertIn('id="article-copy-button" type="button" class="secondary" disabled', html)

    def test_collection_groups_and_chicken_card_order(self):
        page = BeautifulSoup(self.page(), "html.parser")
        market = page.select('[aria-labelledby="market-data-heading"] .sheet-card')
        graphs = page.select('[aria-labelledby="graph-sync-heading"] .sheet-card')
        self.assertEqual(len(market), 8)
        self.assertEqual(len(graphs), 2)
        names = [card.h3.text for card in market]
        self.assertEqual(names.index("닭-브라질"), names.index("닭-미국") + 1)
        self.assertTrue(all("그래프" in card.h3.text for card in graphs))

    def test_collection_artwork_matches_species_and_country(self):
        page = BeautifulSoup(self.page(), "html.parser")
        expected = [
            ("cow", "us"), ("cow", "au"), ("pig", "us"), ("pig", "eu-de"),
            ("chicken", "us"), ("chicken", "br"), ("egg", "us"), ("egg", "jp"),
            ("chicken", "us"), ("chicken", "br"),
        ]
        avatars = page.select("#workspace-sources .sheet-avatar")
        self.assertEqual([(x["data-animal"], x["data-country"]) for x in avatars], expected)
        self.assertTrue(all(x.get("aria-hidden") == "true" for x in avatars))
        self.assertEqual(len(page.select(".sheet-chart")), 2)
        self.assertEqual(len(page.select(".sheet-animal")), 8)
        graph_avatars = page.select('[aria-labelledby="graph-sync-heading"] .sheet-avatar')
        for avatar in graph_avatars:
            self.assertIsNone(avatar.select_one(".sheet-animal"))
            self.assertEqual(avatar.select_one(".sheet-chart use")["href"], "#scope-chart")
        self.assertEqual(len(page.select(".region-flag")), 1)
        self.assertFalse(page.select(".sheet-icon"))
        # Every internal SVG reference resolves once; no remote artwork dependency.
        for use in page.select("#workspace-sources use"):
            self.assertTrue(use["href"].startswith("#scope-"))
            self.assertEqual(len(page.select(use["href"])), 1)

    def test_default_report_date_is_today(self):
        page = BeautifulSoup(self.page(), "html.parser")
        input_field = page.select_one("#article-report-date")
        self.assertIsNotNone(input_field)
        self.assertEqual(input_field.get("value"), date.today().isoformat())

    def test_default_report_date_does_not_shift_by_weekday_or_year(self):
        for today in (
            date(2026, 10, 12),  # Monday
            date(2026, 10, 15),  # Thursday
            date(2026, 10, 17),  # Saturday
            date(2026, 10, 18),  # Sunday
            date(2026, 12, 31),  # End of year
            date(2027, 1, 1),    # Start of year
        ):
            with self.subTest(today=today), patch.object(web, "date", wraps=date) as clock:
                clock.today.return_value = today
                page = BeautifulSoup(self.page(), "html.parser")
                input_field = page.select_one("#article-report-date")
                self.assertIsNotNone(input_field)
                self.assertEqual(input_field.get("value"), today.isoformat())

    def test_upload_card_keeps_native_input_and_described_limit(self):
        html = self.page()
        self.assertIn("기준 Excel 파일 선택 또는 드래그", html)
        self.assertIn('for="template-file"', html)
        input_field = BeautifulSoup(html, 'html.parser').select_one('#template-file')
        self.assertEqual(input_field.get('type'), 'file')
        self.assertEqual(input_field.get('accept'), '.xlsx')
        self.assertEqual(input_field.get('aria-label'), '기준 Excel 파일')
        self.assertEqual(input_field.get('aria-describedby'), 'upload-hint selected-file')
        self.assertTrue(input_field.has_attr('required'))
        self.assertIn('id="upload-title"', html)
        self.assertIn('id="upload-file-name" class="upload-file-name" hidden', html)
        self.assertIn('class="upload-icon-check"', html)
        self.assertIn("최대 20MB", html)
        self.assertIn('uploadField.addEventListener("drop"', html)

    def test_elapsed_time_displays_total_only(self):
        html = self.page()
        self.assertIn('id="article-elapsed-time"', html)
        self.assertIn('id="elapsed-time"', html)
        self.assertNotIn("stageDurations", html)
        self.assertIn("window.clearInterval(articleElapsedTimer)", html)

    def test_copy_feedback_is_announced_and_styled_in_the_viewport(self):
        html = self.page()
        notice = BeautifulSoup(html, "html.parser").select_one("#article-copy-feedback")
        self.assertEqual(notice.get("role"), "status")
        self.assertEqual(notice.get("aria-live"), "polite")
        self.assertEqual(notice.get("aria-atomic"), "true")
        self.assertTrue(notice.has_attr("hidden"))
        self.assertIn("✓ 복사 완료", html)
        self.assertIn("브라우저의 클립보드 권한", html)


if __name__ == "__main__":
    unittest.main()
