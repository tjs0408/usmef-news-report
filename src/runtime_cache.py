"""Small, expiring in-process caches. Failures are never cached or persisted."""
from collections import OrderedDict
from copy import deepcopy
from functools import wraps
from threading import Lock
from time import monotonic


def ttl_cache(*, seconds: float, maxsize: int = 32):
    def decorate(function):
        entries = OrderedDict()
        lock = Lock()

        @wraps(function)
        def cached(*args, **kwargs):
            key = (args, tuple(sorted(kwargs.items())))
            with lock:
                entry = entries.get(key)
                if entry is not None and monotonic() < entry[0]:
                    entries.move_to_end(key)
                    return deepcopy(entry[1])
                entries.pop(key, None)
            value = function(*args, **kwargs)
            with lock:
                entries[key] = (monotonic() + seconds, deepcopy(value))
                entries.move_to_end(key)
                while len(entries) > maxsize:
                    entries.popitem(last=False)
            return value

        def clear():
            with lock:
                entries.clear()
        cached.cache_clear = clear
        return cached
    return decorate
