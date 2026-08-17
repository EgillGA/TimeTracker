"""The logic behind the day window, with no tkinter in sight.

Which rows appear, in which tab, what the totals are, and what gets sent to
Tempo. Keeping this separate is what makes the window itself thin enough to
verify by looking at it.
"""

import unittest

from timelogger.dayview import (
    candidate_issues,
    entries_to_submit,
    fill_remaining,
    internal_rows,
    mark_submitted,
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


class TheTwoTabsNeverShowTheSameIssue(unittest.TestCase):
    """An internal issue that is also assigned would otherwise appear in both
    tabs, and the same hour could be typed twice."""

    def test_internal_issues_are_kept_out_of_the_suggestions(self):
        rows = suggestion_rows(
            day(),
            candidates=[issue("AP-7500", 1), issue("AI-1", 10)],
            internal=[issue("AI-1", 10)],
        )
        self.assertEqual([r.issue_key for r in rows], ["AP-7500"])

    def test_issues_already_on_the_day_are_not_suggested_again(self):
        rows = suggestion_rows(
            day([entry("AP-7500", 3 * HOUR)]),
            candidates=[issue("AP-7500", 1), issue("AP-7429", 2)],
            internal=[],
        )
        self.assertEqual([r.issue_key for r in rows], ["AP-7429"])


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
    def test_the_shortfall_goes_to_the_last_issue_with_hours(self):
        record = day([entry("AP-1", 3 * HOUR), entry("AP-2", 2 * HOUR)])
        record = fill_remaining(record, 8 * HOUR)

        self.assertEqual(record["entries"][0]["seconds"], 3 * HOUR)
        self.assertEqual(record["entries"][1]["seconds"], 5 * HOUR)

    def test_rows_left_empty_are_skipped(self):
        record = day([entry("AP-1", 3 * HOUR), entry("AP-2", 0)])
        record = fill_remaining(record, 8 * HOUR)
        self.assertEqual(record["entries"][0]["seconds"], 8 * HOUR)

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
