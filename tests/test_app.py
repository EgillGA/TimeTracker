"""The service that joins the window to Jira, Tempo and the disk.

Submission is the dangerous direction, so most of this file is about it: one
worklog per row, ids recorded the instant Tempo accepts, and a partial failure
that never resends what already succeeded.
"""

import tempfile
import unittest
from datetime import date
from pathlib import Path

from timetracker.app import AppService
from timetracker.config import Config, default_jql
from timetracker.http import ApiError, AuthError, NetworkError
from timetracker.store import Store

HOUR = 3600
TODAY = date(2026, 8, 17)


def config(**overrides):
    values = dict(
        jira_site="https://apt-oz.atlassian.net", jira_email="egill@aptoz.is",
        hours_per_day=8.0, prompt_time="15:30", week_view_day="friday",
        checkin_minutes=60, heartbeat_seconds=30, theme="dark",
        internal_project="AI", jql=default_jql("AI"),
    )
    values.update(overrides)
    return Config(**values)


class FakeJira:
    def __init__(self, results=None, fail_with=None):
        self.results = results or {}
        self.fail_with = fail_with
        self.searches = []
        self.ids = {"AP-7500": 7500, "AP-7429": 7429, "AI-1": 1, "AI-2": 2}

    def account_id(self):
        if self.fail_with:
            raise self.fail_with
        return "712020:abc"

    def search(self, jql, max_results=50):
        if self.fail_with:
            raise self.fail_with
        self.searches.append(jql)
        for name, issues in self.results.items():
            if name in jql:
                return issues
        return []

    def issue_id(self, key):
        # Every method on the real client makes a request, so every method on
        # the fake has to be able to fail the way the network does.
        if self.fail_with:
            raise self.fail_with
        if key.upper() not in self.ids:
            raise ApiError(f"Couldn't find issue {key}.")
        return self.ids[key.upper()]


class FakeTempo:
    def __init__(self, fail_for=None):
        self.created = []
        self.fail_for = fail_for or {}
        self.next_id = 46580

    def create_worklog(self, account_id, issue_id, seconds, day, description):
        if issue_id in self.fail_for:
            raise self.fail_for[issue_id]
        self.created.append(
            {"issue_id": issue_id, "seconds": seconds, "day": day,
             "description": description}
        )
        self.next_id += 1
        return self.next_id

    def seconds_by_date(self, account_id, start, end):
        return {}


class ServiceTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self._tmp.name) / "state")
        self.addCleanup(self._tmp.cleanup)

    def service(self, jira=None, tempo=None, **config_overrides):
        return AppService(
            config=config(**config_overrides),
            store=self.store,
            jira=jira or FakeJira(),
            tempo=tempo or FakeTempo(),
        )

    def day_with(self, entries):
        record = self.store.load_day(TODAY)
        record["entries"] = entries
        return record

    @staticmethod
    def entry(key, seconds, **overrides):
        base = {"issue_key": key, "issue_id": 0, "summary": key,
                "seconds": seconds, "note": "", "source": "manual",
                "confirmed": True, "submitted": False, "tempo_worklog_id": None}
        base.update(overrides)
        return base


class LoadingTheDay(ServiceTestCase):
    def test_assigned_and_recent_are_kept_apart(self):
        # They feed two different sections; merging them would lose the only
        # thing that tells Projects from Suggestions.
        jira = FakeJira({
            "assignee = currentUser() AND statusCategory": [
                {"key": "AP-7500", "id": 7500, "summary": "LOPA"}],
            "worklogAuthor": [
                {"key": "AP-7429", "id": 7429, "summary": "PSU"}],
        })
        data = self.service(jira).load_day(TODAY)

        self.assertEqual([i["key"] for i in data.assigned], ["AP-7500"])
        self.assertEqual([i["key"] for i in data.recent], ["AP-7429"])

    def test_reads_the_internal_project(self):
        jira = FakeJira({"project = AI": [
            {"key": "AI-1", "id": 1, "summary": "INTERNAL - WORK"}]})
        data = self.service(jira).load_day(TODAY)

        self.assertEqual([i["key"] for i in data.internal], ["AI-1"])

    def test_the_target_comes_from_configured_hours(self):
        data = self.service(hours_per_day=7.5).load_day(TODAY)
        self.assertEqual(data.target_seconds, int(7.5 * HOUR))

    def test_an_existing_day_record_is_loaded(self):
        self.store.save_day(self.day_with([self.entry("AP-7500", 3 * HOUR)]))
        data = self.service().load_day(TODAY)
        self.assertEqual(data.record["entries"][0]["seconds"], 3 * HOUR)


