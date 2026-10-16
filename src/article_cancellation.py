"""Cooperative, job-scoped cancellation for article workers and their children.

In-flight I/O/OCR is allowed to finish. No process is killed and unrelated
Excel jobs, local models and callers without a cancellation scope are affected.
"""
from contextlib import contextmanager
from contextvars import ContextVar, copy_context
from functools import wraps
from threading import Event


class ArticleDraftCancelled(RuntimeError):
    """Expected user cancellation, not a source or summary failure."""


_cancel_event: ContextVar[Event | None] = ContextVar("article_cancel_event", default=None)


def check_article_cancelled():
    event = _cancel_event.get()
    if event is not None and event.is_set():
        raise ArticleDraftCancelled("기사 작업을 중지했습니다.")


@contextmanager
def article_cancellation_scope(event: Event | None):
    token = _cancel_event.set(event)
    try:
        check_article_cancelled()
        yield
        check_article_cancelled()
    finally:
        _cancel_event.reset(token)


def cancellation_checkpoint(function):
    """Also check cached returns; never start another request after cancellation."""
    @wraps(function)
    def checked(*args, **kwargs):
        check_article_cancelled()
        result = function(*args, **kwargs)
        check_article_cancelled()
        return result
    return checked


@contextmanager
def cancellable_lock(lock):
    """A cancelled job need not wait for another job's HTTP/model/OCR lock."""
    check_article_cancelled()
    if _cancel_event.get() is None:
        lock.acquire()
    else:
        while not lock.acquire(timeout=.2):
            check_article_cancelled()
    try:
        check_article_cancelled()
        yield
    finally:
        lock.release()


def submit_article_task(executor, function, *args, **kwargs):
    # Context variables do not automatically propagate into thread pools.
    # Capture a separate context for EVERY submission (including nested pools).
    check_article_cancelled()
    context = copy_context()
    return executor.submit(context.run, cancellation_checkpoint(function), *args, **kwargs)


def map_article_tasks(executor, function, values):
    futures = []
    try:
        for value in values:
            futures.append(submit_article_task(executor, function, value))
        for future in futures:
            check_article_cancelled()
            yield future.result()
    finally:
        for future in futures:
            future.cancel()  # pending work only; running workers drain safely
