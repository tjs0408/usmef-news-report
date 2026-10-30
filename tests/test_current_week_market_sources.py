from datetime import date
import unittest
from unittest.mock import Mock, patch

import requests

from src import current_week_market_sources as m


START, END = date(2026, 10, 18), date(2026, 10, 24)


def report(stamp="October 19, 2026", *, choice="371.58", select="359.91"):
    return f"""TCFA Daily Market Summary - {stamp}

USDA BEEF CUT OUT
-----------------------------------------------------------------------------
CH 600/900:   ${choice}   DN    -0.73    SL 600/900:   ${select}   UP     6.86
CH/SL Spread:                 11.67

SLAUGHTER - 1:00 P.M.
Today:       105,000        W-T-D:              0
Week:        106,000        Last Week:          0
Year Ago:     90,274        Last Year:          0
"""


def page(block=None, *, title="Market - Texas Cattle Feeders Association", address=True):
    return (f"<html><head><title>{title}</title></head><body>"
            "<nav>Unrelated promotion cattle prices 999 dollars</nav>"
            f"<pre>{report() if block is None else block}</pre>"
            + ("<footer>5501 I-40 West * Amarillo, Texas 79106 * 806-358-3681</footer>" if address else "")
            + "</body></html>")


def response(html=None, *, url=m.TCFA_MARKET_URL):
    return Mock(text=page() if html is None else html, url=url)


class CurrentWeekMarketSourcesTests(unittest.TestCase):
    def test_fetch_public_dated_market_block_without_navigation(self):
        with patch.object(m.requests, "get", return_value=response()) as get:
            actual = m.fetch_current_market_source("us", START, END)
        get.assert_called_once_with(m.TCFA_MARKET_URL, timeout=(3, 6))
        self.assertEqual(actual["publishedAt"], date(2026, 10, 19))
        self.assertEqual(actual["publishedDate"], actual["publishedAt"])
        self.assertEqual(actual["language"], "en")
        self.assertEqual(actual["country"], "US")
        self.assertIn("$371.58", actual["body"])
        self.assertIn("105,000", actual["body"])
        self.assertNotIn("999 dollars", actual["body"])
        self.assertNotIn("Amarillo", actual["body"])

    def test_read_values_from_current_source_not_fixed_constants(self):
        actual = m._tcfa_summary(page(report("October 20, 2026", choice="375.41", select="362.13")), START, END)
        self.assertEqual(actual["publishedAt"], date(2026, 10, 20))
        self.assertIn("$375.41", actual["body"])
        self.assertNotIn("$371.58", actual["body"])

    def test_stale_future_or_invalid_report_date_is_not_relabelled(self):
        for stamp in ("October 16, 2026", "October 25, 2026", "February 31, 2026", "Unknown 19, 2026"):
            with self.subTest(stamp=stamp):
                self.assertIsNone(m._tcfa_summary(page(report(stamp)), START, END))

    def test_unrelated_dated_block_and_page_date_do_not_supply_date(self):
        html = page(report("October 16, 2026")) + "<p>Updated October 19, 2026</p><pre>TCFA Daily Volume Price - October 19, 2026</pre>"
        self.assertIsNone(m._tcfa_summary(html, START, END))

    def test_missing_identity_country_or_market_content_fails_closed(self):
        for html in (page(title="Unknown Blog"), page(address=False),
                     page(report().replace("USDA BEEF CUT OUT", "Market Advertisement")),
                     page(report().replace("SLAUGHTER", "COMMENTARY")),
                     page(report().replace("SL 600/900:", "Other category:"))):
            with self.subTest(html=html[:90]):
                self.assertIsNone(m._tcfa_summary(html, START, END))

    def test_date_and_data_must_be_in_same_pre_block(self):
        html = page("TCFA Daily Market Summary - October 19, 2026") + "<pre>" + "\n".join(report().splitlines()[1:]) + "</pre>"
        self.assertIsNone(m._tcfa_summary(html, START, END))

    def test_network_error_or_unrelated_redirect_returns_none(self):
        with patch.object(m.requests, "get", side_effect=requests.Timeout):
            self.assertIsNone(m.fetch_current_market_source("us", START, END))
        for url in ("https://example.org/market.html", "https://www.tcfa.org/login", "http://www.tcfa.org/market.html"):
            with self.subTest(url=url), patch.object(m.requests, "get", return_value=response(url=url)):
                self.assertIsNone(m.fetch_current_market_source("us", START, END))

    def test_http_error_or_oversized_response_returns_none(self):
        failed = response()
        failed.raise_for_status.side_effect = requests.HTTPError("503")
        for reply in (failed, response("a" * 2_000_001)):
            with patch.object(m.requests, "get", return_value=reply):
                self.assertIsNone(m.fetch_current_market_source("us", START, END))

    def test_other_species_and_invalid_range_do_not_request(self):
        with patch.object(m.requests, "get") as get:
            for key in ("us_pork", "us_chicken", "brazil_chicken", "domestic", "us_egg"):
                self.assertIsNone(m.fetch_current_market_source(key, START, END))
            self.assertIsNone(m.fetch_current_market_source("us", END, START))
            get.assert_not_called()


