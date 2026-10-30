"""Observed Australian beef exports retain country, month, unit and comparison."""
from pathlib import Path
import json
import unittest

from src.australia_export_fact_frame import native_australia_export_brief
from src.article_hwpx_layout import summary_reference_layout
from src.overseas_article_digest import _valid_brief


HEADER = ("Recent imported beef tariff impacts in China and the United States are evident in "
          "Australia's August beef export statistics released yesterday. ")
MONTHLY = ("Total exports for the month to all markets reached 128,832 tonnes, a sizeable "
           "15,000t or 10pc decline on the previous month – but that can largely be "
           "attributed to lower mid-winter production, rather than any decline in overall demand.")
CALENDAR = ("For the calendar year to date, beef export shipments have now gone past the one "
            "million tonnes mark, reaching 1,077,644t by the end of August. ")
US = ("Year to date, exports to the US have already reached a phenomenal 335,196t – up "
      "48,300t or 17pc on this period last year, as the US continues to soak up large "
      "volumes of Australian beef in the face of low domestic production.")
BODY = HEADER + MONTHLY
WEATHER_LEAD = ("THIS week's rain event is pressuring supply for beef processors – both short and "
                "potentially, longer-term – pushing some direct consignment offers and saleyards markets higher. ")
WEATHER_OBSERVATION = ("As described in yesterday's weather report, there's been useful rain across a large "
                       "patch of Central and Southern Queensland and Northern NSW over the past week, "
                       "with the prospect of further blanket falls across large parts of eastern and "
                       "southern Australia over the next eight days.")
WEATHER = WEATHER_LEAD + WEATHER_OBSERVATION


