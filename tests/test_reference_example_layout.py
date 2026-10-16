"""Prompt references must demonstrate the same line policy as completed briefs."""
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from src import report_brief_style as style
from src.article_hwpx_layout import summary_reference_layout


class ReferenceExampleLayoutTests(unittest.TestCase):
    def tearDown(self):
        style._one_line_reference_example.cache_clear()

    def test_one_line_sections_only_show_fitting_original_examples(self):
        contexts = ('', 'price retail demand', 'production supply slaughter',
                    'import export tariff', 'cost drought flu delivery')
        for kind in style.SECTION_AUDIENCES:
            if style.summary_line_limit(kind) != 1:
                continue
            for context in contexts:
                with self.subTest(kind=kind, context=context):
                    examples = style.reference_examples(kind, context)
                    self.assertEqual(len(examples), 2)
                    for sentence in examples:
                        self.assertIn(sentence, style.STYLE_EXAMPLES[kind])
                        layout = summary_reference_layout(sentence, kind)
                        self.assertTrue(layout['withinLineLimit'], sentence)
                        self.assertTrue(layout['oneLine'], sentence)
                        self.assertGreaterEqual(layout['tracking'], style.MAX_ARTICLE_TRACKING)

    def test_matching_trade_example_cannot_override_the_one_line_limit(self):
        overflow = style.STYLE_EXAMPLES['australia'][4]
        # Both Australia and EU pork now have a one-line report allowance.
        with patch.dict(style.STYLE_EXAMPLES, {'eu_pork': style.STYLE_EXAMPLES['australia']}):
            examples = style.reference_examples('eu_pork', 'imports exports trade tariffs')
            self.assertNotIn(overflow, examples)
            self.assertEqual(len(examples), 2)
            self.assertTrue(all(summary_reference_layout(sentence, 'eu_pork')['withinLineLimit']
                                for sentence in examples))
            self.assertNotIn(f'문체 예시: {overflow}', style.style_prompt('eu_pork', 'imports exports trade tariffs'))
        self.assertFalse(summary_reference_layout(overflow, 'australia')['withinLineLimit'])

    def test_two_line_sections_keep_their_existing_references_without_filtering(self):
        with patch('src.article_hwpx_layout.summary_reference_layout',
                   side_effect=AssertionError('two-line examples must remain available')):
            for kind in style.TWO_LINE_SECTIONS:
                examples = style.reference_examples(kind)
                self.assertEqual(2, len(examples))
                self.assertTrue(all(sentence in style.STYLE_EXAMPLES[kind] for sentence in examples))

    def test_example_geometry_is_cached_across_prompt_contexts(self):
        style._one_line_reference_example.cache_clear()
        with patch('src.article_hwpx_layout.summary_reference_layout',
                   wraps=summary_reference_layout) as measure:
            style.reference_examples('eu_pork', 'price retail')
            calls = measure.call_count
            self.assertEqual(calls, len(style.STYLE_EXAMPLES['eu_pork']))
            style.reference_examples('eu_pork', 'production supply')
            self.assertEqual(measure.call_count, calls)

    def test_no_fitting_example_is_omitted_instead_of_showing_an_overflow(self):
        with patch.dict(style.STYLE_EXAMPLES, {'eu_pork': ('가격 상승 ' * 40,)}):
            self.assertEqual(style.reference_examples('eu_pork', 'price'), ())

    def test_style_and_layout_modules_can_be_imported_in_either_order(self):
        modules = ('src.report_brief_style', 'src.article_hwpx_layout')
        for order in (modules, tuple(reversed(modules))):
            code = '\n'.join(f'import {module}' for module in order)
            code += "\nfrom src.report_brief_style import reference_examples\nassert reference_examples('australia')"
            with self.subTest(order=order):
                result = subprocess.run(
                    [sys.executable, '-B', '-c', code],
                    cwd=Path(__file__).resolve().parents[1],
                    capture_output=True, text=True, encoding='utf-8', timeout=10,
                )
                self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