class NativeTcfaBriefTests(unittest.TestCase):
    def test_actual_values_and_directions_are_source_grounded(self):
        summary, evidence = m.native_tcfa_brief(report())
        self.assertEqual(summary, "미국 쇠고기 도매가격 지표(100 파운드당)는 초이스 등급 371.58달러로 0.73달러 하락, 셀렉트 등급 359.91달러로 6.86달러 상승")
        self.assertGreaterEqual(len(summary), 40)
        self.assertLessEqual(len(summary), 95)
        self.assertIn("CH 600/900:   $371.58   DN    -0.73", evidence)
        self.assertIn("100 파운드당", summary)
        self.assertNotIn("전일", summary)
        self.assertNotIn("전주", summary)

    def test_values_directions_and_date_are_not_fixed(self):
        body = report("October 20, 2026", choice="400.25", select="380.16")
        body = body.replace("DN    -0.73", "UP    +1.21").replace("UP     6.86", "DN     -2.19")
        summary, evidence = m.native_tcfa_brief(body)
        self.assertIn("초이스 등급 400.25달러로 1.21달러 상승", summary)
        self.assertIn("셀렉트 등급 380.16달러로 2.19달러 하락", summary)
        self.assertIn("October 20, 2026", evidence)
        self.assertNotIn("371.58", summary)

    def test_direction_and_sign_contradiction_is_rejected(self):
        for body in (report().replace("DN    -0.73", "DN    +0.73"),
                     report().replace("DN    -0.73", "DN    0.73"),
                     report().replace("UP     6.86", "UP     -6.86")):
            with self.subTest(body=body):
                self.assertIsNone(m.native_tcfa_brief(body))

    def test_zero_change_is_not_invented_as_increase_or_decrease(self):
        body = report().replace("DN    -0.73", "DN    -0.00").replace("UP     6.86", "UP     0.00")
        summary, _ = m.native_tcfa_brief(body)
        self.assertEqual(summary.count("보합"), 2)
        self.assertNotIn("상승", summary)
        self.assertNotIn("하락", summary)

    def test_carcass_index_is_not_misread_as_boxed_beef(self):
        body = report().replace("\nSLAUGHTER", "\nCARCASS EQUIVALENT INDEX\nCH 600/900: $344.98 UP 0.99 SL 600/900: $328.88 UP 4.78\nSLAUGHTER")
        summary, _ = m.native_tcfa_brief(body)
        self.assertIn("371.58", summary)
        self.assertNotIn("344.98", summary)
        invalid = body.replace("CH 600/900:   $371.58   DN    -0.73", "Choice record unavailable")
        self.assertIsNone(m.native_tcfa_brief(invalid))

    def test_missing_date_price_or_ambiguous_duplicate_is_rejected(self):
        for body in (report().replace("TCFA Daily Market Summary - October 19, 2026", "USDA Report"),
                     report().replace("USDA BEEF CUT OUT", "Unrelated prices"),
                     report(choice="0.00"),
                     report().replace("CH/SL Spread:", "CH 600/900: $400.00 UP 1.00\nCH/SL Spread:")):
            with self.subTest(body=body[:100]):
                self.assertIsNone(m.native_tcfa_brief(body))

    def test_malformed_number_punctuation_does_not_become_a_valid_amount(self):
        for body in (report(choice="371,,58"), report(choice="3,71.58"),
                     report().replace("DN    -0.73", "DN    -0,,73")):
            with self.subTest(body=body[:180]):
                self.assertIsNone(m.native_tcfa_brief(body))


if __name__ == "__main__":
    unittest.main()
