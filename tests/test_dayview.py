"""The logic behind the day window, with no tkinter in sight.

Which rows appear, in which tab, what the totals are, and what gets sent to
Tempo. Keeping this separate is what makes the window itself thin enough to
verify by looking at it.
"""

import unittest

from timetracker.dayview import (
    add_segment,
    candidate_issues,
    entries_to_submit,
    fill_remaining,
    internal_rows,
    mark_submitted,
    project_rows,
    remove_entry,
    schedule,
    set_hours,
    suggestion_rows,
    total_seconds,
    tracked_rows,
    unaccounted_seconds,
)

HOUR = 3600


def issue(key, id_, summary="a task"):
    return {"key": key, "id": id_, "summary": summary}


def day(entries=None):
    return {
        "date": "2026-08-17",
        "submitted_at": None,
        "entries": entries or [],
        "segments": [],
    }


def entry(key, seconds, **overrides):
    base = {
        "issue_key": key, "issue_id": 1, "summary": "a task",
        "seconds": seconds, "note": "", "source": "manual",
        "confirmed": True, "submitted": False, "tempo_worklog_id": None,
    }
    base.update(overrides)
    return base


class CombiningTheTwoJiraQueries(unittest.TestCase):
    def test_issues_in_both_queries_appear_once(self):
        combined = candidate_issues(
            assigned=[issue("AP-7500", 1), issue("AP-7429", 2)],
            recent=[issue("AP-7500", 1), issue("AP-7492", 3)],
        )
        self.assertEqual([i["key"] for i in combined],
                         ["AP-7500", "AP-7429", "AP-7492"])

    def test_assigned_issues_come_first(self):
        # What you own is more likely than what you merely touched.
        combined = candidate_issues(
            assigned=[issue("AP-2", 2)], recent=[issue("AP-1", 1)]
        )
        self.assertEqual([i["key"] for i in combined], ["AP-2", "AP-1"])

    def test_empty_queries_give_an_empty_list(self):
        self.assertEqual(candidate_issues([], []), [])


class ProjectsSection(unittest.TestCase):
    """Everything assigned to me — the work I own, whatever project it is in."""

    def test_lists_every_assigned_issue(self):
        rows = project_rows(
            day(), assigned=[issue("AP-7500", 1), issue("ADS-150", 2)],
            internal=[],
        )
        self.assertEqual([r.issue_key for r in rows], ["AP-7500", "ADS-150"])

    def test_issues_already_tracked_today_drop_out(self):
        rows = project_rows(
            day([entry("AP-7500", 3 * HOUR)]),
            assigned=[issue("AP-7500", 1), issue("AP-7429", 2)],
            internal=[],
        )
        self.assertEqual([r.issue_key for r in rows], ["AP-7429"])

    def test_internal_issues_are_kept_out(self):
        # They have their own tab; the same issue in two places invites
        # typing the same hour twice.
        rows = project_rows(
            day(), assigned=[issue("AP-7500", 1), issue("AI-1", 10)],
            internal=[issue("AI-1", 10)],
        )
        self.assertEqual([r.issue_key for r in rows], ["AP-7500"])


class SuggestionsSection(unittest.TestCase):
    """Recent activity — things I touched that I do not own."""

    def test_recent_work_that_is_not_assigned_to_me(self):
        rows = suggestion_rows(
            day(), recent=[issue("AP-9000", 9)],
            assigned=[issue("AP-7500", 1)], internal=[],
        )
        self.assertEqual([r.issue_key for r in rows], ["AP-9000"])

    def test_issues_already_listed_under_projects_are_not_repeated(self):
        rows = suggestion_rows(
            day(), recent=[issue("AP-7500", 1), issue("AP-9000", 9)],
            assigned=[issue("AP-7500", 1)], internal=[],
        )
        self.assertEqual([r.issue_key for r in rows], ["AP-9000"])

    def test_issues_already_tracked_today_drop_out(self):
        rows = suggestion_rows(
            day([entry("AP-9000", HOUR)]), recent=[issue("AP-9000", 9)],
            assigned=[], internal=[],
        )
        self.assertEqual(rows, [])

    def test_internal_issues_are_kept_out(self):
        rows = suggestion_rows(
            day(), recent=[issue("AI-1", 10)], assigned=[],
            internal=[issue("AI-1", 10)],
        )
        self.assertEqual(rows, [])


