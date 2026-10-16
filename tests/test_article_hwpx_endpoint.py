"""Article application is atomic, offline, and safely permits terminal blanks."""
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from xml.etree import ElementTree as ET
import zipfile

import app as web
from src.article_hwpx import ARTICLE_SLOT_KEYS, ArticleHwpxError, _discover_slots
from src.overseas_article_digest import compact_report_summary


def complete_draft():
    return {
        "reportDate": "2026-10-01", "weekStart": "2026-09-27", "weekEnd": "2026-10-03",
        "sections": {
            spec.key: {
                "status": "completed",
                "summary": "축산물 공급 5% 감소·가격 4% 상승, 수요 회복에 따른 수급 안정 점검 필요",
                "article": {"title": f"{spec.key} 시장 동향 원문 제목", "publisher": "공식 매체",
                            "publishedDate": "2026-09-30", "url": f"https://example.org/news/{spec.key}"},
            }
            for spec in web.SECTION_SPECS
        },
    }


class ApplyArticleDraftEndpointTests(unittest.TestCase):
    def setUp(self):
        self.client = web.app.test_client()
        self.temp = tempfile.TemporaryDirectory()
        self.output_patch = patch.object(web, "OUTPUT_DIR", Path(self.temp.name))
        self.output_patch.start()

    def tearDown(self):
        self.output_patch.stop()
        self.temp.cleanup()

    def post(self, draft=None, filename="price.hwpx", data=b"uploaded report"):
        payload = {"draft": json.dumps(complete_draft() if draft is None else draft, ensure_ascii=False),
                   "report_file": (io.BytesIO(data), filename)}
        return self.client.post("/apply-article-draft", data=payload)

    def test_applies_to_copy_and_sends_attachment_without_crawling(self):
        def write_copy(source, target, draft):
            self.assertEqual(source.read_bytes(), b"uploaded report")
            self.assertEqual(draft["reportDate"], "2026-10-01")
            self.assertNotEqual(source, target)
            target.write_bytes(b"updated hwpx")
            return {"appliedCount": 12}

        with patch.object(web, "apply_article_draft_to_hwpx", side_effect=write_copy) as editor, \
                patch.object(web, "collect_weekly_livestock_report_draft") as crawler:
            response = self.post(filename="../사용자 원본.hwpx")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data, b"updated hwpx")
            self.assertEqual(response.mimetype, "application/vnd.hancom.hwpx")
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            self.assertEqual(response.headers["X-Article-Applied-Count"], "12")
            self.assertEqual(response.headers["X-Article-Blank-Count"], "0")
            self.assertIn("attachment;", response.headers["Content-Disposition"])
            editor.assert_called_once()
            crawler.assert_not_called()
            response.close()
        self.assertEqual(len(list(Path(self.temp.name).glob("*.hwpx"))), 1)
        self.assertFalse((Path(self.temp.name) / "사용자 원본.hwpx").exists())

    def test_real_upload_response_contains_styled_articles_and_unchanged_artwork(self):
        template = Path(__file__).resolve().parents[1] / 'report_template/weekly_overseas_market_report_table_template.hwpx'
        original = template.read_bytes()
        draft = complete_draft()
        with patch.object(web, 'collect_weekly_livestock_report_draft') as crawler:
            with self.post(draft, data=original) as response:
                self.assertEqual(200, response.status_code, response.json)
                self.assertEqual('12', response.headers['X-Article-Applied-Count'])
                with zipfile.ZipFile(io.BytesIO(original)) as before, zipfile.ZipFile(io.BytesIO(response.data)) as after:
                    self.assertEqual(before.namelist(), after.namelist())
                    for name in before.namelist():
                        if name.startswith('BinData/'):
                            self.assertEqual(before.read(name), after.read(name), name)
                    parts = {name: after.read(name) for name in after.namelist() if name.startswith('Contents/section')}
                    slots = _discover_slots(parts)
                    self.assertEqual(set(ARTICLE_SLOT_KEYS), set(slots))
                    header = ET.fromstring(after.read('Contents/header.xml'))
                    head_ns = {'hh': 'http://www.hancom.co.kr/hwpml/2011/head'}
                    styles = {node.get('id'): node for node in header.findall('.//hh:charPr', head_ns)}
                    for key, slot in slots.items():
                        domestic = slot.title is not None
                        summary = compact_report_summary(draft['sections'][key]['summary'], key)
                        prefix = ' - ' if domestic else ' - (현지동향) '
                        self.assertEqual(prefix + summary, slot.paragraph.own_text, key)
                        heights = {styles[run.attributes['charPrIDRef']].get('height') for run in slot.paragraph.children
                                   if run.name.endswith('}run') and run.text}
                        self.assertEqual({'1200'} if domestic else {'1300'}, heights, key)
                crawler.assert_not_called()
        self.assertEqual(original, template.read_bytes())
        self.assertEqual(1, len(list(Path(self.temp.name).glob('*.hwpx'))))

    def test_running_or_old_week_snapshots_rejected_before_editor(self):
        scenarios = []
        draft = complete_draft(); draft["sections"]["us"]["status"] = "summarizing"
        scenarios.append(draft)
        draft = complete_draft(); draft["sections"]["japan_egg"]["article"]["publishedDate"] = "2026-09-26"
        scenarios.append(draft)
        draft = complete_draft(); draft["weekStart"] = "2026-09-25"
        scenarios.append(draft)
        with patch.object(web, "apply_article_draft_to_hwpx") as editor:
            for draft in scenarios:
                with self.subTest(draft=draft):
                    self.assertEqual(self.post(draft).status_code, 400)
            editor.assert_not_called()
        self.assertFalse(list(Path(self.temp.name).iterdir()))

    def test_failed_summary_and_stale_metadata_are_blank_but_other_eleven_download(self):
        draft = complete_draft()
        draft['sections']['eu_pork'] = {
            'status': 'summary_error', 'summary': 'REJECTED MUST NOT BE INSERTED',
            'article': {'title': 'stale title', 'url': 'javascript:alert(1)', 'publishedDate': '2020-01-01'},
        }
        template = Path(__file__).resolve().parents[1] / 'report_template/weekly_overseas_market_report_table_template.hwpx'
        original = template.read_bytes()
        with patch.object(web, 'collect_weekly_livestock_report_draft') as crawler:
            with self.post(draft, data=original) as response:
                self.assertEqual(200, response.status_code, response.json)
                self.assertEqual('11', response.headers['X-Article-Applied-Count'])
                self.assertEqual('1', response.headers['X-Article-Blank-Count'])
                with zipfile.ZipFile(io.BytesIO(response.data)) as after, zipfile.ZipFile(io.BytesIO(original)) as before:
                    parts = {name: after.read(name) for name in after.namelist() if name.startswith('Contents/section')}
                    slots = _discover_slots(parts)
                    self.assertEqual(' - (현지동향) ', slots['eu_pork'].paragraph.own_text)
                    self.assertNotIn('REJECTED', ' '.join(slot.paragraph.own_text for slot in slots.values()))
                    for key, slot in slots.items():
                        if key != 'eu_pork':
                            self.assertIn('수급 안정', slot.paragraph.own_text)
                    for name in before.namelist():
                        if name.startswith('BinData/'):
                            self.assertEqual(before.read(name), after.read(name), name)
                crawler.assert_not_called()
        self.assertEqual(original, template.read_bytes())

    def test_absent_empty_and_terminal_sections_normalize_to_blank_without_mutating_snapshot(self):
        draft = complete_draft()
        del draft['sections']['us']
        draft['sections']['domestic']['summary'] = ''
        draft['sections']['domestic_egg']['status'] = 'model_unavailable'
        normalized = web._validate_hwpx_article_draft(draft)
        self.assertEqual(12, len(normalized['sections']))
        for key in ('us', 'domestic', 'domestic_egg'):
            self.assertEqual({'status': 'missing', 'summary': '', 'article': None}, normalized['sections'][key])
        self.assertNotIn('us', draft['sections'])
        self.assertEqual('model_unavailable', draft['sections']['domestic_egg']['status'])

    def test_zero_completed_unknown_or_malformed_snapshots_are_not_downloads(self):
        zero = complete_draft()
        for section in zero['sections'].values():
            section['status'] = 'summary_error'
        malformed = complete_draft(); malformed['sections']['eu_pork'] = None
        unknown = complete_draft(); unknown['sections']['unexpected'] = {'status': 'missing'}
        unknown_status = complete_draft(); unknown_status['sections']['eu_pork']['status'] = 'anything'
        nonstring_status = complete_draft(); nonstring_status['sections']['eu_pork']['status'] = []
        for draft in (zero, malformed, unknown, unknown_status, nonstring_status, {**complete_draft(), 'sections': {}}):
            with self.subTest(draft=draft), patch.object(web, 'apply_article_draft_to_hwpx') as editor:
                self.assertEqual(400, self.post(draft).status_code)
                editor.assert_not_called()

    def test_week_includes_sunday_and_saturday(self):
        draft = complete_draft()
        draft["sections"]["us"]["article"]["publishedDate"] = "2026-09-27"
        draft["sections"]["australia"]["article"]["publishedDate"] = "2026-10-03"
        self.assertIs(web._validate_hwpx_article_draft(draft), draft)

    def test_invalid_summary_or_metadata_is_reported(self):
        for field, value in (("summary", "짧은 요약"), ("summary", "가" * 96),
                             ("summary", "국내 기사에서는 미국 돼지고기 수급 변화와 가격 동향을 확인하고 공급 조정을 이어간다."),
                             ("summary", "-(현지동향) " + "가" * 40)):
            draft = deepcopy(complete_draft())
            draft["sections"]["us"][field] = value
            self.assertEqual(self.post(draft).status_code, 400)
        for field, value in (("title", ""), ("publisher", "bad\x00text"),
                             ("url", "javascript:alert(1)"), ("publishedDate", "unknown")):
            draft = complete_draft()
            draft["sections"]["us"]["article"][field] = value
            self.assertEqual(self.post(draft).status_code, 400)

    def test_bad_json_missing_file_hwp_and_empty_file_have_json_errors(self):
        response = self.client.post("/apply-article-draft", data={"draft": "{}"})
        self.assertEqual(response.status_code, 400)
        response = self.client.post("/apply-article-draft", data={
            "draft": "bad json", "report_file": (io.BytesIO(b"zip"), "report.hwpx")})
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json)
        self.assertEqual(self.post(filename="report.hwp").status_code, 400)
        self.assertEqual(self.post(data=b"").status_code, 400)

    def test_structural_errors_are_safe_and_do_not_publish_output(self):
        with patch.object(web, "apply_article_draft_to_hwpx", side_effect=ArticleHwpxError("12개 위치를 찾을 수 없습니다.")):
            response = self.post()
        self.assertEqual(response.status_code, 400)
        self.assertIn("위치", response.json["error"])
        self.assertFalse(list(Path(self.temp.name).iterdir()))

    def test_request_size_error_is_json(self):
        with patch.dict(web.app.config, {"MAX_CONTENT_LENGTH": 128}):
            response = self.post()
        self.assertEqual(response.status_code, 413)
        self.assertIn("20MB", response.json["error"])

    def test_missing_date_and_nondict_payload_fail_safely(self):
        for payload in ({}, [], None, {"reportDate": None}, {"reportDate": "20261001"}):
            with self.assertRaises(ValueError):
                web._validate_hwpx_article_draft(payload)


if __name__ == "__main__":
    unittest.main()
