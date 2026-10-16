"""All report currencies use the latest published rate on or before the target."""

from datetime import date
import json
import unittest
from unittest.mock import patch

from src import crawler


def response(items, *, has_next=False, cursor=None):
    return json.dumps({
        "items": [{"date": day, "saleBaseRate": rate} for day, rate in items],
        "hasNext": has_next,
        "cursor": cursor,
    }).encode("utf-8")


CURRENCY_READERS = (
    ("USD", crawler.fetch_usd_krw_exchange_rates),
    ("EUR", crawler.fetch_eur_krw_exchange_rates),
    ("JPY", crawler.fetch_jpy_krw_exchange_rates),
    ("BRL", crawler.fetch_brl_krw_exchange_rates),
    ("AUD", crawler.fetch_aud_krw_exchange_rates),
)


class ExchangeRateTests(unittest.TestCase):
    def test_all_currencies_use_previous_published_day_when_missing(self):
        payload = response([
            ("2026-09-28", "1,360.0"),
            ("2026-09-23", "1,359.0"),
            ("2026-09-22", "1,350.0"),
        ])
        target = date(2026, 9, 25)
        for currency, read in CURRENCY_READERS:
            with self.subTest(currency=currency), patch.object(
                crawler, "_download_exchange_rate_bytes", return_value=payload
            ) as download:
                self.assertEqual(read({target}), {target: 1359.0})
                self.assertEqual(download.call_args.args[1], currency)

    def test_exact_day_takes_priority_over_previous_day(self):
        exact, holiday = date(2026, 9, 23), date(2026, 9, 25)
        payload = response([
            ("2026-09-23", "1,359.0"),
            ("2026-09-22", "1,350.0"),
        ])
        for currency, read in CURRENCY_READERS:
            with self.subTest(currency=currency), patch.object(
                crawler, "_download_exchange_rate_bytes", return_value=payload
            ):
                self.assertEqual(read({exact, holiday}), {exact: 1359.0, holiday: 1359.0})

    def test_never_uses_a_later_day_or_invents_missing_history(self):
        payload = response([("2026-09-28", "1,360.0")])
        for currency, read in CURRENCY_READERS:
            with self.subTest(currency=currency), patch.object(
                crawler, "_download_exchange_rate_bytes", return_value=payload
            ):
                self.assertEqual(read({date(2026, 9, 25)}), {})

    def test_previous_rate_can_be_found_on_next_page(self):
        pages = [
            response([("2026-09-28", "1,360.0")], has_next=True, cursor="next-page"),
            response([("2026-09-23", "1,359.0")]),
        ]
        with patch.object(crawler, "_download_exchange_rate_bytes", side_effect=pages) as download:
            target = date(2026, 9, 25)
            self.assertEqual(crawler.fetch_usd_krw_exchange_rates({target}), {target: 1359.0})
            self.assertEqual(download.call_count, 2)
            self.assertIn("cursor=next-page", download.call_args.args[0])

    def test_no_requested_dates_skips_download(self):
        with patch.object(crawler, "_download_exchange_rate_bytes") as download:
            for _, read in CURRENCY_READERS:
                self.assertEqual(read(set()), {})
            download.assert_not_called()

    def test_network_failure_is_not_replaced_with_a_rate(self):
        with patch.object(
            crawler, "_download_exchange_rate_bytes", side_effect=RuntimeError("unavailable")
        ):
            with self.assertRaisesRegex(RuntimeError, "unavailable"):
                crawler.fetch_usd_krw_exchange_rates({date(2026, 9, 25)})


if __name__ == "__main__":
    unittest.main()