class WhenJiraCannotBeReached(ServiceTestCase):
    def test_the_day_still_opens_with_what_is_on_disk(self):
        # Manual entry has to keep working on a train or a broken VPN.
        self.store.save_day(self.day_with([self.entry("AP-7500", 3 * HOUR)]))
        jira = FakeJira(fail_with=NetworkError("Can't reach apt-oz"))

        data = self.service(jira).load_day(TODAY)

        self.assertEqual(data.record["entries"][0]["seconds"], 3 * HOUR)
        self.assertIn("Can't reach", data.banner)

    def test_an_expired_token_says_which_one(self):
        jira = FakeJira(fail_with=AuthError("Jira rejected the credentials"))
        data = self.service(jira).load_day(TODAY)
        self.assertIn("Jira", data.banner)

    def test_the_internal_list_falls_back_to_the_last_good_copy(self):
        working = FakeJira({"project = AI": [
            {"key": "AI-1", "id": 1, "summary": "INTERNAL - WORK"},
            {"key": "AI-4", "id": 4, "summary": "INTERNAL - SICK DAYS"},
        ]})
        self.service(working).load_day(TODAY)

        offline = FakeJira(fail_with=NetworkError("down"))
        data = self.service(offline).load_day(TODAY)

        self.assertEqual([i["key"] for i in data.internal], ["AI-1", "AI-4"])

    def test_no_cache_and_no_network_gives_an_empty_list_not_a_crash(self):
        jira = FakeJira(fail_with=NetworkError("down"))
        data = self.service(jira).load_day(TODAY)
        self.assertEqual(data.internal, [])


class Submitting(ServiceTestCase):
    def test_one_worklog_per_row(self):
        tempo = FakeTempo()
        record = self.day_with([self.entry("AP-7500", 3 * HOUR, issue_id=7500),
                                self.entry("AP-7429", 2 * HOUR, issue_id=7429)])

        self.service(tempo=tempo).submit(record, TODAY)

        self.assertEqual([w["issue_id"] for w in tempo.created], [7500, 7429])
        self.assertEqual([w["seconds"] for w in tempo.created],
                         [3 * HOUR, 2 * HOUR])

    def test_worklogs_are_dated_to_the_day_being_filled_in(self):
        tempo = FakeTempo()
        record = self.day_with([self.entry("AP-7500", HOUR, issue_id=7500)])

        self.service(tempo=tempo).submit(record, date(2026, 8, 19))

        self.assertEqual(tempo.created[0]["day"], date(2026, 8, 19))

    def test_the_worklog_id_is_recorded_on_the_row(self):
        record = self.day_with([self.entry("AP-7500", HOUR, issue_id=7500)])
        self.service().submit(record, TODAY)

        self.assertTrue(record["entries"][0]["submitted"])
        self.assertIsNotNone(record["entries"][0]["tempo_worklog_id"])

    def test_rows_without_hours_are_not_sent(self):
        tempo = FakeTempo()
        record = self.day_with([self.entry("AP-7500", 0, issue_id=7500)])

        self.service(tempo=tempo).submit(record, TODAY)

        self.assertEqual(tempo.created, [])

    def test_a_missing_issue_id_is_resolved_first(self):
        tempo = FakeTempo()
        record = self.day_with([self.entry("AP-7500", HOUR, issue_id=0)])

        self.service(tempo=tempo).submit(record, TODAY)

        self.assertEqual(tempo.created[0]["issue_id"], 7500)

    def test_the_note_becomes_the_worklog_description(self):
        tempo = FakeTempo()
        record = self.day_with(
            [self.entry("AP-7500", HOUR, issue_id=7500, note="LOPA rework")]
        )
        self.service(tempo=tempo).submit(record, TODAY)

        self.assertEqual(tempo.created[0]["description"], "LOPA rework")


