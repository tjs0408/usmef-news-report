"""Batch row queries reuse one request-local archive without stale upload data."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

from src import template_report as t


TODAY = date(2026, 10, 26)
QUERIES = {
    'market': t.find_pending_report_dates,
    'eu_germany': t.find_pending_eu_germany_rows,
    'japan_egg': t.find_pending_japan_egg_rows,
    'us_egg': t.find_pending_us_egg_rows,
    'us_egg_consumer_price': t.find_pending_us_egg_consumer_price_rows,
    'brazil_chicken': t.find_pending_brazil_chicken_rows,
    'us_chicken': t.find_pending_us_chicken_rows,
    'australia_beef': t.find_pending_australia_beef_rows,
}


def serial(value):
    return str((value - date(1899, 12, 30)).days)


def fixture_cells():
    cells = {}
    for config in t.MARKET_SHEETS:
        cells[config['sheetName']] = {
            config['dateColumn'] + '8': serial(date(2026, 10, 9)),
            config['currentColumn'] + '8': '0',
            config['dateColumn'] + '9': serial(date(2026, 10, 16)),
            config['dateColumn'] + '10': serial(date(2026, 10, 23)),
        }
    for config, date_column, first in (
        (t.EU_GERMANY_SHEET, 'dateColumn', 8),
        (t.JAPAN_EGG_SHEET, 'dateColumn', 6),
        (t.US_EGG_SHEET, 'dateColumn', 6),
        (t.BRAZIL_CHICKEN_SHEET, 'dateColumn', 6),
        (t.US_CHICKEN_SHEET, 'dateColumn', 6),
        (t.AUSTRALIA_BEEF_SHEET, 'dateColumn', 8),
    ):
        values = {config[date_column] + str(first): serial(date(2026, 10, 9)),
                  config[date_column] + str(first + 1): serial(date(2026, 10, 16)),
                  config[date_column] + str(first + 2): serial(date(2026, 10, 30))}
        for key in ('currentColumn', 'inventoryColumn', 'priceColumn', 'exchangeColumn',
                    'slaughterColumn', 'eyciColumn'):
            if key in config:
                values[config[key] + str(first)] = '0'
        cells[config['sheetName']] = values
    # The graph and US-egg market are two queries on this very same worksheet.
    graph = t.US_EGG_CONSUMER_PRICE_GRAPH
    for column in graph['yearColumns']:
        for row in range(graph['monthStartRow'], graph['monthEndRow'] + 1):
            cells[graph['sheetName']][column + str(row)] = '3.25'
    for cell in ('AR11', 'AR12', 'AR13'):
        cells[graph['sheetName']].pop(cell)
    # Australia becomes available the day after Friday, preserving that rule.
    cells[t.AUSTRALIA_BEEF_SHEET['sheetName']]['EZ10'] = serial(date(2026, 10, 23))
    return cells


def write_fixture(path, cells):
    ns, relns, packns = t.SPREADSHEET_NAMESPACE, t.RELATIONSHIP_NAMESPACE, t.PACKAGE_RELATIONSHIP_NAMESPACE
    workbook = ET.Element('{' + ns + '}workbook')
    sheets = ET.SubElement(workbook, '{' + ns + '}sheets')
    relationships = ET.Element('{' + packns + '}Relationships')
    with ZipFile(path, 'w') as archive:
        for index, (name, values) in enumerate(cells.items(), 1):
            identity = 'rId' + str(index)
            ET.SubElement(sheets, '{' + ns + '}sheet', {'name': name, '{' + relns + '}id': identity})
            target = 'worksheets/sheet' + str(index) + '.xml'
            ET.SubElement(relationships, '{' + packns + '}Relationship', {'Id': identity, 'Target': target})
            worksheet = ET.Element('{' + ns + '}worksheet')
            data = ET.SubElement(worksheet, '{' + ns + '}sheetData')
            for reference, value in values.items():
                row = ET.SubElement(data, '{' + ns + '}row')
                cell = ET.SubElement(row, '{' + ns + '}c', {'r': reference})
                ET.SubElement(cell, '{' + ns + '}v').text = value
            archive.writestr('xl/' + target, ET.tostring(worksheet))
        archive.writestr('xl/workbook.xml', ET.tostring(workbook))
        archive.writestr('xl/_rels/workbook.xml.rels', ET.tostring(relationships))


class PendingRowQueryBatchTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'uploaded.xlsx'
        self.cells = fixture_cells()
        write_fixture(self.path, self.cells)

    def test_batch_equals_individual_public_queries_without_reordering(self):
        expected = {key: query(self.path, TODAY) for key, query in QUERIES.items()}
        actual = t.find_pending_rows(self.path, TODAY)
        self.assertEqual(actual, expected)
        self.assertEqual([len(actual[key]) for key in QUERIES], [2, 1, 1, 1, 2, 1, 1, 2])
        self.assertEqual([row['row'] for row in actual['australia_beef']], [9, 10])
        self.assertEqual(actual['us_egg_consumer_price'][0]['month'], '2026-09-01')
        self.assertEqual(actual['us_egg_consumer_price'][1]['month'], '2026-10-01')

    def test_eight_queries_share_one_zip_one_metadata_lookup_and_eight_sheets(self):
        with patch.object(t, 'ZipFile', wraps=t.ZipFile) as archives, \
             patch.object(t, '_find_sheet_paths', wraps=t._find_sheet_paths) as metadata, \
             patch.object(t, '_read_sheet_cell_values', wraps=t._read_sheet_cell_values) as values:
            for query in QUERIES.values():
                query(self.path, TODAY)
            self.assertEqual((archives.call_count, metadata.call_count, values.call_count), (8, 8, 9))
            archives.reset_mock(); metadata.reset_mock(); values.reset_mock()
            t.find_pending_rows(self.path, TODAY)
            self.assertEqual((archives.call_count, metadata.call_count, values.call_count), (1, 1, 8))
            self.assertEqual(len({call.args[1] for call in values.call_args_list}), 8)

    def test_same_path_replaced_by_new_upload_has_no_cached_old_rows(self):
        first = t.find_pending_rows(self.path, TODAY)
        self.cells[t.JAPAN_EGG_SHEET['sheetName']]['Y7'] = '315'
        self.cells[t.US_EGG_SHEET['sheetName']]['AR11'] = '4.25'
        write_fixture(self.path, self.cells)
        second = t.find_pending_rows(self.path, TODAY)
        self.assertEqual(len(first['japan_egg']), 1)
        self.assertEqual(second['japan_egg'], [])
        self.assertEqual(len(first['us_egg_consumer_price']), 2)
        self.assertEqual(len(second['us_egg_consumer_price']), 1)

    def test_returned_rows_are_request_local_and_mutation_cannot_poison_next_upload(self):
        first = t.find_pending_rows(self.path, TODAY)
        first['market'][0]['row'] = -100
        first['japan_egg'].clear()
        second = t.find_pending_rows(self.path, TODAY)
        self.assertEqual(second['market'][0]['row'], 9)
        self.assertEqual(len(second['japan_egg']), 1)

    def test_different_upload_paths_and_simultaneous_queries_do_not_share_rows(self):
        other = Path(self.directory.name) / 'another-upload.xlsx'
        self.cells[t.JAPAN_EGG_SHEET['sheetName']]['Y7'] = '315'
        write_fixture(other, self.cells)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = list(pool.map(lambda path: t.find_pending_rows(path, TODAY), [self.path, other]))
        self.assertEqual(len(first['japan_egg']), 1)
        self.assertEqual(second['japan_egg'], [])

    def test_request_date_changes_are_not_hidden_by_a_cross_request_cache(self):
        friday = t.find_pending_rows(self.path, date(2026, 10, 23))
        saturday = t.find_pending_rows(self.path, date(2026, 10, 24))
        self.assertEqual([item['row'] for item in friday['australia_beef']], [9])
        self.assertEqual([item['row'] for item in saturday['australia_beef']], [9, 10])

    def test_archive_closes_when_a_sheet_query_fails_and_failure_is_not_cached(self):
        opened = []
        real_archive = t.ZipFile
        def capture(*args, **kwargs):
            archive = real_archive(*args, **kwargs)
            opened.append(archive)
            return archive
        with patch.object(t, 'ZipFile', side_effect=capture), \
             patch.object(t, '_read_sheet_cell_values', side_effect=ValueError('invalid worksheet')):
            with self.assertRaisesRegex(ValueError, 'invalid worksheet'):
                t.find_pending_rows(self.path, TODAY)
        self.assertEqual(len(opened), 1)
        self.assertIsNone(opened[0].fp)
        self.assertEqual(len(t.find_pending_rows(self.path, TODAY)['market']), 2)

    def test_bad_zip_and_missing_required_sheet_still_raise_instead_of_empty_success(self):
        self.path.write_bytes(b'not a workbook')
        with self.assertRaises(BadZipFile):
            t.find_pending_rows(self.path, TODAY)
        del self.cells[t.JAPAN_EGG_SHEET['sheetName']]
        write_fixture(self.path, self.cells)
        with self.assertRaises(KeyError):
            t.find_pending_rows(self.path, TODAY)

    def test_report_job_uses_the_batch_once_and_still_cleans_its_staged_upload(self):
        import app as web
        empty = {key: [] for key in QUERIES}
        with patch.object(web, 'find_pending_rows', return_value=empty) as query, \
             patch.object(web, '_update_job'), \
             patch.object(web, '_run_with_timed_progress'), \
             patch.object(web, '_complete_job_with_hwp') as complete:
            web._run_report_job('batch-test-only', self.path)
        query.assert_called_once()
        self.assertEqual(query.call_args.args[0], self.path)
        complete.assert_called_once()
        self.assertFalse(self.path.exists())

    def test_report_job_keeps_failure_cleanup_when_batch_lookup_fails(self):
        import app as web
        with patch.object(web, 'find_pending_rows', side_effect=RuntimeError('query failed')), \
             patch.object(web, '_update_job') as update, \
             patch.object(web.app.logger, 'exception'), \
             patch.object(web, '_complete_job_with_hwp') as complete:
            web._run_report_job('batch-test-only', self.path)
        self.assertFalse(self.path.exists())
        complete.assert_not_called()
        self.assertTrue(any(call.kwargs.get('status') == 'failed' for call in update.call_args_list))


if __name__ == '__main__':
    unittest.main()