class AustraliaExportFactFrameTests(unittest.TestCase):
    def test_export_lean_meat_value_keeps_product_origin_start_month_and_approximation(self):
        body = ("THERE’S been a sharp decline in the value of Australian export lean trimmings "
                "used for hamburger beef this year, falling around 17 percent since January.")
        summary, evidence = native_australia_export_brief(body)
        self.assertIn('호주', summary)
        self.assertIn('저지방 쇠고기 원료', summary)
        self.assertIn('올해 1월 이후 약 17% 하락', summary)
        self.assertTrue(_valid_brief(summary, 'australia', body))
        self.assertTrue(summary_reference_layout(summary, 'australia')['withinLineLimit'])
        changed = body.replace('17 percent', '12 percent').replace('January', 'February')
        revised, _ = native_australia_export_brief(changed)
        self.assertIn('2월 이후 약 12%', revised)
        for bad in (body.replace('Australian', 'Brazilian'),
                    body.replace('falling around', 'expected to fall around'),
                    body.replace('hamburger beef', 'pork'),
                    body.replace('decline', 'increase'),
                    body + ' This report was corrected as incorrect.'):
            with self.subTest(body=bad):
                self.assertIsNone(native_australia_export_brief(bad))

    def test_monthly_actual_source_has_country_period_quantity_rate_and_one_line(self):
        summary, evidence = native_australia_export_brief(BODY)
        self.assertEqual(summary, '호주 8월 전체 시장 쇠고기 수출량은 전월 대비 10% 감소한 12만 8832톤 기록')
        self.assertIn('128,832 tonnes', evidence)
        self.assertIn('10pc decline on the previous month', evidence)
        self.assertIn("Australia's August beef export", evidence)
        self.assertGreaterEqual(len(summary), 40)
        self.assertTrue(_valid_brief(summary, 'australia', BODY))
        layout = summary_reference_layout(summary, 'australia')
        self.assertTrue(layout['withinLineLimit'])
        self.assertLessEqual(layout['estimatedWidthPt'], 466)
        self.assertGreaterEqual(layout['tracking'], -20)

    def test_different_month_amount_and_direction_are_dynamic(self):
        body = BODY.replace('August', 'September').replace('128,832', '142,650')
        body = body.replace('15,000t or 10pc decline', '6500t or 4.8pc increase')
        summary, evidence = native_australia_export_brief(body)
        self.assertIn('9월', summary)
        self.assertIn('14만 2650톤', summary)
        self.assertIn('4.8% 증가', summary)
        self.assertNotIn('12만 8832', summary)
        self.assertIn('142,650 tonnes', evidence)
        self.assertTrue(_valid_brief(summary, 'australia', body))
        self.assertTrue(summary_reference_layout(summary, 'australia')['withinLineLimit'])

    def test_explicit_approximation_is_preserved_not_rounded_into_exact_value(self):
        body = BODY.replace('reached 128,832', 'reached about 128,832').replace('or 10pc', 'or approximately 10pc')
        summary, evidence = native_australia_export_brief(body)
        self.assertIn('약 12만 8832톤', summary)
        self.assertIn('약 10%', summary)
        self.assertIn('approximately 10pc', evidence)
        self.assertTrue(summary_reference_layout(summary, 'australia')['withinLineLimit'])

    def test_monthly_prefix_direction_and_growth_above_one_hundred_are_literal(self):
        body = BODY.replace('a sizeable 15,000t or 10pc decline', 'up 120pc')
        summary, evidence = native_australia_export_brief(body)
        self.assertIn('120% 증가', summary)
        self.assertIn('up 120pc', evidence)
        self.assertTrue(summary_reference_layout(summary, 'australia')['withinLineLimit'])

    def test_calendar_ytd_us_destination_and_annual_comparison_are_not_monthly(self):
        summary, evidence = native_australia_export_brief(HEADER + CALENDAR + US)
        self.assertIn('8월 누적 대미', summary)
        self.assertIn('33만 5196톤', summary)
        self.assertIn('전년 동기비 17% 증가', summary)
        self.assertNotIn('전월', summary)
        self.assertIn('end of August', evidence)
        self.assertIn('exports to the US', evidence)
        self.assertTrue(summary_reference_layout(summary, 'australia')['withinLineLimit'])

    def test_ytd_other_values_month_and_direction_are_not_fixed(self):
        body = (HEADER + CALENDAR + US).replace('August', 'June').replace('335,196', '271,345')
        body = body.replace('up 48,300t or 17pc', 'down 12,000t or 4.2pc')
        summary, evidence = native_australia_export_brief(body)
        self.assertIn('6월 누적 대미', summary)
        self.assertIn('27만 1345톤', summary)
        self.assertIn('4.2% 감소', summary)
        self.assertNotIn('33만 5196', summary)
        self.assertIn('down 12,000t or 4.2pc', evidence)

    def test_forecasts_denials_conditions_and_unconfirmed_figures_are_refused(self):
        for changed in (
            MONTHLY.replace('reached', 'are forecast to reach'),
            MONTHLY.replace('reached', 'did not reach'),
            MONTHLY.replace('10pc decline', '10pc decline if demand stays weak'),
            MONTHLY.replace('10pc decline', '10pc decline according to an unconfirmed estimate'),
            MONTHLY.replace('10pc decline', '10pc decline was not confirmed'),
            MONTHLY.replace('reached 128,832', 'may have reached 128,832'),
        ):
            with self.subTest(changed=changed):
                self.assertIsNone(native_australia_export_brief(HEADER + changed))
        for changed in (US.replace('have already reached', 'are expected to reach'),
                        US.replace('up 48,300t or 17pc', 'not up 48,300t or 17pc'),
                        US.replace('this period last year', 'this period next year')):
            with self.subTest(changed=changed):
                self.assertIsNone(native_australia_export_brief(HEADER + CALENDAR + changed))

    def test_forecast_elsewhere_does_not_erase_an_independent_observed_total(self):
        body = BODY + ' Brazil is expected to export more beef next month.'
        self.assertIsNotNone(native_australia_export_brief(body))

    def test_country_species_destination_and_comparison_cannot_be_substituted(self):
        for body in (
            BODY.replace("Australia's", "New Zealand's"), BODY.replace('beef', 'pork'),
            BODY.replace('to all markets', 'to China'),
            BODY.replace('previous month', 'previous year'),
            BODY.replace('tonnes', 'head'), BODY.replace('128,832', '0'),
            BODY.replace('10pc decline', '110pc decline'),
        ):
            with self.subTest(body=body):
                self.assertIsNone(native_australia_export_brief(body))
        for body in ((HEADER + CALENDAR + US).replace('to the US', 'to China'),
                     (HEADER + CALENDAR + US).replace('this period last year', 'the previous month'),
                     HEADER + US, (HEADER + CALENDAR + US).replace('end of August', 'end of July')):
            with self.subTest(body=body):
                self.assertIsNone(native_australia_export_brief(body))

    def test_conflicting_or_duplicate_monthly_totals_are_not_guessed(self):
        extra = MONTHLY.replace('128,832', '140,000')
        self.assertIsNone(native_australia_export_brief(BODY + ' ' + extra))
        self.assertIsNone(native_australia_export_brief(BODY + ' ' + MONTHLY))

    def test_non_text_and_whitespace_are_safe(self):
        self.assertIsNone(native_australia_export_brief(None))
        self.assertIsNone(native_australia_export_brief(''))
        self.assertIsNotNone(native_australia_export_brief(BODY.replace('Total exports', 'Total\nexports')))

    def test_observed_rain_processing_pressure_preserves_some_and_current_impact(self):
        summary, evidence = native_australia_export_brief(WEATHER)
        self.assertEqual(summary, '호주 강우로 소고기 가공업체 공급 압박, 일부 직거래·가축시장 가격 상승')
        self.assertIn('some direct consignment offers', evidence)
        self.assertIn('potentially, longer-term', evidence)
        self.assertIn('Queensland', evidence)
        self.assertNotIn('전국', summary)
        self.assertNotIn('장기 공급 부족', summary)
        self.assertNotIn('전망', summary)
        self.assertGreaterEqual(len(summary), 40)
        self.assertTrue(_valid_brief(summary, 'australia', WEATHER))
        self.assertTrue(summary_reference_layout(summary, 'australia')['withinLineLimit'])

    def test_rain_forecast_denial_other_cause_species_or_country_cannot_become_observation(self):
        for body in (
            WEATHER.replace("week's rain event is pressuring", "week's forecast rain event may pressure"),
            WEATHER.replace('is pressuring supply', 'is not pressuring supply'),
            WEATHER.replace('pushing some direct', 'not pushing some direct'),
            WEATHER.replace('pushing some direct', 'pushing all direct'),
            WEATHER.replace("week's rain event", "week's heat event"),
            WEATHER.replace('beef processors', 'pork processors'),
            WEATHER.replace("there's been useful rain", 'there may be useful rain'),
            WEATHER.replace("there's been useful rain", 'there has not been useful rain'),
            WEATHER.replace('Central and Southern Queensland and Northern NSW', 'New Zealand'),
            WEATHER.replace('Central and Southern Queensland and Northern NSW', 'the United States'),
            WEATHER_LEAD,
        ):
            with self.subTest(body=body):
                self.assertIsNone(native_australia_export_brief(body))

    def test_explicit_lower_market_direction_is_not_fixed_to_rise(self):
        summary, evidence = native_australia_export_brief(WEATHER.replace('markets higher.', 'markets lower.'))
        self.assertTrue(summary.endswith('가격 하락'))
        self.assertIn('markets lower.', evidence)

    def test_recorded_current_week_processing_original_passes_existing_gates(self):
        snapshot = Path(__file__).resolve().parents[1] / 'output/article_pipeline_originals_20261020_20261020_160043.json'
        if not snapshot.exists():
            self.skipTest('Local original snapshot is not shipped with the application')
        records = json.loads(snapshot.read_text(encoding='utf-8'))
        source = next(item['body'] for item in records if item.get('kind') == 'australia'
                      and "rain event is pressuring supply for beef processors" in item.get('body', ''))
        summary, evidence = native_australia_export_brief(source)
        self.assertTrue(_valid_brief(summary, 'australia', source))
        layout = summary_reference_layout(summary, 'australia')
        self.assertTrue(layout['withinLineLimit'])
        self.assertGreaterEqual(layout['tracking'], -20)
        self.assertLessEqual(layout['estimatedWidthPt'], 466)
        self.assertIn('some direct consignment offers', evidence)

    def test_real_original_snapshot_passes_existing_measurement_and_layout_gates(self):
        snapshot = Path(__file__).resolve().parents[1] / 'output/article_pipeline_originals_20260904_20261020_155927.json'
        if not snapshot.exists():
            self.skipTest('Local original snapshot is not shipped with the application')
        records = json.loads(snapshot.read_text(encoding='utf-8'))
        source = next(item['body'] for item in records if item.get('kind') == 'australia'
                      and 'Total exports for the month to all markets reached' in item.get('body', ''))
        summary, evidence = native_australia_export_brief(source)
        self.assertTrue(_valid_brief(summary, 'australia', source))
        self.assertGreaterEqual(len(summary), 40)
        self.assertTrue(summary_reference_layout(summary, 'australia')['withinLineLimit'])
        self.assertIn('Total exports for the month', evidence)


if __name__ == '__main__':
    unittest.main()
