"""The week window.

Its purpose is fixing a short week, not admiring one, so the tests are mostly
about editing: opening a day, typing into it, and getting those hours to
Tempo — while never offering to re-log hours that are already there.
"""

import tkinter as tk
import unittest
from datetime import date

from timetracker import dayview
from timetracker.ui_week import WeekCallbacks, WeekWindow
from timetracker.week import DaySummary

HOUR = 3600
MON, TUE, WED, THU, FRI = (date(2026, 8, n) for n in (17, 18, 19, 20, 21))


def summary(day, submitted=0, pending=0):
    return DaySummary(date=day, submitted_seconds=submitted,
                      pending_seconds=pending, target_seconds=8 * HOUR)


def record(day, entries=None):
    return {"date": day.isoformat(), "submitted_at": None,
            "entries": entries or [], "segments": []}


def entry(key, seconds, **overrides):
    base = {"issue_key": key, "issue_id": 1, "summary": f"{key} summary",
            "seconds": seconds, "note": "", "source": "manual",
            "confirmed": True, "submitted": False, "tempo_worklog_id": None}
    base.update(overrides)
    return base


class Data:
    """Stands in for week.WeekData."""

    def __init__(self, days, records, assigned=None, internal=None, banner=""):
        self.days = days
        self.records = records
        self.assigned = assigned or []
        self.internal = internal or []
        self.target_seconds = 8 * HOUR
        self.banner = banner

    @property
    def total_seconds(self):
        return sum(d.total_seconds for d in self.days)

    @property
    def week_target_seconds(self):
        return sum(d.target_seconds for d in self.days)


def _descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from _descendants(child)


def labels(widget):
    return [w.cget("text") for w in _descendants(widget)
            if isinstance(w, tk.Label)]


def has_display():
    try:
        tk.Tk().destroy()
        return True
    except tk.TclError:
        return False


