"""Reproducible local query benchmarks: no network, AI, database or user files.

Run from the project root with .venv/Scripts/python.exe scripts/benchmark_data_access.py.
Timings are synthetic component measurements, NOT full report generation times.
"""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date, timedelta
from functools import wraps
import json
from pathlib import Path
from statistics import median
import sys
from threading import Barrier, Lock, Semaphore
from time import monotonic, perf_counter, sleep


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.crawler import _index_usda_reports, _select_usda_report
from src.runtime_cache import ttl_cache


def legacy_cache(function):
    """The previous cache algorithm, retained only as a benchmark baseline."""
    entries, lock = OrderedDict(), Lock()

    @wraps(function)
    def read(key):
        with lock:
            entry = entries.get(key)
            if entry is not None and monotonic() < entry[0]:
                return deepcopy(entry[1])
            entries.pop(key, None)
        value = function(key)
        with lock:
            entries[key] = (monotonic() + 5, deepcopy(value))
        return value
    return read


def cache_trial(decorator):
    start = Barrier(8)
    upstream_slots, counter_lock = Semaphore(2), Lock()
    calls = 0

    def source(key):
        nonlocal calls
        with counter_lock:
            calls += 1
        with upstream_slots:
            sleep(.04)  # controlled simulated I/O, not a real remote request
        return {'items': [key]}

    read = decorator(source)

    def task(_):
        start.wait(timeout=5)
        return read('shared-original')

    tick = perf_counter()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(task, range(8)))
    elapsed = 1000 * (perf_counter() - tick)
    assert all(value == {'items': ['shared-original']} for value in results)
    results[0]['items'].append('mutation')
    assert results[1] == {'items': ['shared-original']}
    return {'underlyingLoads': calls, 'milliseconds': round(elapsed, 2)}


def report_index_trial():
    first = date(2025, 1, 3)
    dates = [first + timedelta(weeks=week) for week in range(52)]
    reads = [0]

    class Report(dict):
        def __getitem__(self, key):
            if key == 'reportDate':
                reads[0] += 1
            return super().__getitem__(key)

    rows = [Report(reportDate=stamp, publishedDate=stamp + timedelta(days=revision),
                   url=f'https://synthetic.invalid/{week}/{revision}')
            for revision in range(100) for week, stamp in enumerate(dates)]
    # Count accesses once, separately from repeated timing trials.
    previous = [_select_usda_report(rows, 'reportDate', stamp) for stamp in dates]
    old_reads = reads[0]
    reads[0] = 0
    index = _index_usda_reports(rows, 'reportDate')
    current = [index.get(stamp) for stamp in dates]
    indexed_reads = reads[0]
    assert previous == current
    old_times, indexed_times = [], []
    for _ in range(7):
        tick = perf_counter()
        [_select_usda_report(rows, 'reportDate', stamp) for stamp in dates]
        old_times.append(1000 * (perf_counter() - tick))
        tick = perf_counter()
        index = _index_usda_reports(rows, 'reportDate')
        [index.get(stamp) for stamp in dates]
        indexed_times.append(1000 * (perf_counter() - tick))
    return {'records': len(rows), 'dateQueries': len(dates), 'identicalResults': True,
            'before': {'dateFieldReads': old_reads, 'medianMilliseconds': round(median(old_times), 3)},
            'after': {'dateFieldReads': indexed_reads, 'medianMilliseconds': round(median(indexed_times), 3)}}


if __name__ == '__main__':
    print(json.dumps({'scope': 'synthetic component benchmark; not full generation time',
        'concurrentRead8Callers2UpstreamSlots': {
            'before': cache_trial(legacy_cache),
            'after': cache_trial(ttl_cache(seconds=5))},
        'weeklyReportIndex': report_index_trial()}, ensure_ascii=False, indent=2))
