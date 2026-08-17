"""A transport that answers from a script instead of the network.

The API clients take their transport as an argument precisely so that every
failure worth handling — a 401, a truncated body, a second page — can be
provoked in a test instead of waited for in production.
"""

import json

from timetracker.http import Response


class FakeTransport:
    """Returns queued responses in order and records what was asked for."""

    def __init__(self, *responses):
        self.queued = list(responses)
        self.requests = []

    def __call__(self, method, url, headers=None, body=None, timeout=None):
        self.requests.append(
            {"method": method, "url": url, "headers": headers or {}, "body": body}
        )
        if not self.queued:
            raise AssertionError(f"unexpected extra request: {method} {url}")
        return self.queued.pop(0)

    @property
    def last(self):
        return self.requests[-1]

    @property
    def call_count(self):
        return len(self.requests)


def ok(payload):
    return Response(200, json.dumps(payload).encode("utf-8"))


def raw(status, text):
    return Response(status, text.encode("utf-8"))


def status(code, payload=None):
    return Response(code, json.dumps(payload or {}).encode("utf-8"))


def boom(exception):
    """A response slot that raises instead — network down, timeout, DNS."""

    class _Raiser:
        def __init__(self, exc):
            self.exc = exc

    return _Raiser(exception)
