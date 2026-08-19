"""Should the window appear right now?

One scheduled task fires twice — at 15:30 on weekdays and again at logon —
and this decides what, if anything, each firing should do. Getting it wrong
in one direction means a window that never appears; in the other, a window
that appears every time you unlock your laptop. The second is how automation
gets uninstalled.
"""

import unittest
from datetime import datetime

from timetracker.config import Config, default_jql
from timetracker.launch import DAY, NOTHING, WEEK, decide, has_submitted

HOUR = 3600


def config(**overrides):
    values = dict(
        jira_site="https://apt-oz.atlassian.net", jira_email="egill@aptoz.is",
        hours_per_day=8.0, prompt_time="15:30", week_view_day="friday",
        day_starts_at="08:00", checkin_minutes=60, heartbeat_seconds=30,
        theme="dark", internal_project="AI", jql=default_jql("AI"),
    )
    values.update(overrides)
    return Config(**values)


def record(entries=None):
    return {"date": "2026-08-17", "submitted_at": None,
            "entries": entries or [], "segments": []}


def entry(seconds, submitted=False):
    return {"issue_key": "AP-1", "issue_id": 1, "summary": "x",
            "seconds": seconds, "note": "", "source": "manual",
            "confirmed": True, "submitted": submitted,
            "tempo_worklog_id": 1 if submitted else None}


# 2026-08-17 is a Monday, 2026-08-21 a Friday, 2026-08-22 a Saturday.
MONDAY_1530 = datetime(2026, 8, 17, 15, 30)
MONDAY_0900 = datetime(2026, 8, 17, 9, 0)
FRIDAY_1530 = datetime(2026, 8, 21, 15, 30)
SATURDAY_1530 = datetime(2026, 8, 22, 15, 30)


class AtThePromptTime(unittest.TestCase):
    def test_a_weekday_opens_the_day(self):
        self.assertEqual(decide(MONDAY_1530, record(), config()), DAY)

    def test_friday_opens_the_week(self):
        self.assertEqual(decide(FRIDAY_1530, record(), config()), WEEK)

    def test_the_week_day_is_configurable(self):
        self.assertEqual(
            decide(MONDAY_1530, record(), config(week_view_day="monday")), WEEK
        )

    def test_the_prompt_time_is_configurable(self):
        at_four = datetime(2026, 8, 17, 16, 0)
        self.assertEqual(decide(at_four, record(), config(prompt_time="16:00")),
                         DAY)

    def test_the_week_day_can_have_its_own_earlier_time(self):
        # Friday afternoons empty out sooner than the rest of the week.
        friday_1330 = datetime(2026, 8, 21, 13, 30)
        self.assertEqual(
            decide(friday_1330, record(), config(week_prompt_time="13:30")), WEEK
        )

    def test_the_week_day_s_own_time_does_not_move_other_days(self):
        # Only Friday gets the earlier time; Monday still waits for 15:30.
        monday_1330 = datetime(2026, 8, 17, 13, 30)
        self.assertEqual(
            decide(monday_1330, record(), config(week_prompt_time="13:30")), NOTHING
        )

    def test_before_the_week_day_s_own_time_is_still_too_early(self):
        friday_1329 = datetime(2026, 8, 21, 13, 29)
        self.assertEqual(
            decide(friday_1329, record(), config(week_prompt_time="13:30")), NOTHING
        )


class TooEarly(unittest.TestCase):
    def test_nothing_happens_before_the_prompt_time(self):
        # A logon at nine in the morning must not open a window asking what
        # you did today.
        self.assertEqual(decide(MONDAY_0900, record(), config()), NOTHING)

    def test_one_minute_before_is_still_too_early(self):
        self.assertEqual(
            decide(datetime(2026, 8, 17, 15, 29), record(), config()), NOTHING
        )

    def test_exactly_on_the_minute_counts(self):
        self.assertEqual(decide(MONDAY_1530, record(), config()), DAY)


class AfterTheDayIsDealtWith(unittest.TestCase):
    def test_nothing_happens_once_something_is_submitted(self):
        # Filling the day in at two o'clock must not earn a second window at
        # half past three.
        done = record([entry(8 * HOUR, submitted=True)])
        self.assertEqual(decide(MONDAY_1530, done, config()), NOTHING)

    def test_a_part_submitted_day_still_prompts(self):
        # Some rows failed, or more work happened since. There is still
        # something to deal with.
        partial = record([entry(3 * HOUR, submitted=True), entry(2 * HOUR)])
        self.assertEqual(decide(MONDAY_1530, partial, config()), DAY)

    def test_typed_but_unsubmitted_hours_still_prompt(self):
        typed = record([entry(3 * HOUR)])
        self.assertEqual(decide(MONDAY_1530, typed, config()), DAY)

    def test_friday_still_shows_the_week_even_when_today_is_done(self):
        # The week view is about the other four days, not today.
        done = record([entry(8 * HOUR, submitted=True)])
        self.assertEqual(decide(FRIDAY_1530, done, config()), WEEK)


class Weekends(unittest.TestCase):
    def test_saturday_is_left_alone(self):
        self.assertEqual(decide(SATURDAY_1530, record(), config()), NOTHING)

    def test_sunday_is_left_alone(self):
        self.assertEqual(
            decide(datetime(2026, 8, 23, 15, 30), record(), config()), NOTHING
        )


class BadConfiguration(unittest.TestCase):
    def test_an_unreadable_prompt_time_falls_back_to_half_past_three(self):
        # A typo in config.toml must not silently disable the whole tool.
        self.assertEqual(
            decide(MONDAY_1530, record(), config(prompt_time="half three")), DAY
        )

    def test_an_unknown_week_day_never_shows_the_week(self):
        self.assertEqual(
            decide(FRIDAY_1530, record(), config(week_view_day="caturday")), DAY
        )


class HasSubmitted(unittest.TestCase):
    def test_an_empty_day_has_not(self):
        self.assertFalse(has_submitted(record()))

    def test_typed_hours_alone_do_not_count(self):
        self.assertFalse(has_submitted(record([entry(3 * HOUR)])))

    def test_one_accepted_row_counts(self):
        self.assertTrue(has_submitted(record([entry(3 * HOUR, submitted=True)])))


if __name__ == "__main__":
    unittest.main()
