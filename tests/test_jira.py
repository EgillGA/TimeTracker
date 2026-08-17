"""Jira client: finding the issues worth offering, and resolving their ids.

Tempo's worklog API wants a numeric issue id, but every human-facing part of
the tool speaks issue keys. Resolution and caching therefore live here, and
getting them wrong means logging time against the wrong issue.
"""

import base64
import json
import unittest

from tests.fakes import ok, raw, status
from timetracker.http import ApiError, AuthError
from timetracker.jira import JiraClient
from tests.fakes import FakeTransport

SITE = "https://apt-oz.atlassian.net"
EMAIL = "egill@aptoz.is"
TOKEN = "test-token"


def issue(key, id_, summary):
    return {"id": str(id_), "key": key, "fields": {"summary": summary}}


def page(issues, next_token=None):
    payload = {"issues": issues, "isLast": next_token is None}
    if next_token:
        payload["nextPageToken"] = next_token
    return ok(payload)


def client(*responses):
    transport = FakeTransport(*responses)
    return JiraClient(SITE, EMAIL, TOKEN, transport=transport), transport


class Authentication(unittest.TestCase):
    def test_uses_basic_auth_with_email_and_api_token(self):
        jira, transport = client(page([]))
        jira.search("project = AI")

        header = transport.last["headers"]["Authorization"]
        self.assertTrue(header.startswith("Basic "))
        decoded = base64.b64decode(header.removeprefix("Basic ")).decode()
        self.assertEqual(decoded, f"{EMAIL}:{TOKEN}")

    def test_401_names_jira_so_the_user_knows_which_token_to_renew(self):
        jira, _ = client(status(401, {"errorMessages": ["Unauthorized"]}))
        with self.assertRaises(AuthError) as caught:
            jira.search("project = AI")
        self.assertIn("Jira", str(caught.exception))

    def test_403_is_also_an_auth_error(self):
        jira, _ = client(status(403))
        with self.assertRaises(AuthError):
            jira.search("project = AI")


class Searching(unittest.TestCase):
    def test_posts_the_jql_to_the_enhanced_search_endpoint(self):
        jira, transport = client(page([]))
        jira.search("project = AI AND statusCategory != Done")

        self.assertEqual(transport.last["method"], "POST")
        self.assertIn("/rest/api/3/search/jql", transport.last["url"])
        self.assertEqual(
            json.loads(transport.last["body"])["jql"],
            "project = AI AND statusCategory != Done",
        )

    def test_returns_key_id_and_summary_in_a_flat_shape(self):
        jira, _ = client(page([issue("AV-412", 10412, "Fix altimeter calculation")]))
        found = jira.search("assignee = currentUser()")

        self.assertEqual(
            found,
            [{"key": "AV-412", "id": 10412, "summary": "Fix altimeter calculation"}],
        )

    def test_issue_id_comes_back_as_an_integer_for_tempo(self):
        jira, _ = client(page([issue("AV-412", 10412, "x")]))
        self.assertIsInstance(jira.search("x")[0]["id"], int)

    def test_missing_summary_does_not_crash_the_list(self):
        jira, _ = client(ok({"issues": [{"id": "1", "key": "AV-1", "fields": {}}],
                             "isLast": True}))
        self.assertEqual(jira.search("x")[0]["summary"], "")

    def test_follows_the_page_token_and_concatenates(self):
        jira, transport = client(
            page([issue("AV-1", 1, "one")], next_token="TOKEN-2"),
            page([issue("AV-2", 2, "two")]),
        )
        found = jira.search("x")

        self.assertEqual([i["key"] for i in found], ["AV-1", "AV-2"])
        self.assertEqual(json.loads(transport.requests[1]["body"])["nextPageToken"],
                         "TOKEN-2")

    def test_stops_at_the_result_cap_even_if_more_pages_exist(self):
        # A runaway JQL must not page forever at 15:30.
        jira, transport = client(
            page([issue(f"AV-{n}", n, "x") for n in range(50)], next_token="MORE"),
        )
        found = jira.search("x", max_results=50)

        self.assertEqual(len(found), 50)
        self.assertEqual(transport.call_count, 1)


class WhenTheEndpointIsUnavailable(unittest.TestCase):
    def test_falls_back_to_the_older_search_endpoint(self):
        jira, transport = client(
            status(410, {"errorMessages": ["Gone"]}),
            ok({"issues": [issue("AV-412", 10412, "Fix altimeter calculation")]}),
        )
        found = jira.search("assignee = currentUser()")

        self.assertEqual(found[0]["key"], "AV-412")
        self.assertIn("/rest/api/2/search", transport.requests[1]["url"])

    def test_remembers_the_fallback_instead_of_failing_twice(self):
        jira, transport = client(
            status(404),
            ok({"issues": []}),
            ok({"issues": []}),
        )
        jira.search("first")
        jira.search("second")

        self.assertEqual(transport.call_count, 3)
        self.assertIn("/rest/api/2/search", transport.requests[2]["url"])


class Failures(unittest.TestCase):
    def test_server_error_is_reported_not_swallowed(self):
        jira, _ = client(status(500, {"errorMessages": ["Internal"]}))
        with self.assertRaises(ApiError):
            jira.search("x")

    def test_body_that_is_not_json_is_reported_clearly(self):
        jira, _ = client(raw(200, "<html>proxy sign-in page</html>"))
        with self.assertRaises(ApiError) as caught:
            jira.search("x")
        self.assertIn("Jira", str(caught.exception))

    def test_error_message_from_jira_is_passed_through_to_the_user(self):
        jira, _ = client(status(400, {"errorMessages": ["Field 'sprint' not found"]}))
        with self.assertRaises(ApiError) as caught:
            jira.search("sprint in openSprints()")
        self.assertIn("sprint", str(caught.exception))


class ResolvingIssueIds(unittest.TestCase):
    def test_looks_up_an_id_for_a_manually_typed_key(self):
        jira, transport = client(ok({"id": "10999", "key": "AV-999",
                                     "fields": {"summary": "Typed by hand"}}))
        self.assertEqual(jira.issue_id("AV-999"), 10999)
        self.assertIn("/rest/api/3/issue/AV-999", transport.last["url"])

    def test_a_known_id_costs_no_request(self):
        jira, transport = client(page([issue("AV-412", 10412, "x")]))
        jira.search("x")
        self.assertEqual(jira.issue_id("AV-412"), 10412)
        self.assertEqual(transport.call_count, 1)

    def test_unknown_key_raises_something_the_ui_can_show(self):
        jira, _ = client(status(404, {"errorMessages": ["Issue does not exist"]}))
        with self.assertRaises(ApiError) as caught:
            jira.issue_id("AV-99999")
        self.assertIn("AV-99999", str(caught.exception))

    def test_key_lookup_is_case_insensitive(self):
        jira, transport = client(page([issue("AV-412", 10412, "x")]))
        jira.search("x")
        self.assertEqual(jira.issue_id("av-412"), 10412)
        self.assertEqual(transport.call_count, 1)


class CurrentUser(unittest.TestCase):
    def test_reads_the_account_id_tempo_needs(self):
        jira, transport = client(ok({"accountId": "5f8a:abc", "displayName": "Egill"}))
        self.assertEqual(jira.account_id(), "5f8a:abc")
        self.assertIn("/rest/api/3/myself", transport.last["url"])

    def test_account_id_is_fetched_once_and_reused(self):
        jira, transport = client(ok({"accountId": "5f8a:abc"}))
        jira.account_id()
        jira.account_id()
        self.assertEqual(transport.call_count, 1)


if __name__ == "__main__":
    unittest.main()
