"""A short-lived cache for lookups that cost a network round trip.

Issue lists change perhaps once a day; fetching them again every time you
switch between the day and the week costs a second and buys nothing.

The rule that matters most: a failed lookup is never cached. Caching an
outage would leave the window empty for the full lifetime of the cache, long
after the network came back.
"""

import unittest

from timetracker.cache import TimedCache


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class Caching(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.cache = TimedCache(ttl_seconds=300, clock=self.clock)
        self.calls = []

    def produce(self, value):
        def call():
            self.calls.append(value)
            return value

        return call

    def test_the_first_call_produces_the_value(self):
        self.assertEqual(self.cache.get("issues", self.produce("a")), "a")
        self.assertEqual(self.calls, ["a"])

    def test_a_second_call_within_the_window_does_not(self):
        self.cache.get("issues", self.produce("a"))
        self.assertEqual(self.cache.get("issues", self.produce("b")), "a")
        self.assertEqual(self.calls, ["a"])

    def test_it_expires(self):
        self.cache.get("issues", self.produce("a"))
        self.clock.advance(301)

        self.assertEqual(self.cache.get("issues", self.produce("b")), "b")

    def test_the_moment_it_expires_counts_as_expired(self):
        self.cache.get("issues", self.produce("a"))
        self.clock.advance(300)
        self.assertEqual(self.cache.get("issues", self.produce("b")), "b")

    def test_keys_are_independent(self):
        self.cache.get("one", self.produce("a"))
        self.cache.get("two", self.produce("b"))

        self.assertEqual(self.cache.get("one", self.produce("x")), "a")
        self.assertEqual(self.cache.get("two", self.produce("x")), "b")

    def test_a_falsy_value_is_still_cached(self):
        # An empty list is a real answer, not a missing one.
        self.cache.get("issues", lambda: [])
        self.assertEqual(self.cache.get("issues", self.produce("a")), [])
        self.assertEqual(self.calls, [])


class FailuresAreNotCached(unittest.TestCase):
    """Caching an outage would leave the window empty for the whole lifetime
    of the cache, long after the network came back."""

    def setUp(self):
        self.cache = TimedCache(ttl_seconds=300, clock=Clock())

    def test_the_error_is_raised(self):
        def boom():
            raise RuntimeError("network down")

        with self.assertRaises(RuntimeError):
            self.cache.get("issues", boom)

    def test_the_next_call_tries_again(self):
        calls = []

        def flaky():
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("network down")
            return "recovered"

        with self.assertRaises(RuntimeError):
            self.cache.get("issues", flaky)

        self.assertEqual(self.cache.get("issues", flaky), "recovered")
        self.assertEqual(len(calls), 2)


class Invalidating(unittest.TestCase):
    def setUp(self):
        self.cache = TimedCache(ttl_seconds=300, clock=Clock())

    def test_one_key_can_be_dropped(self):
        self.cache.get("one", lambda: "a")
        self.cache.get("two", lambda: "b")
        self.cache.invalidate("one")

        self.assertEqual(self.cache.get("one", lambda: "fresh"), "fresh")
        self.assertEqual(self.cache.get("two", lambda: "fresh"), "b")

    def test_everything_can_be_dropped(self):
        self.cache.get("one", lambda: "a")
        self.cache.invalidate()
        self.assertEqual(self.cache.get("one", lambda: "fresh"), "fresh")

    def test_dropping_something_absent_is_harmless(self):
        self.cache.invalidate("never-stored")


class RunningInParallel(unittest.TestCase):
    def test_several_lookups_at_once_return_in_order(self):
        cache = TimedCache(ttl_seconds=300, clock=Clock())
        results = cache.gather({
            "a": lambda: "first",
            "b": lambda: "second",
            "c": lambda: "third",
        })
        self.assertEqual(results, {"a": "first", "b": "second",
                                   "c": "third"})

    def test_results_are_cached_for_next_time(self):
        cache = TimedCache(ttl_seconds=300, clock=Clock())
        cache.gather({"a": lambda: "first"})

        self.assertEqual(cache.get("a", lambda: "again"), "first")

    def test_one_failure_does_not_lose_the_others(self):
        def boom():
            raise RuntimeError("down")

        cache = TimedCache(ttl_seconds=300, clock=Clock())
        results = cache.gather({"a": lambda: "fine", "b": boom})

        self.assertEqual(results["a"], "fine")
        self.assertIsInstance(results["b"], RuntimeError)

    def test_a_failure_is_not_cached(self):
        calls = []

        def boom():
            calls.append(1)
            raise RuntimeError("down")

        cache = TimedCache(ttl_seconds=300, clock=Clock())
        cache.gather({"a": boom})
        cache.gather({"a": boom})

        self.assertEqual(len(calls), 2)


class Prefetching(unittest.TestCase):
    """Fetching in the background what is not on screen yet.

    Suggestions are collapsed and the week is a click away, so blocking the
    first paint on either of them makes the window slow to appear for no gain.
    """

    def setUp(self):
        self.cache = TimedCache(ttl_seconds=300, clock=Clock())

    def test_a_prefetched_value_is_there_when_asked_for(self):
        self.cache.prefetch({"issues": lambda: "fetched"})
        self.cache.wait()

        self.assertEqual(self.cache.get("issues", lambda: "fresh"), "fetched")

    def test_prefetching_does_not_raise_on_failure(self):
        def boom():
            raise RuntimeError("down")

        self.cache.prefetch({"issues": boom})
        self.cache.wait()

        self.assertEqual(self.cache.get("issues", lambda: "fresh"), "fresh")

    def test_asking_while_it_is_in_flight_waits_rather_than_repeating(self):
        import threading

        released = threading.Event()
        calls = []

        def slow():
            calls.append(1)
            released.wait(timeout=5)
            return "fetched"

        self.cache.prefetch({"issues": slow})
        released.set()

        self.assertEqual(self.cache.get("issues", lambda: "duplicate"),
                         "fetched")
        self.assertEqual(len(calls), 1, "the work must not be done twice")

    def test_an_already_cached_key_is_not_prefetched_again(self):
        calls = []
        self.cache.get("issues", lambda: "first")
        self.cache.prefetch({"issues": lambda: calls.append(1)})
        self.cache.wait()

        self.assertEqual(calls, [])

    def test_waiting_with_nothing_in_flight_is_harmless(self):
        self.cache.wait()


if __name__ == "__main__":
    unittest.main()
