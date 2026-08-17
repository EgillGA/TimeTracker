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
        internal_project="AI", day_starts_at="08:00",
        suggestion_count=5, suggestion_days=30, jql=default_jql("AI"),
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
        return self.issue(key)["id"]

    def issue(self, key):
        # Every method on the real client makes a request, so every method on
        # the fake has to be able to fail the way the network does.
        if self.fail_with:
            raise self.fail_with
        if key.upper() not in self.ids:
            raise ApiError(f"Couldn't find issue {key}.")
        return {"key": key.upper(), "id": self.ids[key.upper()],
                "summary": "LOPA change"}


class FakeTempo:
    def __init__(self, fail_for=None, history=None):
        self.created = []
        self.fail_for = fail_for or {}
        self.next_id = 46580
        self.history = history or []

    def create_worklog(self, account_id, issue_id, seconds, day, description,
                       start_time="08:00:00"):
        if issue_id in self.fail_for:
            raise self.fail_for[issue_id]
        self.created.append(
            {"issue_id": issue_id, "seconds": seconds, "day": day,
             "description": description, "start_time": start_time}
        )
        self.next_id += 1
        return self.next_id

    def seconds_by_date(self, account_id, start, end):
        return {}

    def worklogs(self, account_id, start, end):
        return list(self.history)


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


class SuggestionsComeFromWhatYouActuallyLogged(ServiceTestCase):
    """Not Jira activity — Tempo history. The issues you put hours against
    last are the ones you are most likely to put hours against next."""

    def worklog(self, issue_id, day):
        return {"worklog_id": issue_id, "issue_id": issue_id,
                "seconds": HOUR, "date": day, "description": ""}

    def jira_knowing(self, *keys):
        by_id = {"assignee = currentUser() AND statusCategory": [],
                 "worklogAuthor": []}
        found = [{"key": key, "id": index + 1, "summary": key}
                 for index, key in enumerate(keys)]
        by_id["id in ("] = found
        return FakeJira(by_id)

    def test_the_issues_most_recently_logged_to(self):
        tempo = FakeTempo(history=[
            self.worklog(1, date(2026, 8, 10)),
            self.worklog(2, date(2026, 8, 14)),
        ])
        data = self.service(self.jira_knowing("AP-1", "AP-2"),
                            tempo).load_day(TODAY)

        self.assertEqual({i["key"] for i in data.recent}, {"AP-1", "AP-2"})

    def test_only_the_five_most_recent(self):
        tempo = FakeTempo(history=[
            self.worklog(n, date(2026, 8, n)) for n in range(1, 10)
        ])
        jira = self.jira_knowing(*[f"AP-{n}" for n in range(1, 10)])
        data = self.service(jira, tempo).load_day(TODAY)

        self.assertEqual(len(data.recent), 5)

    def test_the_count_is_configurable(self):
        tempo = FakeTempo(history=[
            self.worklog(n, date(2026, 8, n)) for n in range(1, 10)
        ])
        jira = self.jira_knowing(*[f"AP-{n}" for n in range(1, 10)])
        data = self.service(jira, tempo, suggestion_count=3).load_day(TODAY)

        self.assertEqual(len(data.recent), 3)

    def test_an_issue_logged_twice_is_offered_once(self):
        tempo = FakeTempo(history=[
            self.worklog(1, date(2026, 8, 10)),
            self.worklog(1, date(2026, 8, 14)),
        ])
        data = self.service(self.jira_knowing("AP-1"), tempo).load_day(TODAY)

        self.assertEqual(len(data.recent), 1)

    def test_no_history_means_no_suggestions(self):
        data = self.service(self.jira_knowing(), FakeTempo()).load_day(TODAY)
        self.assertEqual(data.recent, [])

    def test_tempo_being_down_costs_only_the_suggestions(self):
        # Projects and the internal tab still work; the day still opens.
        class Broken(FakeTempo):
            def worklogs(self, account_id, start, end):
                raise NetworkError("tempo down")

        jira = FakeJira({"assignee = currentUser() AND statusCategory": [
            {"key": "AP-7500", "id": 7500, "summary": "LOPA"}]})
        data = self.service(jira, Broken()).load_day(TODAY)

        self.assertEqual(data.recent, [])
        self.assertEqual([i["key"] for i in data.assigned], ["AP-7500"])


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


