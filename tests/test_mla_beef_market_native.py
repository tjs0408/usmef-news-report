"""MLA trade narrative grounding; no live HTTP or models in unit tests."""
import unittest
from unittest.mock import patch

from src import overseas_article_digest as s
from src.article_hwpx_layout import summary_reference_layout
from src.report_brief_style import MAX_ARTICLE_TRACKING


# Only the relevant body clauses are retained; these are not headline rules.
CHILLED_GROWTH = (
    "Growth was also evident in chilled beef with Thailand now one of "
    "South-East Asia's most significant chilled beef markets. "
)
BEEF_CUT_CONTEXT = (
    "New cuts, new opportunities The clearest sign of Thailand's growing sophistication "
    "as a beef market is its willingness to embrace cuts that once had limited appeal. "
    "One standout example is the rump cap. "
)
RUMP_IMPORTS = '"Thailand is now the largest importer of Australian rump caps in the world," Sam said.'
BODY = CHILLED_GROWTH + BEEF_CUT_CONTEXT + RUMP_IMPORTS
EXPECTED = "태국은 호주산 쇠고기 럼프캡의 세계 최대 수입국, 냉장 쇠고기 시장 확대"


class MlaBeefMarketNativeTests(unittest.TestCase):
    def tearDown(self):
        s._summarize_report_sentence.cache_clear()

    def test_explicit_thai_beef_body_clauses_recover_without_model_and_fit(self):
        with patch.object(s, '_ollama_generate') as model:
            summary = s._summarize_report_sentence('australia', 'Why Thailand is an export market worth watching', BODY)
        model.assert_not_called()
        self.assertEqual(summary, EXPECTED)
        self.assertEqual(len(summary), 40)
        self.assertTrue(s._valid_brief(summary, 'australia', BODY))
        layout = summary_reference_layout(summary, 'australia')
        self.assertTrue(layout['withinLineLimit'])
        self.assertGreaterEqual(layout['tracking'], MAX_ARTICLE_TRACKING)
        self.assertFalse(s._brief_numeric_values(summary))

    def test_each_explicit_clause_and_its_beef_origin_is_required(self):
        bodies = (
            BEEF_CUT_CONTEXT + RUMP_IMPORTS,
            CHILLED_GROWTH,
            CHILLED_GROWTH + RUMP_IMPORTS,
            BODY.replace('as a beef market', 'as a lamb market'),
            BODY.replace('chilled beef', 'chilled lamb'),
            BODY.replace('Australian rump caps', 'New Zealand rump caps'),
            BODY.replace('Thailand', 'Vietnam'),
            BODY.replace('One standout example is the rump cap.', 'One standout example is lamb leg.'),
        )
        for body in bodies:
            with self.subTest(body=body):
                self.assertIsNone(s._thai_australian_beef_market_summary(body))
                self.assertIsNone(s._native_report_sentence('australia', body))

    def test_negated_growth_imports_or_cut_context_never_qualify(self):
        bodies = (
            BODY.replace('Growth was also evident', 'No growth was also evident'),
            BODY.replace('Growth was also evident', 'Growth was not evident'),
            BODY.replace('is now the largest importer', 'is not the largest importer'),
            BODY.replace('is now the largest importer', 'may become the largest importer'),
            BODY.replace('is its willingness to embrace', 'is its unwillingness to embrace'),
            BODY.replace('One standout example is the rump cap.', 'One standout example is not the rump cap.'),
        )
        for body in bodies:
            with self.subTest(body=body):
                self.assertIsNone(s._thai_australian_beef_market_summary(body))

    def test_no_numbers_are_borrowed_from_lamb_or_untyped_frozen_trade(self):
        unrelated = (
            'The frozen red meat market doubled over two years. '
            'Lamb imports increased 20% to 400 tonnes, while lamb dishes were promoted. '
        )
        summary = s._native_report_sentence('australia', unrelated + BODY)
        self.assertEqual(summary, EXPECTED)
        self.assertFalse(s._brief_numeric_values(summary))
        self.assertNotIn('양고기', summary)
        self.assertNotIn('냉동', summary)
        self.assertIsNone(s._native_report_sentence('australia', unrelated))

    def test_quote_typography_and_attribution_do_not_change_facts(self):
        curly = BODY.replace("Thailand's", 'Thailand’s').replace("Asia's", 'Asia’s')
        curly = curly.replace('"Thailand', '“Thailand').replace('world,"', 'world,”')
        self.assertEqual(s._native_report_sentence('australia', curly), EXPECTED)
        statement = BODY.replace(RUMP_IMPORTS, 'Thailand is now the largest importer of Australian rump caps in the world.')
        self.assertEqual(s._native_report_sentence('australia', statement), EXPECTED)

    def test_headline_or_other_kind_cannot_activate_the_body_rule(self):
        title_only_body = 'Why Thailand is an export market worth watching. Australian beef and lamb trade opportunities.'
        self.assertIsNone(s._native_report_sentence('australia', title_only_body))
        for kind in ('us', 'brazil_chicken', 'domestic_egg'):
            with self.subTest(kind=kind):
                self.assertIsNone(s._grounded_market_statistic(kind, BODY))


if __name__ == '__main__':
    unittest.main()
