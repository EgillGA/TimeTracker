"""Tempo client: reading the week back, and writing the day in.

Writing is the dangerous direction. A worklog posted twice is worse than one
never posted, because nobody notices it.
"""

import json
import unittest
from datetime import date

from tests.fakes import FakeTransport, ok, raw, status
from timelogger.http import ApiError, AuthError
from timelogger.tempo import TempoClient

TOKEN = "tempo-token"
ACCOUNT = "5f8a:abc"


def worklog(worklog_id, issue_id, seconds, day, description="work"):
    return {
        "tempoWorklogId": worklog_id,
        "issue": {"id": issue_id},
        "timeSpentSeconds": seconds,
        "startDate": day,
        "description": description,
    }


def results(items, next_url=None):
    payload = {"results": items, "metadata": {}}
    if next_url:
        payload["metadata"]["next"] = next_url
    return ok(payload)


def client(*responses):
    transport = FakeTransport(*responses)
    return TempoClient(TOKEN, transport=transport), transport


class Authentication(unittest.TestCase):
    def test_uses_a_bearer_token(self):
        tempo, transport = client(results([]))
        tempo.worklogs(ACCOUNT, date(2026, 8, 17), date(2026, 8, 21))
        self.assertEqual(transport.last["headers"]["Authorization"], f"Bearer {TOKEN}")

    def test_401_names_tempo_not_jira(self):
        # The two tokens fail identically otherwise, and renewing the wrong
        # one is a frustrating way to spend a Friday afternoon.
        tempo, _ = client(status(401))
        with self.assertRaises(AuthError) as caught:
            tempo.worklogs(ACCOUNT, date(2026, 8, 17), date(2026, 8, 21))
        self.assertIn("Tempo", str(caught.exception))


class ReadingTheWeek(unittest.TestCase):
    def test_requests_the_date_range_for_the_user(self):
        tempo, transport = client(results([]))
        tempo.worklogs(ACCOUNT, date(2026, 8, 17), date(2026, 8, 21))

        url = transport.last["url"]
        self.assertIn(f"/worklogs/user/{ACCOUNT}", url)
        self.assertIn("from=2026-08-17", url)
        self.assertIn("to=2026-08-21", url)

    def test_normalises_worklogs_to_date_seconds_and_issue(self):
        tempo, _ = client(results([worklog(1, 10412, 10800, "2026-08-17")]))
        found = tempo.worklogs(ACCOUNT, date(2026, 8, 17), date(2026, 8, 21))

        self.assertEqual(found, [{
            "worklog_id": 1,
            "issue_id": 10412,
            "seconds": 10800,
            "date": date(2026, 8, 17),
            "description": "work",
        }])

    def test_follows_paging_to_the_end(self):
        tempo, transport = client(
            results([worklog(1, 1, 3600, "2026-08-17")],
                    next_url="https://api.tempo.io/4/worklogs/user/x?offset=50"),
            results([worklog(2, 2, 3600, "2026-08-18")]),
        )
        found = tempo.worklogs(ACCOUNT, date(2026, 8, 17), date(2026, 8, 21))

        self.assertEqual([w["worklog_id"] for w in found], [1, 2])
        self.assertIn("offset=50", transport.requests[1]["url"])

    def test_totals_by_date_are_summed_for_the_week_view(self):
        tempo, _ = client(results([
            worklog(1, 10412, 3 * 3600, "2026-08-17"),
            worklog(2, 10388, 5 * 3600, "2026-08-17"),
            worklog(3, 10412, 4 * 3600, "2026-08-19"),
        ]))
        totals = tempo.seconds_by_date(ACCOUNT, date(2026, 8, 17), date(2026, 8, 21))

        self.assertEqual(totals, {
            date(2026, 8, 17): 8 * 3600,
            date(2026, 8, 19): 4 * 3600,
        })

    def test_an_empty_week_is_an_empty_mapping_not_an_error(self):
        tempo, _ = client(results([]))
        self.assertEqual(
            tempo.seconds_by_date(ACCOUNT, date(2026, 8, 17), date(2026, 8, 21)), {}
        )


class WritingAWorklog(unittest.TestCase):
    def test_posts_the_fields_tempo_requires(self):
        tempo, transport = client(ok({"tempoWorklogId": 99123}))
        tempo.create_worklog(
            account_id=ACCOUNT, issue_id=10412, seconds=5400,
            day=date(2026, 8, 17), description="Altimeter fix",
        )

        self.assertEqual(transport.last["method"], "POST")
        self.assertIn("/worklogs", transport.last["url"])
        body = json.loads(transport.last["body"])
        self.assertEqual(body["issueId"], 10412)
        self.assertEqual(body["timeSpentSeconds"], 5400)
        self.assertEqual(body["startDate"], "2026-08-17")
        self.assertEqual(body["authorAccountId"], ACCOUNT)
        self.assertEqual(body["description"], "Altimeter fix")

    def test_returns_the_new_worklog_id_so_it_is_never_posted_twice(self):
        tempo, _ = client(ok({"tempoWorklogId": 99123}))
        created = tempo.create_worklog(
            account_id=ACCOUNT, issue_id=10412, seconds=3600,
            day=date(2026, 8, 17), description="",
        )
        self.assertEqual(created, 99123)

    def test_empty_description_is_still_sent(self):
        # Tempo rejects a missing description on some configurations.
        tempo, transport = client(ok({"tempoWorklogId": 1}))
        tempo.create_worklog(account_id=ACCOUNT, issue_id=1, seconds=3600,
                             day=date(2026, 8, 17), description="")
        self.assertIn("description", json.loads(transport.last["body"]))

    def test_a_rejected_worklog_surfaces_tempo_s_own_message(self):
        # This is what the day window prints next to the offending row.
        tempo, _ = client(status(400, {"errors": [
            {"message": "Period is closed for the given date"}
        ]}))
        with self.assertRaises(ApiError) as caught:
            tempo.create_worklog(account_id=ACCOUNT, issue_id=1, seconds=3600,
                                 day=date(2026, 8, 10), description="")
        self.assertIn("Period is closed", str(caught.exception))

    def test_a_missing_required_attribute_is_reported_verbatim(self):
        tempo, _ = client(status(400, {"errors": [
            {"message": "Attribute _Account_ is required"}
        ]}))
        with self.assertRaises(ApiError) as caught:
            tempo.create_worklog(account_id=ACCOUNT, issue_id=1, seconds=3600,
                                 day=date(2026, 8, 17), description="")
        self.assertIn("_Account_", str(caught.exception))

    def test_a_response_that_is_not_json_is_reported_clearly(self):
        tempo, _ = client(raw(200, "<html>gateway timeout</html>"))
        with self.assertRaises(ApiError) as caught:
            tempo.create_worklog(account_id=ACCOUNT, issue_id=1, seconds=3600,
                                 day=date(2026, 8, 17), description="")
        self.assertIn("Tempo", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