class WorklogsRunThroughTheDay(ServiceTestCase):
    """Two four-hour rows should read 08:00-12:00 and 12:00-16:00, not two
    worklogs stacked on midnight."""

    def test_the_first_row_starts_at_eight(self):
        tempo = FakeTempo()
        record = self.day_with([self.entry("AP-7500", 4 * HOUR, issue_id=7500)])

        self.service(tempo=tempo).submit(record, TODAY)

        self.assertEqual(tempo.created[0]["start_time"], "08:00:00")

    def test_the_second_row_starts_where_the_first_ended(self):
        tempo = FakeTempo()
        record = self.day_with([self.entry("AP-7500", 4 * HOUR, issue_id=7500),
                                self.entry("AP-7429", 4 * HOUR, issue_id=7429)])

        self.service(tempo=tempo).submit(record, TODAY)

        self.assertEqual([w["start_time"] for w in tempo.created],
                         ["08:00:00", "12:00:00"])

    def test_uneven_rows_still_run_back_to_back(self):
        tempo = FakeTempo()
        record = self.day_with([self.entry("AP-7500", 3 * HOUR, issue_id=7500),
                                self.entry("AP-7429", 90 * 60, issue_id=7429),
                                self.entry("AI-1", 2 * HOUR, issue_id=1)])

        self.service(tempo=tempo).submit(record, TODAY)

        self.assertEqual([w["start_time"] for w in tempo.created],
                         ["08:00:00", "11:00:00", "12:30:00"])

    def test_the_start_of_the_day_is_configurable(self):
        tempo = FakeTempo()
        record = self.day_with([self.entry("AP-7500", HOUR, issue_id=7500)])

        self.service(tempo=tempo, day_starts_at="09:00").submit(record, TODAY)

        self.assertEqual(tempo.created[0]["start_time"], "09:00:00")

    def test_a_row_added_after_a_submission_starts_after_it(self):
        # The submitted row keeps its slot, so the new one does not land on
        # top of time already in Tempo.
        tempo = FakeTempo()
        record = self.day_with([
            self.entry("AP-7500", 4 * HOUR, issue_id=7500, submitted=True,
                       tempo_worklog_id=1),
            self.entry("AP-7429", 2 * HOUR, issue_id=7429),
        ])

        self.service(tempo=tempo).submit(record, TODAY)

        self.assertEqual(tempo.created[0]["start_time"], "12:00:00")


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


class RecoveringAnInterruptedTimer(ServiceTestCase):
    """A timer running when the process died still represents real work.
    It is added to the day, bounded by the last heartbeat, and flagged."""

    def running_timer(self, started, heartbeat):
        self.store.save_timer({
            "issue_key": "AP-7500", "issue_id": 7500, "summary": "LOPA",
            "started_at": started, "last_heartbeat": heartbeat,
            "paused_total_seconds": 0, "paused_at": None,
        })

    def test_the_time_is_added_to_today(self):
        self.running_timer("2026-08-17T09:00:00", "2026-08-17T10:30:00")
        data = self.service().load_day(TODAY)

        self.assertEqual(data.record["entries"][0]["issue_key"], "AP-7500")
        self.assertEqual(data.record["entries"][0]["seconds"], 90 * 60)

    def test_it_is_flagged_rather_than_trusted(self):
        self.running_timer("2026-08-17T09:00:00", "2026-08-17T10:30:00")
        data = self.service().load_day(TODAY)
        self.assertFalse(data.record["entries"][0]["confirmed"])

    def test_the_window_is_told_what_happened(self):
        self.running_timer("2026-08-17T09:00:00", "2026-08-17T10:30:00")
        self.assertIn("AP-7500", self.service().load_day(TODAY).banner)

    def test_a_sleeping_machine_does_not_bill_for_the_nap(self):
        # Four hours of wall clock, thirty minutes of heartbeat.
        self.running_timer("2026-08-17T09:00:00", "2026-08-17T09:30:00")
        data = self.service().load_day(TODAY)
        self.assertEqual(data.record["entries"][0]["seconds"], 30 * 60)

    def test_the_timer_is_cleared_so_it_recovers_only_once(self):
        self.running_timer("2026-08-17T09:00:00", "2026-08-17T10:30:00")
        self.service().load_day(TODAY)

        self.assertIsNone(self.store.load_timer())
        second = self.service().load_day(TODAY)
        self.assertEqual(len(second.record["entries"]), 1)

    def test_a_trivial_amount_is_discarded(self):
        # Starting a timer and immediately crashing is not ten seconds of work.
        self.running_timer("2026-08-17T09:00:00", "2026-08-17T09:00:10")
        data = self.service().load_day(TODAY)

        self.assertEqual(data.record["entries"], [])
        self.assertEqual(data.banner, "")

    def test_no_timer_means_no_banner(self):
        self.assertEqual(self.service().load_day(TODAY).banner, "")


class LookingUpATypedKey(ServiceTestCase):
    def test_a_known_key_comes_back_with_its_id(self):
        issue = self.service().lookup("AP-7500")
        self.assertEqual(issue["id"], 7500)

    def test_the_summary_comes_back_too(self):
        # The strip shows it, and so does the row it creates.
        issue = self.service().lookup("AP-7500")
        self.assertEqual(issue["summary"], "LOPA change")

    def test_an_unknown_key_is_none_rather_than_an_exception(self):
        self.assertIsNone(self.service().lookup("AP-99999"))

    def test_lookup_survives_being_offline(self):
        jira = FakeJira(fail_with=NetworkError("down"))
        self.assertIsNone(self.service(jira).lookup("AP-7500"))


if __name__ == "__main__":
    unittest.main()
