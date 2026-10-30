"""Concurrent data reads, invalidation and job-scoped cancellation stay safe."""
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from copy import deepcopy
from threading import Barrier, Event, Lock
from time import monotonic, sleep
import unittest
from unittest.mock import patch

from src.article_cancellation import ArticleDraftCancelled, article_cancellation_scope, check_article_cancelled
from src.runtime_cache import ttl_cache


def wait_for(predicate, timeout=2):
    deadline = monotonic() + timeout
    while not predicate():
        if monotonic() >= deadline:
            raise AssertionError('concurrent workers did not reach expected state')
        sleep(.002)


class RuntimeCacheConcurrencyTests(unittest.TestCase):
    def test_eight_same_key_reads_share_one_load_and_return_isolated_values(self):
        go, loaded, release = Barrier(8), Event(), Event()
        calls = []

        @ttl_cache(seconds=5)
        def fetch(key):
            calls.append(key)
            loaded.set()
            self.assertTrue(release.wait(2))
            return {'values': [key]}

        def task():
            go.wait(2)
            return fetch('same')

        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(task) for _ in range(8)]
            try:
                self.assertTrue(loaded.wait(2))
                wait_for(lambda: fetch.cache_info().waits == 7)
            finally:
                release.set()
            results = [future.result(2) for future in futures]
        self.assertEqual(calls, ['same'])
        results[0]['values'].append('caller mutation')
        self.assertTrue(all(value == {'values': ['same']} for value in results[1:]))
        self.assertEqual(fetch('same'), {'values': ['same']})
        self.assertEqual(fetch.cache_info().misses, 1)
        self.assertEqual(fetch.cache_info().inflight, 0)

    def test_different_keys_are_not_serialized(self):
        both = Barrier(2)

        @ttl_cache(seconds=5)
        def fetch(key):
            both.wait(2)
            return key

        with ThreadPoolExecutor(max_workers=2) as pool:
            a, b = pool.submit(fetch, 'a'), pool.submit(fetch, 'b')
            self.assertEqual((a.result(2), b.result(2)), ('a', 'b'))

    def test_slow_snapshot_copy_does_not_hold_global_map_lock(self):
        copying, release = Event(), Event()

        @ttl_cache(seconds=5)
        def fetch(key):
            return {'key': key}

        fetch('slow')
        fetch('fast')

        def copy(value):
            if value == {'key': 'slow'}:
                copying.set()
                self.assertTrue(release.wait(2))
            return deepcopy(value)

        with patch('src.runtime_cache.deepcopy', side_effect=copy), ThreadPoolExecutor(max_workers=2) as pool:
            slow = pool.submit(fetch, 'slow')
            try:
                self.assertTrue(copying.wait(2))
                self.assertEqual(pool.submit(fetch, 'fast').result(1), {'key': 'fast'})
                self.assertEqual(pool.submit(fetch, 'new').result(1), {'key': 'new'})
            finally:
                release.set()
            self.assertEqual(slow.result(2), {'key': 'slow'})

    def test_failure_is_not_cached_or_transferred_to_a_healthy_job(self):
        role = ContextVar('cache_test_role', default='healthy')
        entered, release = Event(), Event()

        @ttl_cache(seconds=5)
        def fetch():
            if role.get() == 'failed':
                entered.set()
                self.assertTrue(release.wait(2))
                raise RuntimeError('this job failed')
            return role.get()

        def fail():
            role.set('failed')
            return fetch()

        with ThreadPoolExecutor(max_workers=2) as pool:
            failed = pool.submit(fail)
            self.assertTrue(entered.wait(2))
            healthy = pool.submit(fetch)
            try:
                wait_for(lambda: fetch.cache_info().waits == 1)
            finally:
                release.set()
            with self.assertRaises(RuntimeError):
                failed.result(2)
            self.assertEqual(healthy.result(2), 'healthy')
        self.assertEqual(fetch(), 'healthy')

    def test_cancelled_owner_does_not_cancel_another_jobs_waiter(self):
        owner_event, entered, release = Event(), Event(), Event()
        role = ContextVar('cache_owner', default=False)

        @ttl_cache(seconds=5)
        def fetch():
            if role.get():
                entered.set()
                self.assertTrue(release.wait(2))
                check_article_cancelled()
            return 'healthy data'

        def owner():
            role.set(True)
            with article_cancellation_scope(owner_event):
                return fetch()

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(owner)
            self.assertTrue(entered.wait(2))
            second = pool.submit(fetch)
            try:
                wait_for(lambda: fetch.cache_info().waits == 1)
                owner_event.set()
            finally:
                release.set()
            with self.assertRaises(ArticleDraftCancelled):
                first.result(2)
            self.assertEqual(second.result(2), 'healthy data')

    def test_waiter_cancels_without_waiting_for_the_owner_to_finish(self):
        entered, release, cancelled = Event(), Event(), Event()

        @ttl_cache(seconds=5)
        def fetch():
            entered.set()
            self.assertTrue(release.wait(2))
            return {'safe': True}

        def waiter():
            with article_cancellation_scope(cancelled):
                return fetch()

        with ThreadPoolExecutor(max_workers=2) as pool:
            owner = pool.submit(fetch)
            self.assertTrue(entered.wait(2))
            waiting = pool.submit(waiter)
            try:
                wait_for(lambda: fetch.cache_info().waits == 1)
                cancelled.set()
                with self.assertRaises(ArticleDraftCancelled):
                    waiting.result(1)
                self.assertFalse(owner.done())
            finally:
                release.set()
            self.assertEqual(owner.result(2), {'safe': True})

    def test_clear_detaches_waiters_and_old_owner_cannot_reinsert_stale_data(self):
        entered, release = Event(), Event()
        calls, count_lock = [], Lock()

        @ttl_cache(seconds=5)
        def fetch():
            with count_lock:
                number = len(calls) + 1
                calls.append(number)
            if number == 1:
                entered.set()
                self.assertTrue(release.wait(2))
            return number

        with ThreadPoolExecutor(max_workers=2) as pool:
            old = pool.submit(fetch)
            self.assertTrue(entered.wait(2))
            waiting = pool.submit(fetch)
            try:
                wait_for(lambda: fetch.cache_info().waits == 1)
                fetch.cache_clear()
                self.assertEqual(waiting.result(1), 2)
            finally:
                release.set()
            self.assertEqual(old.result(2), 1)
        self.assertEqual(fetch(), 2)
        self.assertEqual(calls, [1, 2])

    def test_same_thread_reentry_does_not_deadlock(self):
        depth = 0

        @ttl_cache(seconds=5)
        def fetch():
            nonlocal depth
            depth += 1
            return fetch() if depth == 1 else 'nested value'

        self.assertEqual(fetch(), 'nested value')
        self.assertEqual(fetch(), 'nested value')
        self.assertEqual(depth, 2)

    def test_opt_out_preserves_independent_context_bound_computation(self):
        both = Barrier(2)
        context = ContextVar('job_budget_test', default='none')

        @ttl_cache(seconds=5, singleflight=False)
        def fetch():
            both.wait(2)
            return context.get()

        def task(value):
            context.set(value)
            return fetch()

        with ThreadPoolExecutor(max_workers=2) as pool:
            a, b = pool.submit(task, 'job-a'), pool.submit(task, 'job-b')
            self.assertEqual((a.result(2), b.result(2)), ('job-a', 'job-b'))
        self.assertEqual(fetch.cache_info().misses, 2)

    def test_none_result_wrapped_function_expiry_lru_and_clear_compatibility(self):
        calls = []

        @ttl_cache(seconds=5, maxsize=2)
        def fetch(key):
            calls.append(key)
            return None

        with patch('src.runtime_cache.monotonic', return_value=10):
            fetch('a'); fetch('b'); fetch('a'); fetch('c'); fetch('b')
            self.assertEqual(calls, ['a', 'b', 'c', 'b'])
            self.assertIsNone(fetch.__wrapped__('raw'))
            self.assertEqual(fetch.cache_info().currsize, 2)
        with patch('src.runtime_cache.monotonic', return_value=16):
            fetch('b')
        self.assertEqual(calls[-2:], ['raw', 'b'])
        fetch.cache_clear()
        self.assertEqual(fetch.cache_info().currsize, 0)
        self.assertEqual(fetch.cache_info().hits, 0)


if __name__ == '__main__':
    unittest.main()