class RemovedIssuesGoBackWhereTheyBelong(unittest.TestCase):
    """Removing a tracked row must return it to the section it came from —
    an issue assigned to me is a project, not a suggestion."""

    def test_an_assigned_issue_returns_to_projects(self):
        record = day([entry("AP-7500", HOUR)])
        assigned = [issue("AP-7500", 1)]
        record = remove_entry(record, "AP-7500")

        self.assertEqual(
            [r.issue_key for r in project_rows(record, assigned, [])],
            ["AP-7500"],
        )
        self.assertEqual(suggestion_rows(record, [], assigned, []), [])

    def test_a_merely_recent_issue_returns_to_suggestions(self):
        record = day([entry("AP-9000", HOUR)])
        recent = [issue("AP-9000", 9)]
        record = remove_entry(record, "AP-9000")

        self.assertEqual(project_rows(record, [], []), [])
        self.assertEqual(
            [r.issue_key for r in suggestion_rows(record, recent, [], [])],
            ["AP-9000"],
        )


class TrackedRows(unittest.TestCase):
    def test_entries_become_rows_with_their_hours(self):
        rows = tracked_rows(day([entry("AP-7500", 3 * HOUR)]))
        self.assertEqual(rows[0].issue_key, "AP-7500")
        self.assertEqual(rows[0].seconds, 3 * HOUR)

    def test_timer_sourced_rows_are_marked(self):
        rows = tracked_rows(day([entry("AP-7500", HOUR, source="timer")]))
        self.assertTrue(rows[0].from_timer)

    def test_unconfirmed_rows_are_marked_so_the_window_can_warn(self):
        rows = tracked_rows(
            day([entry("AP-7500", HOUR, source="timer", confirmed=False)])
        )
        self.assertTrue(rows[0].unconfirmed)

    def test_manual_rows_are_never_unconfirmed(self):
        # Typed hours were confirmed by the act of typing them.
        rows = tracked_rows(day([entry("AP-7500", HOUR, source="manual")]))
        self.assertFalse(rows[0].unconfirmed)


class InternalTab(unittest.TestCase):
    def test_lists_every_internal_issue_in_the_given_order(self):
        rows = internal_rows(day(), [issue("AI-1", 10), issue("AI-2", 11)])
        self.assertEqual([r.issue_key for r in rows], ["AI-1", "AI-2"])

    def test_an_issue_already_on_the_day_shows_its_hours_not_an_add_button(self):
        rows = internal_rows(
            day([entry("AI-2", HOUR, issue_id=11)]),
            [issue("AI-1", 10), issue("AI-2", 11)],
        )
        by_key = {r.issue_key: r for r in rows}

        self.assertFalse(by_key["AI-1"].on_day)
        self.assertTrue(by_key["AI-2"].on_day)
        self.assertEqual(by_key["AI-2"].seconds, HOUR)


class EnteringHours(unittest.TestCase):
    def test_setting_hours_on_a_new_issue_adds_a_row(self):
        record = set_hours(day(), issue("AP-7500", 1), 3 * HOUR)
        self.assertEqual(record["entries"][0]["issue_key"], "AP-7500")
        self.assertEqual(record["entries"][0]["seconds"], 3 * HOUR)

    def test_setting_hours_twice_replaces_rather_than_appends(self):
        record = set_hours(day(), issue("AP-7500", 1), 3 * HOUR)
        record = set_hours(record, issue("AP-7500", 1), 5 * HOUR)

        self.assertEqual(len(record["entries"]), 1)
        self.assertEqual(record["entries"][0]["seconds"], 5 * HOUR)

    def test_the_issue_id_is_kept_because_tempo_needs_it(self):
        record = set_hours(day(), issue("AP-7500", 7500), HOUR)
        self.assertEqual(record["entries"][0]["issue_id"], 7500)

    def test_clearing_a_row_to_zero_keeps_it_visible(self):
        # Deleting the row on a keystroke would be hostile while typing.
        record = set_hours(day(), issue("AP-7500", 1), HOUR)
        record = set_hours(record, issue("AP-7500", 1), 0)
        self.assertEqual(len(record["entries"]), 1)

    def test_editing_a_submitted_row_does_not_clear_its_worklog_id(self):
        record = day([entry("AP-7500", HOUR, submitted=True, tempo_worklog_id=5)])
        record = set_hours(record, issue("AP-7500", 1), 2 * HOUR)
        self.assertEqual(record["entries"][0]["tempo_worklog_id"], 5)


