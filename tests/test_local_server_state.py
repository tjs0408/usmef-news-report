"""Local launcher state tests never start a server, search, model, or worker."""

from copy import deepcopy
import unittest
from unittest.mock import patch

import app as web
from src.report_brief_style import STYLE_VERSION


class LocalServerStateTests(unittest.TestCase):
    def setUp(self):
        self.client = web.app.test_client()
        self.article_jobs = {}
        self.report_jobs = {}
        self.addCleanup(patch.stopall)
        patch.object(web, "ARTICLE_JOBS", self.article_jobs).start()
        patch.object(web, "REPORT_JOBS", self.report_jobs).start()

    def get(self, address="127.0.0.1", **options):
        return self.client.get("/local-server-state", environ_overrides={"REMOTE_ADDR": address}, **options)

    def test_new_style_cannot_reuse_the_previous_browser_draft_namespace(self):
        import re

        storage_keys = []
        for version in ("livestock-brief-v901", "livestock-brief-v902"):
            with patch.object(web, "STYLE_VERSION", version):
                response = self.client.get("/")
            self.assertEqual(response.status_code, 200)
            key = re.search(r'const articleDraftStorageKey = "([^"]+)";',
                            response.get_data(as_text=True)).group(1)
            self.assertEqual(key, f"weekly-overseas-report-{version}-sunday-week-v1")
            storage_keys.append(key)
        self.assertNotEqual(storage_keys[0], storage_keys[1])

    def test_idle_local_response_has_only_public_flags_pid_and_style(self):
        with patch.object(web.os, "getpid", return_value=1234):
            response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {
            "pid": 1234, "styleVersion": STYLE_VERSION,
            "articleBusy": False, "reportBusy": False, "busy": False,
        })
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_ipv6_loopback_is_allowed(self):
        self.assertEqual(self.get("::1").status_code, 200)

    def test_non_loopback_and_unset_addresses_get_no_state(self):
        for address in ("192.168.1.93", "10.0.0.1", "203.0.113.1", "::ffff:127.0.0.1", None):
            with self.subTest(address=address):
                response = self.get(address)
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.data, b"")

    def test_forwarded_header_does_not_override_remote_address(self):
        response = self.get("192.168.1.93", headers={"X-Forwarded-For": "127.0.0.1"})
        self.assertEqual(response.status_code, 404)

    def test_running_or_cancelling_article_is_busy(self):
        for status in ("running", "cancelling"):
            with self.subTest(status=status):
                self.article_jobs["private-article-id"] = {"status": status, "summary": "private text"}
                result = self.get().get_json()
                self.assertTrue(result["articleBusy"])
                self.assertTrue(result["busy"])
                self.assertFalse(result["reportBusy"])

    def test_running_report_is_busy(self):
        self.report_jobs["private-report-id"] = {"status": "running", "reportPath": "private path"}
        result = self.get().get_json()
        self.assertTrue(result["reportBusy"])
        self.assertTrue(result["busy"])
        self.assertFalse(result["articleBusy"])

    def test_terminal_jobs_are_not_busy_or_disclosed_or_changed(self):
        self.article_jobs.update({str(index): {"status": status, "apiKey": "not-a-real-test-secret"}
                                  for index, status in enumerate(("completed", "cancelled", "failed"))})
        self.report_jobs.update({str(index): {"status": status, "reportPath": "test-private-path"}
                                 for index, status in enumerate(("completed", "failed"))})
        before_articles = deepcopy(self.article_jobs)
        before_reports = deepcopy(self.report_jobs)
        response = self.get()
        self.assertFalse(response.get_json()["busy"])
        self.assertNotIn("test-private-path", response.get_data(as_text=True))
        self.assertNotIn("not-a-real-test-secret", response.get_data(as_text=True))
        self.assertEqual(self.article_jobs, before_articles)
        self.assertEqual(self.report_jobs, before_reports)

    def test_post_cannot_change_jobs(self):
        response = self.client.post("/local-server-state", json={"busy": False})
        self.assertEqual(response.status_code, 405)
        self.assertEqual(self.article_jobs, {})
        self.assertEqual(self.report_jobs, {})

    def test_busy_snapshots_use_existing_locks(self):
        from unittest.mock import MagicMock
        article_lock = MagicMock()
        report_lock = MagicMock()
        with patch.object(web, "ARTICLE_JOBS_LOCK", article_lock), patch.object(web, "REPORT_JOBS_LOCK", report_lock):
            self.assertEqual(self.get().status_code, 200)
        article_lock.__enter__.assert_called_once_with()
        article_lock.__exit__.assert_called_once()
        report_lock.__enter__.assert_called_once_with()
        report_lock.__exit__.assert_called_once()


if __name__ == "__main__":
    unittest.main()
