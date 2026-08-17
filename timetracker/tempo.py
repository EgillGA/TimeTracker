"""Tempo Cloud: reading the week back and writing the day in.

Read and create only. Editing and deleting are left to Tempo's own interface,
which already does them well and does not risk this tool quietly rewriting
history it misunderstood.
"""

import json
from datetime import date
from urllib.parse import urlencode

from timetracker.http import Response, check_status, urllib_transport

BASE_URL = "https://api.tempo.io/4"
SERVICE = "Tempo"
MAX_PAGES = 20


class TempoClient:
    def __init__(self, token, transport=None, base_url=BASE_URL):
        self.token = token
        self.base_url = base_url.rstrip("/")
        self._transport = transport or urllib_transport

    # -- reading ------------------------------------------------------------

    def worklogs(self, account_id, start, end):
        """Every worklog this user has between two dates, inclusive."""
        query = urlencode({"from": start.isoformat(), "to": end.isoformat(),
                           "limit": 1000})
        url = f"{self.base_url}/worklogs/user/{account_id}?{query}"

        found = []
        for _ in range(MAX_PAGES):
            payload = self._request("GET", url)
            found.extend(_normalise(entry) for entry in payload.get("results", []))

            url = (payload.get("metadata") or {}).get("next")
            if not url:
                break

        return found

    def seconds_by_date(self, account_id, start, end):
        """Worklogs collapsed to `{date: seconds}` for the week view."""
        totals = {}
        for entry in self.worklogs(account_id, start, end):
            totals[entry["date"]] = totals.get(entry["date"], 0) + entry["seconds"]
        return totals

    # -- writing ------------------------------------------------------------

    def create_worklog(self, account_id, issue_id, seconds, day, description):
        """Log time and return the new worklog id.

        The caller records that id, which is what makes resubmitting a
        partially failed day safe: anything with an id is never sent again.
        """
        body = {
            "issueId": int(issue_id),
            "timeSpentSeconds": int(seconds),
            "startDate": day.isoformat(),
            "authorAccountId": account_id,
            "description": description or "",
        }
        payload = self._request("POST", f"{self.base_url}/worklogs",
                                json.dumps(body), context=f"logging to issue {issue_id}")
        return payload.get("tempoWorklogId")

    # -- internals ----------------------------------------------------------

    def _request(self, method, url, body=None, context=""):
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
        }
        if body is not None:
            headers["Content-Type"] = "application/json"

        response = self._transport(method, url, headers, body)
        if not isinstance(response, Response):  # pragma: no cover - defensive
            raise TypeError("transport must return a Response")

        check_status(response, SERVICE, context)
        return response.json(SERVICE)


def _normalise(entry):
    return {
        "worklog_id": entry.get("tempoWorklogId"),
        "issue_id": (entry.get("issue") or {}).get("id"),
        "seconds": entry.get("timeSpentSeconds", 0),
        "date": date.fromisoformat(entry["startDate"]),
        "description": entry.get("description", ""),
    }
