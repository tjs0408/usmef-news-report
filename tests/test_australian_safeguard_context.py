"""Quota conditions, annual trade ranges and retail presence are distinct facts."""
import unittest
from unittest.mock import patch
from src import overseas_article_digest as s
from src.article_hwpx_layout import summary_reference_layout

ORIGIN = "The initiative was sparked by China's decision to trigger safeguard measures on Australian beef imports earlier this year. "
TARIFF = "The safeguard imposed a 55% tariff once Australia's quota threshold was exceeded. "
TRADE = ("The immediate issue facing the industry was safeguard tariffs, which impacts on Australian beef exports to China had been significant. "
         "According to Murray, export volumes were currently running 70–80% below the same period last year. ")
RETAIL = "Premium retailers including Costco and Sam's Club continued to stock Australian chilled beef despite higher prices."
BODY = ORIGIN + TARIFF + TRADE + "Frozen beef trade had been particularly affected. " + RETAIL


class AustralianSafeguardContextTests(unittest.TestCase):
    def test_quota_range_period_and_shelf_presence_complete_without_model(self):
        with patch.object(s, '_ollama_generate', side_effect=AssertionError('typed facts need no inference')):
            summary = s._summarize_report_sentence.__wrapped__('australia', 'China beef trade', BODY)
        for fact in ('할당량 초과 시', '55%', '대중 수출량 전년비 70~80% 감소'):
            self.assertIn(fact, summary)
        self.assertNotIn('판매량 유지', summary)
        self.assertNotIn('가격 하락', summary)
        self.assertTrue(s._valid_brief(summary, 'australia', BODY))
        self.assertFalse(s._summary_needs_market_context('australia', BODY, summary))
        layout = summary_reference_layout(summary, 'australia')
        self.assertEqual(layout['estimatedLines'], 1)
        self.assertTrue(layout['withinLineLimit'])
        evidence = s._native_source_excerpt(BODY, summary)
        for passage in (TARIFF.strip(), TRADE[TRADE.index('safeguard tariffs'):].strip(), RETAIL):
            self.assertIn(passage, evidence)

    def test_changed_tariff_and_range_are_not_hardcoded(self):
        body = BODY.replace('55%', '45%').replace('70–80%', '20–30%')
        summary = s._native_report_sentence('australia', body)
        self.assertIn('관세 45%', summary)
        self.assertIn('20~30% 감소', summary)
        self.assertTrue(s._valid_brief(summary, 'australia', body))

    def test_condition_direction_period_product_and_denial_cannot_be_dropped(self):
        invalid = (
            BODY.replace('once', 'whether'),
            BODY.replace('was exceeded', 'was not exceeded'),
            BODY.replace('below the same period last year', 'above the same period last year'),
            BODY.replace('same period last year', 'previous month'),
            BODY.replace('Australian beef imports', 'Brazilian beef imports'),
            BODY.replace('Australian beef exports to China', 'Australian lamb exports to China'),
            BODY.replace('continued to stock Australian chilled beef', 'stopped stocking Australian chilled beef'),
            BODY.replace('70–80%', '80–70%'),
            BODY.replace(TARIFF, ''), BODY.replace(RETAIL, ''),
            BODY.replace(ORIGIN, 'The report was denied as false. ' + ORIGIN),
        )
        for body in invalid:
            with self.subTest(body=body):
                self.assertIsNone(s._australian_china_safeguard_fact(body))


if __name__ == '__main__':
    unittest.main()
