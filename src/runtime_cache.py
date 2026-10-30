"""Bounded process caches with isolated values and coalesced data reads.

Exceptions are never cached. Return values (including None) keep their original
semantics. Job-specific work can opt out of sharing in-flight computation.
"""
from collections import OrderedDict, namedtuple
from copy import deepcopy
from dataclasses import dataclass, field
from functools import wraps
from threading import Event, Lock, get_ident
from time import monotonic

from .article_cancellation import check_article_cancelled


_MISSING = object()
CacheInfo = namedtuple('CacheInfo', 'hits misses maxsize currsize waits inflight')


@dataclass
class _Flight:
    owner: int
    generation: int
    done: Event = field(default_factory=Event)
    value: object = _MISSING


def ttl_cache(*, seconds: float, maxsize: int = 32, singleflight: bool = True):
    def decorate(function):
        entries = OrderedDict()
        pending = {}
        lock = Lock()
        generation = 0
        hits = misses = waits = 0

        def compute(args, kwargs, key, epoch, flight=None):
            try:
                value = function(*args, **kwargs)
                # Private snapshots are never exposed to callers. Both storage
                # and return copies run OUTSIDE the shared map lock.
                stored = deepcopy(value)
                with lock:
                    if epoch == generation:
                        entries[key] = (monotonic() + seconds, stored)
                        entries.move_to_end(key)
                        while len(entries) > maxsize:
                            entries.popitem(last=False)
                        if flight is not None:
                            flight.value = stored
                return value
            finally:
                if flight is not None:
                    with lock:
                        if pending.get(key) is flight:
                            del pending[key]
                        flight.done.set()

        @wraps(function)
        def cached(*args, **kwargs):
            nonlocal hits, misses, waits
            key = (args, tuple(sorted(kwargs.items())))
            while True:
                check_article_cancelled()
                with lock:
                    epoch = generation
                    entry = entries.get(key)
                    value = _MISSING
                    if entry is not None and monotonic() < entry[0]:
                        entries.move_to_end(key)
                        hits += 1
                        value = entry[1]
                        flight = None
                        leader = False
                    else:
                        entries.pop(key, None)
                        flight = pending.get(key) if singleflight else None
                        reentrant = flight is not None and flight.owner == get_ident()
                        if reentrant or not singleflight:
                            misses += 1
                            leader = True
                            flight = None
                        elif flight is None:
                            misses += 1
                            flight = _Flight(get_ident(), epoch)
                            pending[key] = flight
                            leader = True
                        else:
                            waits += 1
                            leader = False
                if value is not _MISSING:
                    return deepcopy(value)
                if leader:
                    if reentrant:
                        return function(*args, **kwargs)  # never wait on ourselves
                    return compute(args, kwargs, key, epoch, flight)
                # Waiting for another job remains independently cancellable.
                while not flight.done.wait(.1):
                    check_article_cancelled()
                check_article_cancelled()
                with lock:
                    current = generation
                    value = flight.value
                    if epoch == current and value is _MISSING:
                        misses += 1
                if epoch != current:
                    continue  # cache_clear detached the old generation
                if value is not _MISSING:
                    return deepcopy(value)
                # Never inherit another job's failure/cancellation/budget. Retry
                # independently in THIS context, without serializing N source
                # timeouts behind one another if the upstream service is down.
                return compute(args, kwargs, key, epoch)

        def clear():
            nonlocal generation, hits, misses, waits
            with lock:
                generation += 1
                entries.clear()
                for flight in pending.values():
                    flight.done.set()
                pending.clear()
                hits = misses = waits = 0

        def info():
            with lock:
                return CacheInfo(hits, misses, maxsize, len(entries), waits, len(pending))

        cached.cache_clear = clear
        cached.cache_info = info
        return cached
    return decorate