class RemovingARow(unittest.TestCase):
    def test_a_row_can_be_taken_off_the_day(self):
        record = day([entry("AP-1", 3 * HOUR), entry("AP-2", 2 * HOUR)])
        record = remove_entry(record, "AP-1")

        self.assertEqual([e["issue_key"] for e in record["entries"]], ["AP-2"])

    def test_removing_drops_its_hours_from_the_total(self):
        record = day([entry("AP-1", 3 * HOUR), entry("AP-2", 2 * HOUR)])
        record = remove_entry(record, "AP-1")
        self.assertEqual(total_seconds(record), 2 * HOUR)

    def test_a_row_already_in_tempo_is_never_removed(self):
        # Its hours exist in Tempo. Deleting the local row would hide time
        # that is really logged, and this tool has no way to unlog it.
        record = day([entry("AP-1", 3 * HOUR, submitted=True,
                            tempo_worklog_id=46580)])
        record = remove_entry(record, "AP-1")

        self.assertEqual(len(record["entries"]), 1)
        self.assertTrue(record["entries"][0]["submitted"])

    def test_removing_an_unknown_issue_changes_nothing(self):
        record = day([entry("AP-1", HOUR)])
        record = remove_entry(record, "AP-999")
        self.assertEqual(len(record["entries"]), 1)

    def test_removal_is_case_insensitive(self):
        record = day([entry("AP-1", HOUR)])
        record = remove_entry(record, "ap-1")
        self.assertEqual(record["entries"], [])


class AddingTimeFromTheTimer(unittest.TestCase):
    def piece(self, key, seconds, confirmed=True):
        return {"issue_key": key, "issue_id": 1, "summary": key,
                "seconds": seconds, "start": "2026-08-17T09:00:00",
                "end": "2026-08-17T10:00:00", "confirmed": confirmed}

    def test_a_new_issue_gets_a_row(self):
        record = add_segment(day(), self.piece("AP-7500", HOUR))

        self.assertEqual(record["entries"][0]["issue_key"], "AP-7500")
        self.assertEqual(record["entries"][0]["seconds"], HOUR)

    def test_time_is_added_to_what_is_already_there(self):
        # Two stints on the same issue are one row of two hours, not two rows.
        record = add_segment(day([entry("AP-7500", HOUR)]),
                             self.piece("AP-7500", 2 * HOUR))

        self.assertEqual(len(record["entries"]), 1)
        self.assertEqual(record["entries"][0]["seconds"], 3 * HOUR)

    def test_the_row_is_marked_as_coming_from_the_timer(self):
        record = add_segment(day(), self.piece("AP-7500", HOUR))
        self.assertEqual(record["entries"][0]["source"], "timer")

    def test_unattended_time_flags_the_row(self):
        record = add_segment(day(), self.piece("AP-7500", HOUR, confirmed=False))
        self.assertFalse(record["entries"][0]["confirmed"])

    def test_a_flagged_row_stays_flagged_when_good_time_is_added(self):
        # Part of the row is still unvouched-for; the warning has to survive.
        record = add_segment(day(), self.piece("AP-7500", HOUR, confirmed=False))
        record = add_segment(record, self.piece("AP-7500", HOUR, confirmed=True))

        self.assertFalse(record["entries"][0]["confirmed"])

    def test_the_run_is_kept_as_an_audit_trail(self):
        record = add_segment(day(), self.piece("AP-7500", HOUR))

        self.assertEqual(len(record["segments"]), 1)
        self.assertEqual(record["segments"][0]["start"], "2026-08-17T09:00:00")

    def test_time_tracked_after_submitting_gets_its_own_row(self):
        """The important one.

        If more time is tracked against an issue whose hours are already in
        Tempo, adding it to that row would leave it marked submitted, and the
        new hour would never be sent anywhere. It needs a row of its own."""
        record = day([entry("AP-7500", 3 * HOUR, submitted=True,
                            tempo_worklog_id=46604)])
        record = add_segment(record, self.piece("AP-7500", HOUR))

        self.assertEqual(len(record["entries"]), 2)
        self.assertEqual(record["entries"][0]["seconds"], 3 * HOUR)
        self.assertTrue(record["entries"][0]["submitted"])
        self.assertEqual(record["entries"][1]["seconds"], HOUR)
        self.assertFalse(record["entries"][1]["submitted"])

    def test_that_extra_row_is_the_one_that_gets_submitted(self):
        record = day([entry("AP-7500", 3 * HOUR, submitted=True,
                            tempo_worklog_id=46604)])
        record = add_segment(record, self.piece("AP-7500", HOUR))

        pending = entries_to_submit(record)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["seconds"], HOUR)

    def test_marking_submitted_finds_the_pending_row_not_the_done_one(self):
        record = day([entry("AP-7500", 3 * HOUR, submitted=True,
                            tempo_worklog_id=46604)])
        record = add_segment(record, self.piece("AP-7500", HOUR))
        record = mark_submitted(record, "AP-7500", 46700)

        self.assertEqual(record["entries"][0]["tempo_worklog_id"], 46604)
        self.assertEqual(record["entries"][1]["tempo_worklog_id"], 46700)