class WhenSubmissionPartlyFails(ServiceTestCase):
    def failing_tempo(self):
        return FakeTempo(fail_for={
            7429: ApiError("Tempo error 400: Period is closed for the given date")
        })

    def test_the_successful_row_is_still_recorded(self):
        record = self.day_with([self.entry("AP-7500", 3 * HOUR, issue_id=7500),
                                self.entry("AP-7429", 2 * HOUR, issue_id=7429)])

        self.service(tempo=self.failing_tempo()).submit(record, TODAY)

        self.assertTrue(record["entries"][0]["submitted"])
        self.assertFalse(record["entries"][1]["submitted"])

    def test_results_report_both_outcomes(self):
        record = self.day_with([self.entry("AP-7500", 3 * HOUR, issue_id=7500),
                                self.entry("AP-7429", 2 * HOUR, issue_id=7429)])

        results = self.service(tempo=self.failing_tempo()).submit(record, TODAY)

        by_key = {r["issue_key"]: r for r in results}
        self.assertTrue(by_key["AP-7500"]["ok"])
        self.assertFalse(by_key["AP-7429"]["ok"])
        self.assertIn("Period is closed", by_key["AP-7429"]["message"])

    def test_retrying_sends_only_the_failure(self):
        # The whole point of recording ids as we go: pressing Submit again
        # must never log the successful row a second time.
        record = self.day_with([self.entry("AP-7500", 3 * HOUR, issue_id=7500),
                                self.entry("AP-7429", 2 * HOUR, issue_id=7429)])
        self.service(tempo=self.failing_tempo()).submit(record, TODAY)

        retry = FakeTempo()
        self.service(tempo=retry).submit(record, TODAY)

        self.assertEqual([w["issue_id"] for w in retry.created], [7429])

    def test_progress_is_on_disk_before_the_failure_happens(self):
        # If the process died on the failing row, the id for the successful
        # one must already be saved, or it gets logged twice tomorrow.
        record = self.day_with([self.entry("AP-7500", 3 * HOUR, issue_id=7500),
                                self.entry("AP-7429", 2 * HOUR, issue_id=7429)])

        self.service(tempo=self.failing_tempo()).submit(record, TODAY)

        persisted = Store(self.store.root).load_day(TODAY)
        self.assertTrue(persisted["entries"][0]["submitted"])
        self.assertIsNotNone(persisted["entries"][0]["tempo_worklog_id"])

    def test_an_unresolvable_issue_key_fails_only_its_own_row(self):
        tempo = FakeTempo()
        record = self.day_with([self.entry("AP-9999", HOUR, issue_id=0),
                                self.entry("AP-7500", HOUR, issue_id=7500)])

        results = self.service(tempo=tempo).submit(record, TODAY)

        self.assertEqual([w["issue_id"] for w in tempo.created], [7500])
        self.assertFalse({r["issue_key"]: r for r in results}["AP-9999"]["ok"])


class LookingUpATypedKey(ServiceTestCase):
    def test_a_known_key_comes_back_with_its_id(self):
        issue = self.service().lookup("AP-7500")
        self.assertEqual(issue["id"], 7500)

    def test_an_unknown_key_is_none_rather_than_an_exception(self):
        self.assertIsNone(self.service().lookup("AP-99999"))

    def test_lookup_survives_being_offline(self):
        jira = FakeJira(fail_with=NetworkError("down"))
        self.assertIsNone(self.service(jira).lookup("AP-7500"))


if __name__ == "__main__":
    unittest.main()
