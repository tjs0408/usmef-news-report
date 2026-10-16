"""Per-country line allowances are shared by prompts, drafts and HWPX output."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src import overseas_article_digest as digest
from src.article_hwpx import ArticleHwpxError, apply_article_draft_to_hwpx
from src.article_hwpx_layout import ArticleLayoutStyles, summary_reference_layout, _reference_styles
from src.report_brief_style import (
    MAX_ARTICLE_TRACKING, SECTION_AUDIENCES, SUMMARY_MAX_LINES, TWO_LINE_SECTIONS,
    summary_line_limit, style_prompt, summary_target_range,
)
from test_article_hwpx import _draft, _package
from test_article_hwpx_layout import _header


class ArticleLinePolicyTests(unittest.TestCase):
    def tearDown(self):
        digest._summarize_report_sentence.cache_clear()

    def test_only_us_beef_and_us_chicken_can_use_a_second_line(self):
        self.assertEqual(set(SECTION_AUDIENCES), set(SUMMARY_MAX_LINES))
        self.assertEqual({'us', 'us_chicken'}, TWO_LINE_SECTIONS)
        self.assertEqual(TWO_LINE_SECTIONS, {key for key, lines in SUMMARY_MAX_LINES.items() if lines == 2})
        for key in SECTION_AUDIENCES:
            self.assertEqual(2 if key in TWO_LINE_SECTIONS else 1, summary_line_limit(key))

    def test_twelve_prompts_do_not_globally_allow_wrapping(self):
        for key in SECTION_AUDIENCES:
            with self.subTest(key=key):
                prompt = style_prompt(key)
                self.assertIn(f'최저 {MAX_ARTICLE_TRACKING}', prompt)
                if key in TWO_LINE_SECTIONS:
                    self.assertIn('최대 두 줄을 허용', prompt)
                    self.assertIn('65~85자', prompt)
                    self.assertEqual((65, 85), summary_target_range(key))
                else:
                    self.assertIn('반드시 한 줄', prompt)
                    self.assertNotIn('최대 두 줄을 허용', prompt)

    @patch('src.article_hwpx_layout._metric_font', return_value=None)
    def test_minimum_tracking_is_minus_20_but_only_as_negative_as_needed(self, _font):
        styles = ArticleLayoutStyles(_header())
        natural = styles.measure_layout('가' * 10, available_width=20000, max_lines=1)
        self.assertEqual(0, natural['tracking'])
        tight = styles.measure_layout('가' * 10, available_width=11100, max_tracking=-100, max_lines=1)
        self.assertEqual(-20, MAX_ARTICLE_TRACKING)
        self.assertEqual(-17, tight['tracking'])
        self.assertTrue(tight['withinLineLimit'])
        self.assertGreater(styles.estimate_width('가' * 10, tracking=-16), 111)
        overflow = styles.measure_layout('가' * 10, available_width=10000, max_lines=1)
        self.assertFalse(overflow['withinLineLimit'])
        self.assertFalse(overflow['oneLine'])

    @patch('src.article_hwpx_layout._metric_font', return_value=None)
    def test_real_advance_width_that_failed_at_minus_17_fits_at_minus_20(self, _font):
        styles = ArticleLayoutStyles(_header())
        text = '가' * 10
        # Ten 13pt glyphs total 130pt; nine inter-glyph spaces shrink to
        # 110.11pt at -17 and 106.6pt at -20. This line needs all three
        # newly permitted points, without shrinking the 13pt body font.
        before = styles.measure_layout(text, available_width=10700, max_tracking=-17, max_lines=1)
        after = styles.measure_layout(text, available_width=10700, max_tracking=-20, max_lines=1)
        self.assertFalse(before['withinLineLimit'])
        self.assertTrue(after['withinLineLimit'])
        self.assertEqual(-20, after['tracking'])
        self.assertEqual(13, after['bodySizePt'])
        self.assertGreater(styles.estimate_width(text, tracking=-19), 107)
        self.assertLessEqual(styles.estimate_width(text, tracking=-20), 107)
        still_too_long = styles.measure_layout(text, available_width=10600, max_tracking=-100, max_lines=1)
        self.assertFalse(still_too_long['withinLineLimit'])
        self.assertGreaterEqual(still_too_long['tracking'], MAX_ARTICLE_TRACKING)

    def test_read_only_reference_measurement_does_not_append_styles(self):
        styles = _reference_styles()
        before = styles.patched_header()
        text = '미국 육계 병아리 입식수 전주보다 363만 2000마리 줄어 1억 8968만 9000마리 기록'
        self.assertTrue(summary_reference_layout(text, 'us_chicken')['withinLineLimit'])
        self.assertFalse(summary_reference_layout(text, 'brazil_chicken')['withinLineLimit'])
        self.assertFalse(summary_reference_layout(text, 'us_egg')['withinLineLimit'])
        self.assertEqual(before, styles.patched_header())

    def test_already_fitting_summary_does_not_call_repair_model(self):
        summary = '미국 육계 병아리 입식수 전주보다 363만 2000마리 줄어 1억 8968만 9000마리 기록'
        with patch.object(digest, '_summarize_report_sentence_content', return_value=summary), \
                patch.object(digest, '_repair_korean_report_sentence') as repair:
            self.assertEqual(summary, digest._summarize_report_sentence('us_chicken', 'market', summary))
        repair.assert_not_called()

    def test_document_only_wraps_the_two_allowed_sections(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / 'source.hwpx', Path(directory) / 'result.hwpx'
            _package(source)
            result = apply_article_draft_to_hwpx(source, target, _draft())
        for key in SECTION_AUDIENCES:
            layout = result['layout'][key]
            self.assertTrue(layout['withinLineLimit'])
            self.assertEqual(summary_line_limit(key), layout['allowedLines'])
            if key not in TWO_LINE_SECTIONS:
                self.assertTrue(layout['oneLine'], key)
            self.assertGreaterEqual(layout['tracking'], MAX_ARTICLE_TRACKING)

    def test_overflowing_other_section_is_rejected_without_a_partial_file(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / 'source.hwpx', Path(directory) / 'result.hwpx'
            _package(source)
            original = source.read_bytes()
            draft = _draft()
            draft['sections']['us_egg']['summary'] = (
                '미국 계란 시장은 수출 수요 회복과 공급 감소로 가격 상승 압력이 확대되는 가운데 향후 생산 기반 회복 여부에 대한 점검 필요')
            with self.assertRaisesRegex(ArticleHwpxError, '미국 계란.*1줄'):
                apply_article_draft_to_hwpx(source, target, draft)
            self.assertFalse(target.exists())
            self.assertEqual(original, source.read_bytes())

    def test_overflow_repair_is_bounded_and_cannot_invent_a_number(self):
        long = '미국 계란 공급 부족과 소비자 수요 증가로 가격 상승 압력이 확대되는 가운데 향후 생산 기반 회복 여부에 대한 점검 필요'
        bad = '미국 계란 가격 전년비 99% 상승, 공급 감소와 소비자 수요 증가로 수급 압박 확대'
        with patch.object(digest, '_summarize_report_sentence_content', return_value=long), \
                patch.object(digest, '_repair_korean_report_sentence', return_value=bad) as repair:
            with self.assertRaisesRegex(digest.ArticleDigestError, '1줄'):
                digest._summarize_report_sentence('us_egg', 'egg prices', long)
        repair.assert_called_once()
