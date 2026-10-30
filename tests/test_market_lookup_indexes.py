"""Request-local market indexes preserve report and prior-day lookup policy."""
from datetime import date, timedelta
import json
import unittest
from unittest.mock import patch

from src import crawler


def report(day, publication=None, name='original'):
    return {'reportDate': day, 'publishedDate': publication or day,
            'url': 'https://example.org/' + name, 'name': name}


class MarketLookupIndexTests(unittest.TestCase):
    def test_latest_correction_and_equal_publication_first_match_are_preserved(self):
        day = date(2026, 10, 9)
        first = report(day, day + timedelta(days=2), 'first-correction')
        equal = report(day, day + timedelta(days=2), 'same-day-correction')
        old = report(day, day, 'original')
        other = report(day - timedelta(days=7), name='other-week')
        reports = [first, other, equal, old]
        indexed = crawler._index_usda_reports(reports, 'reportDate')
        self.assertIs(indexed[day], first)
        for target in (day, day - timedelta(days=7), day + timedelta(days=7)):
            self.assertIs(indexed.get(target), crawler._select_usda_report(reports, 'reportDate', target))

    def test_unsorted_archives_match_original_selector_for_both_date_fields(self):
        day = date(2026, 10, 9)
        reports = [report(day + timedelta(days=n), day + timedelta(days=n + delay), str((n, delay)))
                   for n, delay in ((14, 0), (0, 0), (7, 1), (0, 2), (7, 0), (0, 2))]
        for field in ('reportDate', 'publishedDate'):
            indexed = crawler._index_usda_reports(reports, field)
            for offset in range(-1, 24):
                target = day + timedelta(days=offset)
                self.assertIs(indexed.get(target), crawler._select_usda_report(reports, field, target))

    def test_empty_and_fresh_indexes_do_not_keep_a_previously_selected_revision(self):
        self.assertEqual(crawler._index_usda_reports([], 'reportDate'), {})
        day = date(2026, 10, 9)
        original = report(day)
        corrected = report(day, day + timedelta(days=1), 'corrected')
        before = crawler._index_usda_reports([original], 'reportDate')
        after = crawler._index_usda_reports([original, corrected], 'reportDate')
        self.assertIs(before[day], original)
        self.assertIs(after[day], corrected)
        self.assertNotIn(day + timedelta(days=1), after)

    def test_one_index_pass_replaces_52_full_archive_scans(self):
        class CountedReport(dict):
            reads = 0

            def __getitem__(self, key):
                type(self).reads += 1
                return super().__getitem__(key)

        first = date(2000, 1, 1)
        reports = [CountedReport(report(first + timedelta(days=n), name=str(n))) for n in range(5200)]
        targets = [first + timedelta(days=4000 + 7 * n) for n in range(52)]
        old_results = [crawler._select_usda_report(reports, 'reportDate', target) for target in targets]
        old_reads = CountedReport.reads
        CountedReport.reads = 0
        index = crawler._index_usda_reports(reports, 'reportDate')
        new_results = [index.get(target) for target in targets]
        new_reads = CountedReport.reads
        self.assertEqual(new_results, old_results)
        self.assertEqual(new_reads, len(reports))
        self.assertGreater(old_reads, new_reads * 50)

    def test_bulk_egg_fetch_indexes_each_source_once_and_keeps_corrected_pdf(self):
        first_week = date(2026, 10, 9)
        next_week = first_week + timedelta(days=7)
        inventory_day = first_week - timedelta(days=4)
        corrected = report(inventory_day, first_week, 'corrected-inventory')
        archive = {
            '1427': [report(inventory_day), corrected, report(next_week - timedelta(days=4))],
            '2848': [report(first_week), report(next_week)],
        }
        with patch.object(crawler, '_find_usda_report_documents', side_effect=lambda slug: archive[slug]), \
             patch.object(crawler, '_index_usda_reports', wraps=crawler._index_usda_reports) as index, \
             patch.object(crawler, '_select_usda_report', side_effect=AssertionError('bulk scan')), \
             patch.object(crawler, '_download_usda_bytes', side_effect=lambda url: url.encode()) as download, \
             patch.object(crawler, '_extract_usda_inventory_total', return_value=100.0), \
             patch.object(crawler, '_extract_usda_large_average_price', return_value=250.0):
            values = crawler.fetch_usda_us_egg_data({first_week, next_week})
        self.assertEqual(index.call_count, 2)
        self.assertEqual(set(values), {first_week, next_week})
        self.assertEqual(values[first_week], {'weeklyInventory': 100.0, 'largeAveragePrice': 250.0})
        self.assertEqual(download.call_args_list[0].args[0], corrected['url'])

    def test_bulk_chicken_fetch_uses_two_indexes_not_per_week_scans(self):
        day = date(2026, 10, 9)
        targets = {day + timedelta(days=7 * n) for n in range(4)}
        archive = [report(target) for target in targets]
        with patch.object(crawler, '_find_usda_report_documents', return_value=archive), \
             patch.object(crawler, '_index_usda_reports', wraps=crawler._index_usda_reports) as index, \
             patch.object(crawler, '_select_usda_report', side_effect=AssertionError('bulk scan')), \
             patch.object(crawler, '_download_usda_bytes', return_value=b'pdf'), \
             patch.object(crawler, '_extract_usda_young_chicken_wtd', return_value=500.0), \
             patch.object(crawler, '_extract_usda_wog_weighted_average', return_value=123.0):
            values = crawler.fetch_usda_us_chicken_data(targets)
        self.assertEqual(index.call_count, 2)
        self.assertEqual(set(values), targets)

    def test_missing_old_reports_still_error_but_unpublished_future_is_deferred(self):
        day = date(2026, 10, 9)
        for fetch in (crawler.fetch_usda_us_egg_data, crawler.fetch_usda_us_chicken_data):
            with self.subTest(fetch=fetch.__name__), \
                 patch.object(crawler, '_find_usda_report_documents', return_value=[report(day)]), \
                 patch.object(crawler, '_download_usda_bytes') as download:
                self.assertEqual(fetch({day + timedelta(days=14)}), {})
                download.assert_not_called()
                with self.assertRaises(RuntimeError):
                    fetch({day - timedelta(days=14)})

    def test_previous_business_day_matches_scan_for_unsorted_sparse_rates(self):
        days = [date(2026, 10, 19), date(2026, 10, 5), date(2026, 10, 12)]
        source = {day: float(1200 + n) for n, day in enumerate(days)}
        targets = {date(2026, 10, 1) + timedelta(days=n) for n in range(25)}
        payload = json.dumps({'items': [{'date': day.isoformat(), 'saleBaseRate': value}
                                        for day, value in source.items()], 'hasNext': False}).encode()
        expected = {}
        for target in targets:
            prior = [day for day in source if day <= target]
            if prior:
                expected[target] = source[max(prior)]
        with patch.object(crawler, '_download_exchange_rate_bytes', return_value=payload):
            self.assertEqual(crawler._fetch_naver_exchange_rates(targets, 'USD', True), expected)
            exact = crawler._fetch_naver_exchange_rates(targets, 'USD', False)
            self.assertEqual(exact, source)

    def test_empty_target_sets_do_not_read_archives(self):
        with patch.object(crawler, '_find_usda_report_documents') as archive:
            self.assertEqual(crawler.fetch_usda_us_egg_data(set()), {})
            self.assertEqual(crawler.fetch_usda_us_chicken_data(set()), {})
        archive.assert_not_called()


if __name__ == '__main__':
    unittest.main()
