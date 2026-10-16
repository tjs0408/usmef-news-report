"""Recurring report facts should survive a new week without model retries."""
import unittest
from unittest.mock import patch

from src import overseas_article_digest as s
from src.article_hwpx_layout import summary_reference_layout
from src.report_brief_style import MAX_ARTICLE_TRACKING


PORK_PRODUCTION = (
    "돼지고기 생산량, 도축두수 및 중량 지난주 돼지고기 생산량은 전주 "
    "(5억 4,440만 파운드 ) 대비 3.3%, 전년 대비 1.1% 증가한 5억 6,240만 "
    "파운드를 기록했고, 2026년 누계 기준으로는 2025년 대비 0.4% 증가했다."
)
BROILER_MARKET = (
    "DOMESTIC MARKET HIGHLIGHTS WOGs are entering the week with a steady tone. "
    "Floor stocks remain barely adequate. Bone-in breasts and front halves are fully steady. "
    "B/S breasts and tenders continue about steady. Demand for wings are noted as unseasonably light. "
    "Dark meat activity continues steady and supplies are moving well. The market is steady. "
    "EXPORT MARKET HIGHLIGHTS Export market is moderate to active."
)
EGG_IMPORT_PRICES = (
    "그러나 브라질산 계란의 개당 수입가격은 1300원으로 미국산(464원)의 2.8배, "
    "태국산(305원)의 4.3배에 달했다. "
    "다변화를 내세우지만 왜 저렇게 비싸고 관세도 불리한 나라를 골라 국민세금을 "
    "투입했는지 이유는 불확실하다."
)
TOKYO_DAILY_TABLE = (
    "JA全農たまご 鶏卵相場（東京）\n2026年10月14日(水) 09:00 発表\n"
    "東 京 高値 基準値 安値 LL 334 310 ±0 303 L 340 315 ±0 309 "
    "M 340 315 ±0 309 MS 360 335 ±0 329 S 334 310 ±0 303 SS 264 240 ±0 233 "
    "特殊高値 ----- 333 ±0 ----- 特殊安値 ----- 194 ±0 ----- "
    "市況 保合 入荷量 760t\n単位 円 / kg"
)


