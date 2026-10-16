"""Offline cancellation, reload races and child-worker draining regressions."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Event, Lock, Thread
from unittest.mock import MagicMock, patch
import unittest

import app as web
from src import livestock_article_draft as drafts
from src import overseas_article_digest as source
from src.article_cancellation import (
    ArticleDraftCancelled, article_cancellation_scope, cancellation_checkpoint,
    cancellable_lock, check_article_cancelled, map_article_tasks, submit_article_task,
)


class CancellationTests(unittest.TestCase):
    def test_pre_cancelled_collector_never_starts_model_or_source(self):
        event = Event()
        event.set()
        with patch.object(source, "_ensure_ollama_ready") as model, patch.object(drafts, "_usmef_pair") as finder:
            with self.assertRaises(ArticleDraftCancelled):
                drafts.collect_weekly_livestock_report_draft(date(2026, 10, 1), cancel_event=event)
        model.assert_not_called()
        finder.assert_not_called()
        check_article_cancelled()  # cancelled context must not leak to next job

    def test_pending_and_nested_pool_work_does_not_start_after_cancellation(self):
        event, entered, release = Event(), Event(), Event()
        calls = []
        def first():
            entered.set()
            self.assertTrue(release.wait(2))
            check_article_cancelled()
        def nested():
            with ThreadPoolExecutor(max_workers=1) as children:
                return list(map_article_tasks(children, lambda value: calls.append(value), ["child"]))
        with ThreadPoolExecutor(max_workers=1) as pool, article_cancellation_scope(event):
            running = submit_article_task(pool, first)
            queued = submit_article_task(pool, nested)
            self.assertTrue(entered.wait(2))
            event.set()
            release.set()
            for future in (running, queued):
                with self.assertRaises(ArticleDraftCancelled):
                    future.result(timeout=2)
            event.clear()  # leave scope normally
        self.assertEqual(calls, [])
        # Cancellation is propagated to nested pools, not merely top-level work.
        with ThreadPoolExecutor(max_workers=1) as pool, article_cancellation_scope(event):
            def cancel_in_child(value):
                event.set()
                check_article_cancelled()
            def parent():
                with ThreadPoolExecutor(max_workers=1) as children:
                    return list(map_article_tasks(children, cancel_in_child, [1, 2]))
            with self.assertRaises(ArticleDraftCancelled):
                submit_article_task(pool, parent).result(timeout=2)
            event.clear()

    def test_cancelled_lock_waiter_leaves_without_acquiring_or_releasing_owner_lock(self):
        event, waiting = Event(), Event()
        lock = Lock()
        lock.acquire()
        def worker():
            with article_cancellation_scope(event):
                waiting.set()
                with cancellable_lock(lock):
                    self.fail("cancelled waiter must not acquire")
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(worker)
            self.assertTrue(waiting.wait(2))
            event.set()
            with self.assertRaises(ArticleDraftCancelled):
                future.result(timeout=2)
        self.assertTrue(lock.locked())
        lock.release()

    def test_inflight_http_finishes_but_no_followup_request_runs(self):
        event = Event()
        response = MagicMock()
        response.__enter__.return_value = response
        def read():
            event.set()
            return b'{"response": "done"}'
        response.read.side_effect = read
        with patch.object(source, "urlopen", return_value=response) as opened:
            with self.assertRaises(ArticleDraftCancelled), article_cancellation_scope(event):
                source._request_json("http://127.0.0.1/test")
            with self.assertRaises(ArticleDraftCancelled), article_cancellation_scope(event):
                source._request_json("http://127.0.0.1/followup")
        opened.assert_called_once()

    def test_cached_source_checkpoint_respects_cancellation(self):
        event = Event()
        seen = []
        @cancellation_checkpoint
        def cached():
            seen.append("read")
            return "cached article"
        event.set()
        with self.assertRaises(ArticleDraftCancelled), article_cancellation_scope(event):
            cached()
        self.assertEqual(seen, [])


class CancellationRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = web.app.test_client()
        self.jobs = patch.object(web, "ARTICLE_JOBS", {})
        self.cancelled = patch.object(web, "ARTICLE_CANCELLED_REQUESTS", {})
        self.jobs.start()
        self.cancelled.start()
        self.token = "a" * 32

    def tearDown(self):
        self.cancelled.stop()
        self.jobs.stop()

    def start(self, token=None):
        with patch.object(web, "Thread"):
            response = self.client.post("/start-article-draft", json={"reportDate": "2026-10-01", "requestId": token or self.token})
        self.assertEqual(response.status_code, 202)
        return response.json["jobId"]

    def stop(self, token=None):
        return self.client.post("/cancel-article-draft", json={"requestId": token or self.token})

    def test_reload_cancels_only_own_request_and_blocks_restart_until_drained(self):
        job_id = self.start()
        self.assertEqual(self.stop("b" * 32).json["status"], "cancelled")
        self.assertEqual(web.ARTICLE_JOBS[job_id]["status"], "running")
        self.assertEqual(self.stop().json["status"], "cancelling")
        self.assertEqual(self.stop().json["status"], "cancelling")
        self.assertTrue(web.ARTICLE_JOBS[job_id]["_cancelEvent"].is_set())
        busy = self.client.post("/start-article-draft", json={"reportDate": "2026-10-01", "requestId": "c" * 32})
        self.assertEqual(busy.status_code, 409)
        self.assertIn("중지", busy.json["error"])
        with patch.object(source, "_ensure_ollama_ready") as model:
            web._run_article_job(job_id, date(2026, 10, 1))
        model.assert_not_called()
        status = self.client.get(f"/article-draft-status/{job_id}").json
        self.assertEqual(status["status"], "cancelled")
        self.assertEqual(status["sections"], {})
        self.assertEqual(status["progress"], 0)
        self.assertFalse(any(key.startswith("_") for key in status))
        self.assertNotIn(self.token, str(status))
        self.start("c" * 32)

    def test_cancel_before_start_and_beacon_are_idempotent(self):
        body = '{"requestId":"' + self.token + '"}'
        self.assertEqual(self.client.post("/cancel-article-draft", data=body, content_type="application/json").json["status"], "cancelled")
        late = self.client.post("/start-article-draft", json={"reportDate": "2026-10-01", "requestId": self.token})
        self.assertEqual(late.status_code, 409)
        self.assertEqual(late.json["status"], "cancelled")
        self.assertEqual(web.ARTICLE_JOBS, {})
        self.assertEqual(self.stop().json["status"], "cancelled")

    def test_duplicate_start_same_token_returns_same_job_without_second_worker(self):
        job_id = self.start()
        self.assertEqual(self.start(), job_id)
        self.assertEqual(len(web.ARTICLE_JOBS), 1)

    def test_cancel_wins_over_late_result_and_waits_for_inflight_worker(self):
        job_id = self.start()
        entered, release = Event(), Event()
        def collect(report_date, progress, *, cancel_event):
            entered.set()
            self.assertTrue(release.wait(2))
            return {"sections": {"us": {"summary": "must not publish"}}, "message": "done", "readyCount": 1, "candidatesFound": 1}
        with patch.object(web, "collect_weekly_livestock_report_draft", side_effect=collect):
            worker = Thread(target=web._run_article_job, args=(job_id, date(2026, 10, 1)))
            worker.start()
            try:
                self.assertTrue(entered.wait(2))
                self.assertEqual(self.stop().json["status"], "cancelling")
                self.assertTrue(worker.is_alive())
            finally:
                release.set()
                worker.join(timeout=2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(web.ARTICLE_JOBS[job_id]["status"], "cancelled")
        self.assertNotIn("result", web.ARTICLE_JOBS[job_id])
        self.assertEqual(web.ARTICLE_JOBS[job_id]["readyCount"], 0)

    def test_invalid_tokens_and_cancelled_metadata_do_not_touch_reports(self):
        with patch.object(web, "REPORT_JOBS", {"report": {"status": "running"}}):
            for payload in ({}, {"requestId": "../bad"}, {"requestId": "a" * 300}):
                self.assertEqual(self.client.post("/cancel-article-draft", json=payload).status_code, 400)
            self.stop()
            self.assertEqual(web.REPORT_JOBS["report"]["status"], "running")


if __name__ == "__main__":
    unittest.main()