class Totals(unittest.TestCase):
    def test_total_sums_every_entry(self):
        record = day([entry("AP-1", 3 * HOUR), entry("AP-2", 2 * HOUR)])
        self.assertEqual(total_seconds(record), 5 * HOUR)

    def test_unaccounted_is_the_shortfall(self):
        record = day([entry("AP-1", 6 * HOUR)])
        self.assertEqual(unaccounted_seconds(record, 8 * HOUR), 2 * HOUR)

    def test_unaccounted_never_goes_negative(self):
        record = day([entry("AP-1", 10 * HOUR)])
        self.assertEqual(unaccounted_seconds(record, 8 * HOUR), 0)


class FillRemaining(unittest.TestCase):
    """The shortfall is shared out between the rows you added but left blank.

    Adding three issues and pressing Fill remaining is the fast path for a day
    spent across all three; dumping the whole remainder on one of them would
    be wrong in a way that is easy not to notice."""

    def test_the_shortfall_is_split_between_the_empty_rows(self):
        record = day([entry("AP-1", 3 * HOUR), entry("AP-2", 0), entry("AP-3", 0)])
        record = fill_remaining(record, 8 * HOUR)

        seconds = [e["seconds"] for e in record["entries"]]
        self.assertEqual(seconds, [3 * HOUR, 2.5 * HOUR, 2.5 * HOUR])

    def test_a_single_empty_row_takes_all_of_it(self):
        record = day([entry("AP-1", 6 * HOUR), entry("AP-2", 0)])
        record = fill_remaining(record, 8 * HOUR)
        self.assertEqual(record["entries"][1]["seconds"], 2 * HOUR)

    def test_an_uneven_split_loses_no_seconds(self):
        # Three ways into an hour is 1200s each; a split that rounds each
        # share independently would quietly lose or invent time.
        record = day([entry("AP-1", 0), entry("AP-2", 0), entry("AP-3", 0)])
        record = fill_remaining(record, HOUR)

        seconds = [e["seconds"] for e in record["entries"]]
        self.assertEqual(sum(seconds), HOUR)
        self.assertEqual(seconds, [1200, 1200, 1200])

    def test_an_indivisible_split_still_totals_exactly(self):
        record = day([entry("AP-1", 0), entry("AP-2", 0), entry("AP-3", 0)])
        record = fill_remaining(record, HOUR + 1)

        seconds = [e["seconds"] for e in record["entries"]]
        self.assertEqual(sum(seconds), HOUR + 1)
        self.assertEqual(max(seconds) - min(seconds), 1)

    def test_with_no_empty_rows_it_tops_up_the_last_one(self):
        record = day([entry("AP-1", 3 * HOUR), entry("AP-2", 2 * HOUR)])
        record = fill_remaining(record, 8 * HOUR)

        self.assertEqual(record["entries"][0]["seconds"], 3 * HOUR)
        self.assertEqual(record["entries"][1]["seconds"], 5 * HOUR)

    def test_nothing_happens_when_the_day_is_already_full(self):
        record = day([entry("AP-1", 8 * HOUR)])
        self.assertEqual(fill_remaining(record, 8 * HOUR)["entries"][0]["seconds"],
                         8 * HOUR)

    def test_nothing_happens_when_there_is_no_row_to_attribute_it_to(self):
        # Inventing an issue would be worse than leaving the day short.
        record = fill_remaining(day(), 8 * HOUR)
        self.assertEqual(record["entries"], [])

    def test_a_submitted_row_is_never_topped_up(self):
        # Its hours are already in Tempo; growing it here would double-log.
        record = day([entry("AP-1", 3 * HOUR, submitted=True, tempo_worklog_id=1),
                      entry("AP-2", 1 * HOUR)])
        record = fill_remaining(record, 8 * HOUR)

        self.assertEqual(record["entries"][0]["seconds"], 3 * HOUR)
        self.assertEqual(record["entries"][1]["seconds"], 5 * HOUR)


