"""A short-lived cache, and a way to run several lookups at once.

Every Jira or Tempo call costs about a third of a second. Loading the day made
four of them one after another, and switching to the week and back made them
all again — well over a second each time, for lists that change perhaps once a
day.

Two things fix that: remember answers for a few minutes, and ask for the
independent ones simultaneously.

Failures are deliberately not remembered. Caching an outage would leave the
window empty for the cache's whole lifetime, long after the network came back.
"""

import time
from concurrent.futures import ThreadPoolExecutor

MAX_PARALLEL_LOOKUPS = 6


class TimedCache:
    def __init__(self, ttl_seconds, clock=time.monotonic):
        self.ttl_seconds = ttl_seconds
        self.clock = clock
        self._entries = {}
        self._in_flight = {}
        self._background = None

    def _pool(self):
        """Daemon threads, so a prefetch in flight never holds the app open."""
        if self._background is None:
            self._background = ThreadPoolExecutor(
                max_workers=MAX_PARALLEL_LOOKUPS,
                thread_name_prefix="timetracker-prefetch",
            )
        return self._background

    def get(self, key, produce):
        """The cached value, or `produce()` — whose result is then cached.

        If a prefetch of this key is still in flight, waits for it rather than
        doing the same work a second time.

        An exception propagates and is not stored, so the next attempt tries
        again rather than serving the failure.
        """
        cached = self._cached(key)
        if cached is not _MISSING:
            return cached

        pending = self._in_flight.pop(key, None)
        if pending is not None:
            try:
                value = pending.result()
            except Exception:  # noqa: BLE001 - fall back to fetching now
                value = _MISSING
            if value is not _MISSING:
                self._entries[key] = (self.clock(), value)
                return value

        value = produce()
        self._entries[key] = (self.clock(), value)
        return value

    def prefetch(self, lookups):
        """Start lookups in the background and return at once.

        For things not on screen yet: the collapsed Suggestions list, and the
        week that is one click away. Blocking the first paint on either makes
        the window slow to appear and buys nothing.
        """
        for key, produce in lookups.items():
            if self._cached(key) is not _MISSING or key in self._in_flight:
                continue
            self._in_flight[key] = self._pool().submit(produce)

    def wait(self, timeout=None):
        """Let any in-flight prefetches finish. Used by tests and shutdown."""
        for key, future in list(self._in_flight.items()):
            try:
                value = future.result(timeout=timeout)
            except Exception:  # noqa: BLE001 - failures are simply not cached
                self._in_flight.pop(key, None)
                continue
            self._entries[key] = (self.clock(), value)
            self._in_flight.pop(key, None)

    def gather(self, lookups):
        """Run several lookups at once and return `{key: value}`.

        Anything that raises comes back as its exception rather than being
        allowed to sink the others: one dead service should cost only its own
        part of the window.
        """
        if not lookups:
            return {}

        results = {}
        pending = {}

        for key, produce in lookups.items():
            cached = self._cached(key)
            if cached is not _MISSING:
                results[key] = cached
            else:
                pending[key] = produce

        if pending:
            with ThreadPoolExecutor(
                max_workers=min(MAX_PARALLEL_LOOKUPS, len(pending))
            ) as pool:
                running = {key: pool.submit(produce)
                           for key, produce in pending.items()}

            for key, future in running.items():
                try:
                    value = future.result()
                except Exception as error:  # noqa: BLE001 - handed to caller
                    results[key] = error
                    continue
                self._entries[key] = (self.clock(), value)
                results[key] = value

        return {key: results[key] for key in lookups}

    def invalidate(self, key=None):
        if key is None:
            self._entries.clear()
            self._in_flight.clear()
        else:
            self._entries.pop(key, None)
            self._in_flight.pop(key, None)

    def _cached(self, key):
        entry = self._entries.get(key)
        if entry is None:
            return _MISSING

        stored_at, value = entry
        if self.clock() - stored_at >= self.ttl_seconds:
            return _MISSING
        return value


class _Missing:
    """A sentinel, because None and [] are both legitimate cached values."""


_MISSING = _Missing()
