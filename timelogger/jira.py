"""Jira Cloud: which issues to offer, and what their numeric ids are.

Tempo wants issue ids; humans want issue keys. Every key this client sees —
from a search or from a manual lookup — is remembered, so typing a key you
worked on this week costs no extra request.
"""

import base64
import json

from timelogger.http import ApiError, Response, check_status, urllib_transport

ENHANCED_SEARCH = "/rest/api/3/search/jql"
LEGACY_SEARCH = "/rest/api/2/search"
SERVICE = "Jira"
DEFAULT_MAX_RESULTS = 50


class JiraClient:
    def __init__(self, site, email, token, transport=None):
        self.site = site.rstrip("/")
        self.email = email
        self.token = token
        self._transport = transport or urllib_transport
        self._ids = {}
        self._account_id = None
        self._use_legacy_search = False

    # -- public -------------------------------------------------------------

    def account_id(self):
        """The Atlassian account id Tempo needs. Fetched once per run."""
        if self._account_id is None:
            payload = self._get("/rest/api/3/myself")
            self._account_id = payload.get("accountId")
        return self._account_id

    def search(self, jql, max_results=DEFAULT_MAX_RESULTS):
        """Run a JQL query and return `[{key, id, summary}]`, capped.

        The cap is a guard, not a preference: a mistyped JQL that matches the
        whole backlog must not page forever while the user waits at 15:30.
        """
        issues = []
        token = None

        while len(issues) < max_results:
            payload = self._search_page(jql, max_results, token)
            for raw in payload.get("issues", []):
                issues.append(self._normalise(raw))
                if len(issues) >= max_results:
                    break

            token = payload.get("nextPageToken")
            if not token or payload.get("isLast", True) or self._use_legacy_search:
                break

        return issues

    def issue_id(self, key):
        """The numeric id for an issue key, from cache or from Jira."""
        cached = self._ids.get(key.upper())
        if cached is not None:
            return cached

        try:
            payload = self._get(f"/rest/api/3/issue/{key}?fields=summary")
        except ApiError as error:
            raise ApiError(f"Couldn't find issue {key}. {error}") from None

        return self._normalise(payload)["id"]

    # -- internals ----------------------------------------------------------

    def _normalise(self, raw):
        issue = {
            "key": raw.get("key", ""),
            "id": int(raw.get("id", 0)),
            "summary": (raw.get("fields") or {}).get("summary") or "",
        }
        if issue["key"]:
            self._ids[issue["key"].upper()] = issue["id"]
        return issue

    def _search_page(self, jql, max_results, token):
        if self._use_legacy_search:
            return self._legacy_search_page(jql, max_results)

        body = {"jql": jql, "fields": ["summary"], "maxResults": max_results}
        if token:
            body["nextPageToken"] = token

        response = self._request("POST", ENHANCED_SEARCH, json.dumps(body))
        if response.status in (404, 410):
            # This site is still on the older search API. Remember it, so the
            # next query does not pay for the discovery twice.
            self._use_legacy_search = True
            return self._legacy_search_page(jql, max_results)

        check_status(response, SERVICE, "search")
        return response.json(SERVICE)

    def _legacy_search_page(self, jql, max_results):
        query = urlencode_jql(jql, max_results)
        response = self._request("GET", f"{LEGACY_SEARCH}?{query}")
        check_status(response, SERVICE, "search")
        return response.json(SERVICE)

    def _get(self, path):
        response = self._request("GET", path)
        check_status(response, SERVICE)
        return response.json(SERVICE)

    def _request(self, method, path, body=None):
        credentials = base64.b64encode(
            f"{self.email}:{self.token}".encode("utf-8")
        ).decode("ascii")
        headers = {
            "Authorization": f"Basic {credentials}",
            "Accept": "application/json",
        }
        if body is not None:
            headers["Content-Type"] = "application/json"

        result = self._transport(method, f"{self.site}{path}", headers, body)
        return result if isinstance(result, Response) else result


def urlencode_jql(jql, max_results):
    from urllib.parse import urlencode

    return urlencode({"jql": jql, "fields": "summary", "maxResults": max_results})