class SchedulingTheDay(unittest.TestCase):
    """Worklogs get consecutive start times from the beginning of the working
    day, so a submitted day reads 08:00-12:00, 12:00-16:00 rather than piling
    everything on midnight."""

    def test_the_first_row_starts_at_the_start_of_the_day(self):
        record = day([entry("AP-1", 4 * HOUR)])
        self.assertEqual(schedule(record, 8 * HOUR), {"AP-1": 8 * HOUR})

    def test_each_row_starts_where_the_previous_one_ended(self):
        record = day([entry("AP-1", 4 * HOUR), entry("AP-2", 4 * HOUR)])
        self.assertEqual(
            schedule(record, 8 * HOUR),
            {"AP-1": 8 * HOUR, "AP-2": 12 * HOUR},
        )

    def test_three_uneven_rows_run_back_to_back(self):
        record = day([entry("AP-1", 3 * HOUR), entry("AP-2", 2 * HOUR),
                      entry("AP-3", 3 * HOUR)])
        self.assertEqual(
            schedule(record, 8 * HOUR),
            {"AP-1": 8 * HOUR, "AP-2": 11 * HOUR, "AP-3": 13 * HOUR},
        )

    def test_empty_rows_take_no_slot(self):
        record = day([entry("AP-1", 4 * HOUR), entry("AP-2", 0),
                      entry("AP-3", 4 * HOUR)])
        scheduled = schedule(record, 8 * HOUR)

        self.assertNotIn("AP-2", scheduled)
        self.assertEqual(scheduled["AP-3"], 12 * HOUR)

    def test_already_submitted_rows_still_occupy_their_time(self):
        # Otherwise a row added later would be scheduled on top of one that
        # is already in Tempo.
        record = day([entry("AP-1", 4 * HOUR, submitted=True,
                            tempo_worklog_id=1),
                      entry("AP-2", 2 * HOUR)])
        self.assertEqual(schedule(record, 8 * HOUR)["AP-2"], 12 * HOUR)

    def test_the_start_of_the_day_is_configurable(self):
        record = day([entry("AP-1", HOUR)])
        self.assertEqual(schedule(record, 9 * HOUR), {"AP-1": 9 * HOUR})

    def test_a_day_that_would_run_past_midnight_is_clamped(self):
        # Tempo rejects a start time of 25:00. A wrong-but-valid time is
        # recoverable; a rejected worklog at 15:30 is not.
        record = day([entry("AP-1", 20 * HOUR), entry("AP-2", 2 * HOUR)])
        scheduled = schedule(record, 8 * HOUR)

        self.assertLess(scheduled["AP-2"], 24 * HOUR)


class WhatGetsSentToTempo(unittest.TestCase):
    def test_only_rows_with_hours_are_submitted(self):
        record = day([entry("AP-1", 3 * HOUR), entry("AP-2", 0)])
        self.assertEqual([e["issue_key"] for e in entries_to_submit(record)],
                         ["AP-1"])

    def test_rows_already_in_tempo_are_never_sent_twice(self):
        record = day([entry("AP-1", 3 * HOUR, submitted=True, tempo_worklog_id=9),
                      entry("AP-2", 2 * HOUR)])
        self.assertEqual([e["issue_key"] for e in entries_to_submit(record)],
                         ["AP-2"])

    def test_marking_submitted_records_the_worklog_id(self):
        record = day([entry("AP-1", 3 * HOUR)])
        record = mark_submitted(record, "AP-1", 46580)

        self.assertTrue(record["entries"][0]["submitted"])
        self.assertEqual(record["entries"][0]["tempo_worklog_id"], 46580)

    def test_a_marked_row_drops_out_of_the_next_submission(self):
        record = day([entry("AP-1", 3 * HOUR), entry("AP-2", 2 * HOUR)])
        record = mark_submitted(record, "AP-1", 1)
        self.assertEqual([e["issue_key"] for e in entries_to_submit(record)],
                         ["AP-2"])

    def test_marking_an_unknown_issue_changes_nothing(self):
        record = day([entry("AP-1", HOUR)])
        record = mark_submitted(record, "AP-999", 1)
        self.assertFalse(record["entries"][0]["submitted"])


if __name__ == "__main__":
    unittest.main()
