"""Historical USDA PDFs require independently matching original dates."""
from datetime import date
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch
import unittest

from src import livestock_article_draft as d


START, END = date(2026, 10, 4), date(2026, 10, 10)
ARCHIVED = 'https://mymarketnews.ams.usda.gov/filerepo/sites/default/files/2843/2026-10-09/1357156/ams_2843_01657.pdf'


def egg_body(day=9):
    return ('Daily National Shell Egg Index Report (5-day rolling average) Agricultural Marketing Service '
            f'Fri Oct {day}, 2026 Report for: 10/{day:02d}/2026 '
            'National FOB shell egg weighted average prices are lower. '
            'Retail demand is moderate. Offerings are moderate on mostly moderate supplies. '
            'NEGOTIATED REGIONAL VOLUME MOVEMENT 999.99')


def listing(*, slug='2843', published='10-09-2026', reported='2026-10-09', url=ARCHIVED):
    return ('<table id="filerepo-reports-table"><tbody><tr>'
            f'<td>{slug}</td><td>AMS_{slug}</td><td>Daily National Shell Egg Index Report</td>'
            f'<td>{published} 07:16 am</td><td>{reported}</td><td>Final</td>'
            f'<td><a href="{url}">view report</a></td></tr></tbody></table>')


class UsdaPublicArchiveTests(unittest.TestCase):
    def test_current_pdf_outside_week_uses_discovered_archived_original(self):
        def pdf(url):
            return egg_body(13 if url == d.USDA_DAILY_REPORTS['us_egg'][0] else 9)
        with patch.object(d, '_public_pdf_text', side_effect=pdf), \
             patch.object(d, '_usda_archive_page', return_value=listing()) as archive:
            found = d._official_market_article(d.SPECS_BY_KEY['us_egg'], START, END)
        self.assertEqual(found['url'], ARCHIVED)
        self.assertEqual(found['publishedDate'], date(2026, 10, 9))
        self.assertEqual(found['sourceMethod'], 'official')
        self.assertNotIn('999.99', found['briefBody'])
        query = parse_qs(urlparse(archive.call_args.args[0]).query)
        self.assertEqual(query['field_slug_id_value'], ['2843'])
        self.assertEqual(query['field_report_date_end_value'], ['2026-10-09'])

    def test_archive_listing_cannot_relabel_different_pdf_date(self):
        with patch.object(d, '_usda_archive_page', side_effect=[listing()] + [''] * 4), \
             patch.object(d, '_public_pdf_text', return_value=egg_body(13)) as pdf:
            self.assertIsNone(d._usda_archive_article(d.SPECS_BY_KEY['us_egg'], START, END))
        pdf.assert_called_once_with(ARCHIVED)

    def test_archive_listing_publication_must_itself_be_in_week(self):
        with patch.object(d, '_usda_archive_page', side_effect=[listing(published='10-13-2026')] + [''] * 4), \
             patch.object(d, '_public_pdf_text') as pdf:
            self.assertIsNone(d._usda_archive_article(d.SPECS_BY_KEY['us_egg'], START, END))
        pdf.assert_not_called()

    def test_unavailable_archive_stops_after_one_bounded_request(self):
        with patch.object(d, '_usda_archive_page', return_value=None) as archive, \
             patch.object(d, '_public_pdf_text') as pdf:
            self.assertIsNone(d._usda_archive_article(d.SPECS_BY_KEY['us_egg'], START, END))
        self.assertEqual(archive.call_count, 1)
        pdf.assert_not_called()

    def test_rejects_wrong_slug_or_external_document_link(self):
        for html in (listing(slug='2740'), listing(url='https://untrusted.example/report.pdf')):
            with self.subTest(html=html), \
                 patch.object(d, '_usda_archive_page', side_effect=[html] + [''] * 4), \
                 patch.object(d, '_public_pdf_text') as pdf:
                self.assertIsNone(d._usda_archive_article(d.SPECS_BY_KEY['us_egg'], START, END))
                pdf.assert_not_called()

    def test_chicken_report_uses_its_own_slug_and_header(self):
        spec = d.SPECS_BY_KEY['us_chicken']
        url = 'https://mymarketnews.ams.usda.gov/filerepo/sites/default/files/2740/2026-10-09/123/ams_2740_123.pdf'
        body = ('Daily National Broiler Market-At-A-Glance Agricultural Marketing Service Fri Oct 9, 2026 '
                'Reported for Oct 9, 2026 Broiler chicken prices are steady. Supplies are moderate. '
                'Source: USDA AMS')
        with patch.object(d, '_usda_archive_page', return_value=listing(slug='2740', url=url)) as archive, \
             patch.object(d, '_public_pdf_text', return_value=body):
            found = d._usda_archive_article(spec, START, END)
        self.assertEqual(found['url'], url)
        self.assertEqual(found['publishedDate'], date(2026, 10, 9))
        self.assertEqual(parse_qs(urlparse(archive.call_args.args[0]).query)['field_slug_id_value'], ['2740'])


if __name__ == '__main__':
    unittest.main()