@unittest.skipUnless(has_display(), "no display available")
class WeekWindowTestCase(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.geometry("760x520+40+40")
        self.root.attributes("-alpha", 0.0)
        self.saved = []
        self.submitted = []
        self.addCleanup(self._teardown)

    def _teardown(self):
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def build(self, data=None, **callbacks):
        data = data or self.default_data()
        defaults = {
            "on_change": self.saved.append,
            "on_submit": lambda record, day: self.submitted.append((record, day)) or [],
            "on_lookup": lambda key: None,
            "on_close": lambda: None,
        }
        defaults.update(callbacks)
        window = WeekWindow(self.root, data, WeekCallbacks(**defaults))
        self.root.update()
        return window

    def default_data(self):
        return Data(
            days=[summary(MON, submitted=8 * HOUR), summary(TUE, submitted=8 * HOUR),
                  summary(WED, submitted=4 * HOUR), summary(THU, submitted=8 * HOUR),
                  summary(FRI, pending=5 * HOUR + 30 * 60)],
            records={
                MON: record(MON), TUE: record(TUE),
                WED: record(WED, [entry("AP-1", 4 * HOUR, submitted=True,
                                        tempo_worklog_id=9)]),
                THU: record(THU), FRI: record(FRI, [entry("AP-2", 5 * HOUR + 1800)]),
            },
        )


class TheWeekAtAGlance(WeekWindowTestCase):
    def test_it_builds(self):
        self.build()

    def test_every_weekday_is_listed(self):
        self.build()
        shown = labels(self.root)
        for day in (MON, TUE, WED, THU, FRI):
            with self.subTest(day=day):
                self.assertIn(f"{day:%a %d}", shown)

    def test_the_week_total_is_shown(self):
        self.build()
        self.assertEqual(self.build().total_label.cget("text"),
                         "33:30 of 40:00")

    def test_short_days_say_what_is_missing(self):
        self.build()
        shown = labels(self.root)
        self.assertIn("4:00 missing", shown)   # Wednesday
        self.assertIn("2:30 missing", shown)   # Friday

    def test_a_complete_day_says_nothing_about_missing_time(self):
        data = Data(days=[summary(MON, submitted=8 * HOUR)],
                    records={MON: record(MON)})
        window = self.build(data)
        self.assertEqual(window.missing_label.cget("text"),
                         "The week is complete.")

    def test_the_week_shortfall_is_totalled(self):
        window = self.build()
        self.assertIn("6:30 missing", window.missing_label.cget("text"))


class OpeningADay(WeekWindowTestCase):
    def test_days_start_closed(self):
        window = self.build()
        self.assertIsNone(window.open_day)
        self.assertNotIn("AP-1", labels(self.root))

    def test_clicking_a_day_reveals_what_is_on_it(self):
        window = self.build()
        window._toggle(WED)
        self.root.update()

        self.assertEqual(window.open_day, WED)
        self.assertIn("AP-1", labels(self.root))

    def test_clicking_it_again_closes_it(self):
        window = self.build()
        window._toggle(WED)
        window._toggle(WED)
        self.root.update()

        self.assertIsNone(window.open_day)

    def test_only_one_day_is_open_at_a_time(self):
        window = self.build()
        window._toggle(WED)
        window._toggle(FRI)
        self.root.update()

        self.assertEqual(window.open_day, FRI)
        self.assertNotIn("AP-1", labels(self.root))

    def test_an_empty_day_says_so(self):
        window = self.build()
        window._toggle(MON)
        self.root.update()
        self.assertTrue([t for t in labels(self.root)
                         if "Nothing logged" in t])


class EditingAPastDay(WeekWindowTestCase):
    def type_into(self, window, day, key, text):
        field = window._fields[(day, key)]
        field.delete(0, "end")
        field.focus_force()
        for _ in range(100):
            self.root.update()
            if self.root.focus_get() is field:
                break
        else:
            self.fail("could not focus the hours field")

        field.insert(0, text)
        field.event_generate("<KeyRelease>", keysym="Right")
        self.root.update()
        return field

    def test_typing_hours_updates_that_day_s_record(self):
        data = self.default_data()
        window = self.build(data)
        window._toggle(FRI)
        self.root.update()

        self.type_into(window, FRI, "AP-2", "7:30")

        self.assertEqual(dayview.total_seconds(data.records[FRI]),
                         7 * HOUR + 1800)
        self.assertTrue(self.saved)

    def test_it_edits_the_day_you_opened_and_no_other(self):
        data = self.default_data()
        window = self.build(data)
        window._toggle(FRI)
        self.root.update()

        self.type_into(window, FRI, "AP-2", "7:30")

        self.assertEqual(dayview.total_seconds(data.records[MON]), 0)
        self.assertEqual(dayview.total_seconds(data.records[WED]), 4 * HOUR)

    def test_hours_already_in_tempo_are_shown_but_not_editable(self):
        data = self.default_data()
        window = self.build(data)
        window._toggle(WED)
        self.root.update()

        self.assertIn("4:00 logged", labels(self.root))
        self.assertEqual(window._fields[(WED, "AP-1")].get(), "",
                         "the box beside logged hours starts empty")

    def test_adding_to_a_submitted_issue_makes_a_new_sendable_row(self):
        # Back-dated entry is where double-logging is easiest to do and
        # hardest to spot, so the logged hours must never be resent.
        data = self.default_data()
        window = self.build(data)
        window._toggle(WED)
        self.root.update()

        self.type_into(window, WED, "AP-1", "2")

        pending = dayview.entries_to_submit(data.records[WED])
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["seconds"], 2 * HOUR)
        self.assertEqual(dayview.total_seconds(data.records[WED]), 6 * HOUR)

    def test_invalid_input_is_flagged_and_kept(self):
        data = self.default_data()
        window = self.build(data)
        window._toggle(FRI)
        self.root.update()

        field = self.type_into(window, FRI, "AP-2", "lunchtime")

        self.assertEqual(field.get(), "lunchtime")
        self.assertEqual(str(field.cget("highlightbackground")),
                         window.theme["danger"])


class SubmittingAPastDay(WeekWindowTestCase):
    def test_submitting_sends_that_day_s_date(self):
        data = self.default_data()
        window = self.build(data)
        window._toggle(FRI)
        self.root.update()

        window._submit(data.days[4])

        self.assertEqual(len(self.submitted), 1)
        _, day = self.submitted[0]
        self.assertEqual(day, FRI)

    def test_the_button_names_the_day_and_the_hours(self):
        window = self.build()
        window._toggle(FRI)
        self.root.update()

        self.assertIn("Add 5:30 to Friday", labels(self.root))

    def test_a_day_with_nothing_pending_offers_nothing_to_add(self):
        window = self.build()
        window._toggle(WED)
        self.root.update()

        self.assertIn("Nothing to add", labels(self.root))

    def test_a_rejected_row_shows_tempo_s_message(self):
        data = self.default_data()
        window = self.build(data, on_submit=lambda record, day: [
            {"issue_key": "AP-2", "ok": False,
             "message": "Period is closed for the given date"}
        ])
        window._toggle(FRI)
        self.root.update()
        window._submit(data.days[4])
        self.root.update()

        self.assertTrue([t for t in labels(self.root)
                         if "Period is closed" in t])


if __name__ == "__main__":
    unittest.main()