class CurrentSourceNativeSummaryTests(unittest.TestCase):
    def tearDown(self):
        s._summarize_report_sentence.cache_clear()

    def test_new_source_clauses_complete_without_model_and_obey_layout(self):
        for kind, body in (
            ('us_pork', PORK_PRODUCTION), ('us_chicken', BROILER_MARKET),
            ('domestic_egg', EGG_IMPORT_PRICES), ('japan_egg', TOKYO_DAILY_TABLE),
        ):
            with self.subTest(kind=kind), patch.object(s, '_ollama_generate') as model:
                summary = s._summarize_report_sentence(kind, 'Unrelated title', body)
                model.assert_not_called()
                self.assertGreaterEqual(len(summary), 40)
                self.assertTrue(s._valid_brief(summary, kind, body), summary)
                layout = summary_reference_layout(summary, kind)
                self.assertTrue(layout['withinLineLimit'], (summary, layout))
                self.assertGreaterEqual(layout['tracking'], MAX_ARTICLE_TRACKING)

    def test_pork_production_excludes_reference_quantity_and_cumulative_change(self):
        summary = s._native_report_sentence('us_pork', PORK_PRODUCTION)
        for fact in ('3.3%', '1.1%', '5억 6240만 파운드', '증가'):
            self.assertIn(fact, summary)
        for fact in ('54440', '4,440', '0.4%', '2025', '2026'):
            self.assertNotIn(fact, summary)
        changed = PORK_PRODUCTION.replace('3.3%', '2.2%').replace('1.1%', '1.7%').replace('6,240만', '3,610만').replace('증가한', '감소한')
        summary = s._native_report_sentence('us_pork', changed)
        self.assertIn('2.2%·전년비 1.7% 감소', summary)
        self.assertIn('5억 3610만 파운드', summary)
        self.assertTrue(s._valid_brief(summary, 'us_pork', changed))
        self.assertTrue(summary_reference_layout(summary, 'us_pork')['withinLineLimit'])

    def test_production_requires_same_species_unit_and_actual_not_forecast(self):
        for body in (
            PORK_PRODUCTION.replace('돼지고기', '닭고기'),
            PORK_PRODUCTION.replace('파운드', '톤'),
            PORK_PRODUCTION.replace('기록했고', '기록할 전망이고'),
            PORK_PRODUCTION.replace('증가한', '증가하지 않은'),
        ):
            self.assertIsNone(s._usmef_production_summary('us_pork', body))

    def test_broiler_market_scope_never_uses_export_conditions(self):
        summary = s._native_report_sentence('us_chicken', BROILER_MARKET)
        self.assertIn('시장은 보합', summary)
        self.assertIn('가까스로 적정 수준', summary)
        self.assertIn('날개 수요', summary)
        self.assertNotIn('수출', summary)
        for body in (
            BROILER_MARKET.replace('The market is steady.', 'The market is higher.'),
            BROILER_MARKET.replace('barely adequate', 'well balanced and adequate'),
            BROILER_MARKET.replace('unseasonably light', 'moderate to good'),
            BROILER_MARKET.replace('WOGs', 'Beef cuts'),
            'DOMESTIC MARKET HIGHLIGHTS WOGs are steady. The market is steady. '
            'EXPORT MARKET HIGHLIGHTS Floor stocks remain barely adequate. '
            'Demand for wings are noted as unseasonably light.',
        ):
            self.assertIsNone(s._national_broiler_market_summary(body))

    def test_egg_import_price_is_reported_comparison_without_editorial_claim(self):
        summary = s._native_report_sentence('domestic_egg', EGG_IMPORT_PRICES)
        for fact in ('브라질산 계란', '1300원', '미국산 464원', '2.8배 수준'):
            self.assertIn(fact, summary)
        for opinion in ('허투루', '세금', '황당', '낭비', '무책임', '불확실'):
            self.assertNotIn(opinion, summary)
        changed = EGG_IMPORT_PRICES.replace('브라질산', '태국산').replace('1300원', '650원').replace('(464원)', '(232원)')
        summary = s._native_report_sentence('domestic_egg', changed)
        self.assertIn('태국산 계란', summary)
        self.assertIn('650원', summary)
        self.assertIn('미국산 232원', summary)
        self.assertTrue(s._valid_brief(summary, 'domestic_egg', changed))
        for body in (
            EGG_IMPORT_PRICES.replace('계란', '닭고기'),
            EGG_IMPORT_PRICES.replace('개당', 'kg당'),
            EGG_IMPORT_PRICES.replace('수입가격은', '예상 수입가격은'),
            EGG_IMPORT_PRICES.replace('달했다.', '달했다는 주장은 사실이 아니라고 반박했다.'),
        ):
            self.assertIsNone(s._korean_egg_import_price_comparison_summary(body))

    def test_tokyo_table_reads_benchmark_not_high_low_or_other_grade(self):
        self.assertEqual(s._japanese_egg_daily_table_fact(TOKYO_DAILY_TABLE), ('315', '760'))
        summary = s._japanese_egg_daily_table_summary(TOKYO_DAILY_TABLE)
        self.assertIn('M 규격', summary)
        self.assertIn('315엔', summary)
        self.assertIn('760톤', summary)
        self.assertNotIn('340', summary)
        self.assertNotIn('335', summary)
        self.assertTrue(40 <= len(summary) <= s.SUMMARY_LIMITS['japan_egg'])
        self.assertTrue(summary_reference_layout(summary, 'japan_egg')['withinLineLimit'])
        changed = TOKYO_DAILY_TABLE.replace('M 340 315 ±0 309', 'M 330 322 ±0 312').replace('760t', '680t')
        self.assertEqual(s._japanese_egg_daily_table_fact(changed), ('322', '680'))
        for body in (
            TOKYO_DAILY_TABLE.replace('円 / kg', '円 / 個'),
            TOKYO_DAILY_TABLE.replace('M 340 315 ±0 309', 'M 340 350 ±0 309'),
            TOKYO_DAILY_TABLE.replace('M 340 315 ±0 309', 'M 340 315 +5 309'),
            TOKYO_DAILY_TABLE.replace('東 京 高値', '大 阪 高値'),
            TOKYO_DAILY_TABLE.replace('10月14日', '10月32日'),
            TOKYO_DAILY_TABLE.replace('市況 保合', '市況 強保合'),
            TOKYO_DAILY_TABLE.replace('M 340 315 ±0 309', '')
                + ' 大 阪 高値 基準値 安値 M 340 315 ±0 309 MS 350 330 ±0 320',
        ):
            self.assertIsNone(s._japanese_egg_daily_table_fact(body))

    def test_tokyo_native_brief_preserves_table_currency_and_arrival_unit(self):
        summary = s._native_report_sentence('japan_egg', TOKYO_DAILY_TABLE)
        self.assertIsNotNone(summary)
        self.assertTrue(s._valid_brief(summary, 'japan_egg', TOKYO_DAILY_TABLE))
        self.assertIn((315.0, 'jpy'), s._numeric_unit_facts(TOKYO_DAILY_TABLE))
        self.assertIn((760.0, 'tonne'), s._numeric_unit_facts(TOKYO_DAILY_TABLE))
        self.assertFalse(s._valid_brief(summary.replace('315엔', '320엔'), 'japan_egg', TOKYO_DAILY_TABLE))
        self.assertFalse(s._valid_brief(summary.replace('760톤', '760두'), 'japan_egg', TOKYO_DAILY_TABLE))


if __name__ == '__main__':
    unittest.main()
