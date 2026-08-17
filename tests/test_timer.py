"""The running timer's state, with no window attached.

Everything here turns into hours on a timesheet, so the arithmetic is worth
more care than the strip that displays it. Pause that does not really pause,
or a check-in that never fires, both produce confident wrong numbers.
"""

import unittest
from datetime import datetime, timedelta

from timetracker.timer import (
    confirm,
    elapsed_seconds,
    heartbeat,
    is_confirmed,
    is_paused,
    needs_checkin,
    pause,
    resume,
    segment,
    start,
)

ISSUE = {"key": "AP-7500", "id": 7500, "summary": "LOPA change"}
NINE = datetime(2026, 8, 17, 9, 0, 0)


def at(minutes):
    return NINE + timedelta(minutes=minutes)


class Starting(unittest.TestCase):
    def test_records_the_issue(self):
        state = start(ISSUE, NINE)
        self.assertEqual(state["issue_key"], "AP-7500")
        self.assertEqual(state["issue_id"], 7500)
        self.assertEqual(state["summary"], "LOPA change")

    def test_starts_at_zero(self):
        self.assertEqual(elapsed_seconds(start(ISSUE, NINE), NINE), 0)

    def test_is_not_paused(self):
        self.assertFalse(is_paused(start(ISSUE, NINE)))

    def test_counts_as_confirmed_at_the_moment_it_starts(self):
        # Starting a timer is itself an act of saying what you are doing.
        state = start(ISSUE, NINE)
        self.assertTrue(is_confirmed(state, NINE, checkin_minutes=60))


class Elapsing(unittest.TestCase):
    def test_ninety_minutes(self):
        self.assertEqual(elapsed_seconds(start(ISSUE, NINE), at(90)), 90 * 60)

    def test_never_goes_backwards_if_the_clock_does(self):
        # Daylight saving and clock corrections should not invent negative work.
        state = start(ISSUE, NINE)
        self.assertEqual(elapsed_seconds(state, NINE - timedelta(hours=1)), 0)


class Pausing(unittest.TestCase):
    def test_pausing_freezes_the_count(self):
        state = pause(start(ISSUE, NINE), at(30))

        self.assertEqual(elapsed_seconds(state, at(30)), 30 * 60)
        self.assertEqual(elapsed_seconds(state, at(90)), 30 * 60)

    def test_paused_is_reported(self):
        self.assertTrue(is_paused(pause(start(ISSUE, NINE), at(30))))

    def test_resuming_continues_from_where_it_stopped(self):
        state = pause(start(ISSUE, NINE), at(30))
        state = resume(state, at(90))

        self.assertEqual(elapsed_seconds(state, at(90)), 30 * 60)
        self.assertEqual(elapsed_seconds(state, at(120)), 60 * 60)

    def test_the_paused_hour_is_not_billed(self):
        state = pause(start(ISSUE, NINE), at(30))
        state = resume(state, at(90))
        self.assertEqual(state["paused_total_seconds"], 60 * 60)

    def test_several_pauses_accumulate(self):
        state = start(ISSUE, NINE)
        state = resume(pause(state, at(10)), at(20))
        state = resume(pause(state, at(30)), at(50))

        self.assertEqual(state["paused_total_seconds"], 30 * 60)
        self.assertEqual(elapsed_seconds(state, at(60)), 30 * 60)

    def test_resuming_a_running_timer_changes_nothing(self):
        state = start(ISSUE, NINE)
        self.assertEqual(resume(state, at(30)), state)

    def test_pausing_a_paused_timer_changes_nothing(self):
        state = pause(start(ISSUE, NINE), at(30))
        self.assertEqual(pause(state, at(45)), state)


class TheHourlyCheckIn(unittest.TestCase):
    def test_does_not_ask_before_the_interval(self):
        state = start(ISSUE, NINE)
        self.assertFalse(needs_checkin(state, at(59), checkin_minutes=60))

    def test_asks_once_the_interval_has_passed(self):
        state = start(ISSUE, NINE)
        self.assertTrue(needs_checkin(state, at(60), checkin_minutes=60))

    def test_confirming_resets_the_clock(self):
        state = confirm(start(ISSUE, NINE), at(60))
        self.assertFalse(needs_checkin(state, at(90), checkin_minutes=60))
        self.assertTrue(needs_checkin(state, at(120), checkin_minutes=60))

    def test_a_paused_timer_is_never_asked(self):
        # You already told it you stopped working. Asking again is nagging.
        state = pause(start(ISSUE, NINE), at(30))
        self.assertFalse(needs_checkin(state, at(120), checkin_minutes=60))

    def test_the_interval_is_configurable(self):
        state = start(ISSUE, NINE)
        self.assertTrue(needs_checkin(state, at(30), checkin_minutes=30))


class Confirmation(unittest.TestCase):
    """Time that ran on unattended is still recorded, but flagged, so the day
    window can say 'check this' instead of quietly billing it."""

    def test_time_within_the_interval_is_confirmed(self):
        state = start(ISSUE, NINE)
        self.assertTrue(is_confirmed(state, at(45), checkin_minutes=60))

    def test_an_ignored_check_in_leaves_the_time_unconfirmed(self):
        state = start(ISSUE, NINE)
        self.assertFalse(is_confirmed(state, at(75), checkin_minutes=60))

    def test_there_is_a_grace_period_before_it_counts_as_ignored(self):
        # Answering a minute late should not taint the whole segment.
        state = start(ISSUE, NINE)
        self.assertTrue(is_confirmed(state, at(62), checkin_minutes=60))

    def test_answering_makes_it_confirmed_again(self):
        state = confirm(start(ISSUE, NINE), at(60))
        self.assertTrue(is_confirmed(state, at(90), checkin_minutes=60))


class Heartbeat(unittest.TestCase):
    def test_records_the_last_moment_work_was_demonstrable(self):
        state = heartbeat(start(ISSUE, NINE), at(30))
        self.assertEqual(state["last_heartbeat"], at(30).isoformat())


class StoppingProducesASegment(unittest.TestCase):
    def test_carries_the_issue_and_the_time(self):
        piece = segment(start(ISSUE, NINE), at(90), checkin_minutes=60)

        self.assertEqual(piece["issue_key"], "AP-7500")
        self.assertEqual(piece["issue_id"], 7500)
        self.assertEqual(piece["seconds"], 90 * 60)

    def test_records_when_it_ran(self):
        piece = segment(start(ISSUE, NINE), at(90), checkin_minutes=60)

        self.assertEqual(piece["start"], NINE.isoformat())
        self.assertEqual(piece["end"], at(90).isoformat())

    def test_excludes_paused_time(self):
        state = resume(pause(start(ISSUE, NINE), at(30)), at(90))
        piece = segment(state, at(120), checkin_minutes=60)

        self.assertEqual(piece["seconds"], 60 * 60)

    def test_a_segment_that_ran_unattended_is_flagged(self):
        piece = segment(start(ISSUE, NINE), at(200), checkin_minutes=60)
        self.assertFalse(piece["confirmed"])

    def test_a_short_segment_is_confirmed(self):
        piece = segment(start(ISSUE, NINE), at(20), checkin_minutes=60)
        self.assertTrue(piece["confirmed"])


if __name__ == "__main__":
    unittest.main()
