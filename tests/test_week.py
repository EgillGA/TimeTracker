"""Week aggregation: what's logged, what's missing, and never counting twice.

This is the arithmetic behind the Friday window. If it is wrong, the tool
either nags about hours that are already logged or stays quiet about hours
that are not — and the second failure is the one that costs money.
"""

import unittest
from datetime import date

from timetracker.week import pending_seconds, summarise_week, weekdays_of_week

HOUR = 3600


class WeekBoundaries(unittest.TestCase):
    def test_monday_gives_monday_to_friday(self):
        self.assertEqual(
            weekdays_of_week(date(2026, 8, 17)),
            [date(2026, 8, d) for d in (17, 18, 19, 20, 21)],
        )

    def test_friday_gives_the_same_week(self):
        self.assertEqual(weekdays_of_week(date(2026, 8, 21))[0], date(2026, 8, 17))

    def test_saturday_belongs_to_the_week_that_just_ended(self):
        # Someone catching up on Saturday morning means last week, not next.
        self.assertEqual(weekdays_of_week(date(2026, 8, 22))[0], date(2026, 8, 17))

    def test_sunday_belongs_to_the_week_that_just_ended(self):
        self.assertEqual(weekdays_of_week(date(2026, 8, 23))[0], date(2026, 8, 17))

    def test_week_spanning_a_month_end(self):
        self.assertEqual(
            weekdays_of_week(date(2026, 4, 1)),
            [date(2026, 3, 30), date(2026, 3, 31),
             date(2026, 4, 1), date(2026, 4, 2), date(2026, 4, 3)],
        )

    def test_week_spanning_a_year_end(self):
        self.assertEqual(
            weekdays_of_week(date(2026, 1, 1)),
            [date(2025, 12, 29), date(2025, 12, 30), date(2025, 12, 31),
             date(2026, 1, 1), date(2026, 1, 2)],
        )

    def test_weekends_are_never_included(self):
        for day in weekdays_of_week(date(2026, 8, 17)):
            self.assertLessEqual(day.isoweekday(), 5)


class Targets(unittest.TestCase):
    def test_every_weekday_targets_eight_hours(self):
        week = summarise_week(date(2026, 8, 17), {}, {})
        for day in week.days:
            self.assertEqual(day.target_seconds, 8 * HOUR)

    def test_week_targets_forty_hours(self):
        week = summarise_week(date(2026, 8, 17), {}, {})
        self.assertEqual(week.target_seconds, 40 * HOUR)

    def test_target_is_configurable(self):
        week = summarise_week(date(2026, 8, 17), {}, {}, hours_per_day=7.5)
        self.assertEqual(week.target_seconds, int(37.5 * HOUR))


class GapDetection(unittest.TestCase):
    def test_a_full_day_is_complete(self):
        week = summarise_week(date(2026, 8, 17), {date(2026, 8, 17): 8 * HOUR}, {})
        monday = week.days[0]
        self.assertTrue(monday.is_complete)
        self.assertEqual(monday.missing_seconds, 0)

    def test_a_short_day_reports_what_is_missing(self):
        week = summarise_week(date(2026, 8, 17), {date(2026, 8, 19): 4 * HOUR}, {})
        wednesday = week.days[2]
        self.assertEqual(wednesday.missing_seconds, 4 * HOUR)
        self.assertFalse(wednesday.is_complete)

    def test_an_empty_day_is_missing_the_whole_target(self):
        week = summarise_week(date(2026, 8, 17), {}, {})
        self.assertEqual(week.days[0].missing_seconds, 8 * HOUR)

    def test_overtime_does_not_produce_negative_missing_time(self):
        week = summarise_week(date(2026, 8, 17), {date(2026, 8, 17): 10 * HOUR}, {})
        self.assertEqual(week.days[0].missing_seconds, 0)

    def test_overtime_on_one_day_does_not_hide_a_gap_on_another(self):
        # 12h Monday + 4h Wednesday reaches 16h against a 16h two-day target,
        # but Wednesday is still 4h short and must still be flagged.
        week = summarise_week(
            date(2026, 8, 17),
            {date(2026, 8, 17): 12 * HOUR, date(2026, 8, 19): 4 * HOUR},
            {},
        )
        self.assertEqual(week.missing_seconds, 4 * HOUR + 3 * (8 * HOUR))
        self.assertIn(date(2026, 8, 19), [d.date for d in week.short_days])

    def test_short_days_lists_only_incomplete_days_in_order(self):
        week = summarise_week(
            date(2026, 8, 17),
            {d: 8 * HOUR for d in
             (date(2026, 8, 17), date(2026, 8, 18), date(2026, 8, 20))},
            {date(2026, 8, 21): 5 * HOUR},
        )
        self.assertEqual(
            [d.date for d in week.short_days],
            [date(2026, 8, 19), date(2026, 8, 21)],
        )


class MergingTempoWithLocalEntries(unittest.TestCase):
    def test_submitted_and_pending_on_the_same_day_add_up(self):
        week = summarise_week(
            date(2026, 8, 17),
            {date(2026, 8, 17): 5 * HOUR},
            {date(2026, 8, 17): 3 * HOUR},
        )
        monday = week.days[0]
        self.assertEqual(monday.submitted_seconds, 5 * HOUR)
        self.assertEqual(monday.pending_seconds, 3 * HOUR)
        self.assertEqual(monday.total_seconds, 8 * HOUR)
        self.assertTrue(monday.is_complete)

    def test_pending_only_still_counts_toward_the_total(self):
        week = summarise_week(date(2026, 8, 17), {}, {date(2026, 8, 17): 8 * HOUR})
        self.assertEqual(week.days[0].total_seconds, 8 * HOUR)

    def test_data_for_days_outside_the_week_is_ignored(self):
        week = summarise_week(
            date(2026, 8, 17),
            {date(2026, 8, 10): 8 * HOUR, date(2026, 8, 22): 8 * HOUR},
            {},
        )
        self.assertEqual(week.total_seconds, 0)

    def test_week_total_is_the_sum_of_both_sources(self):
        week = summarise_week(
            date(2026, 8, 17),
            {date(2026, 8, 17): 8 * HOUR, date(2026, 8, 18): 8 * HOUR},
            {date(2026, 8, 19): 4 * HOUR},
        )
        self.assertEqual(week.total_seconds, 20 * HOUR)


class DoubleCountingGuard(unittest.TestCase):
    """The one failure mode that silently inflates a week: counting a local
    entry that has already been pushed to Tempo, where it is read back as
    submitted time."""

    def test_entries_already_submitted_are_not_pending(self):
        entries = [
            {"issue_key": "AV-412", "seconds": 3 * HOUR, "submitted": True},
            {"issue_key": "AV-388", "seconds": 2 * HOUR, "submitted": False},
        ]
        self.assertEqual(pending_seconds(entries), 2 * HOUR)

    def test_all_submitted_means_nothing_pending(self):
        entries = [{"issue_key": "AV-412", "seconds": 8 * HOUR, "submitted": True}]
        self.assertEqual(pending_seconds(entries), 0)

    def test_missing_submitted_flag_is_treated_as_not_submitted(self):
        # A day file written by an older version must not vanish from the week.
        self.assertEqual(pending_seconds([{"seconds": HOUR}]), HOUR)

    def test_no_entries_is_zero(self):
        self.assertEqual(pending_seconds([]), 0)


if __name__ == "__main__":
    unittest.main()
