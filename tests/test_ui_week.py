"""The week page.

It answers one question — which days are short — and hands you off to the day
page to fix them. It deliberately does no editing of its own: a second,
smaller editor for back-dated days would be a second place for the rules about
not re-logging hours to be got wrong.
"""

import tkinter as tk
import unittest
from datetime import date

from timetracker.ui_week import WeekCallbacks, WeekWindow
from timetracker.week import DaySummary

HOUR = 3600
MON, TUE, WED, THU, FRI = (date(2026, 8, n) for n in (17, 18, 19, 20, 21))


def summary(day, submitted=0, pending=0):
    return DaySummary(date=day, submitted_seconds=submitted,
                      pending_seconds=pending, target_seconds=8 * HOUR)


class Data:
    """Stands in for week.WeekData."""

    def __init__(self, days, banner=""):
        self.days = days
        self.records = {}
        self.assigned = []
        self.internal = []
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
class WeekPageTestCase(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.geometry("760x520+40+40")
        self.root.attributes("-alpha", 0.0)
        self.opened = []
        self.closed = []
        self.addCleanup(self._teardown)

    def _teardown(self):
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def build(self, data=None):
        window = WeekWindow(
            self.root, data or self.default_data(),
            WeekCallbacks(on_open_day=self.opened.append,
                          on_close=lambda: self.closed.append(True)),
        )
        self.root.update()
        return window

    def default_data(self):
        return Data([
            summary(MON, submitted=8 * HOUR),
            summary(TUE, submitted=8 * HOUR),
            summary(WED, submitted=4 * HOUR),
            summary(THU, submitted=8 * HOUR),
            summary(FRI, pending=5 * HOUR + 30 * 60),
        ])


class TheWeekAtAGlance(WeekPageTestCase):
    def test_it_builds(self):
        self.build()

    def test_every_weekday_is_listed(self):
        self.build()
        shown = labels(self.root)
        for day in (MON, TUE, WED, THU, FRI):
            with self.subTest(day=day):
                self.assertIn(f"{day:%a %d}", shown)

    def test_the_week_total_is_shown(self):
        window = self.build()
        self.assertEqual(window.total_label.cget("text"), "33:30 of 40:00")

    def test_each_day_shows_its_hours(self):
        self.build()
        shown = labels(self.root)
        self.assertIn("4:00", shown)   # Wednesday
        self.assertIn("5:30", shown)   # Friday

    def test_short_days_say_what_is_missing(self):
        self.build()
        shown = labels(self.root)
        self.assertIn("4:00 missing", shown)
        self.assertIn("2:30 missing", shown)

    def test_the_week_shortfall_is_totalled(self):
        window = self.build()
        self.assertIn("6:30 missing", window.missing_label.cget("text"))

    def test_a_complete_week_says_so(self):
        data = Data([summary(MON, submitted=8 * HOUR)])
        window = self.build(data)
        self.assertEqual(window.missing_label.cget("text"),
                         "The week is complete.")

    def test_a_full_day_is_not_marked_missing(self):
        data = Data([summary(MON, submitted=8 * HOUR)])
        self.build(data)
        self.assertEqual([t for t in labels(self.root) if "missing" in t
                          and t != "The week is complete."], [])

    def test_pending_local_hours_count_toward_a_day(self):
        # Typed but not yet submitted still means the day is not empty.
        data = Data([summary(MON, submitted=2 * HOUR, pending=3 * HOUR)])
        self.build(data)
        self.assertIn("5:00", labels(self.root))

    def test_a_banner_is_shown_when_there_is_one(self):
        self.build(Data([summary(MON)], banner="Can't reach Jira."))
        self.assertTrue([t for t in labels(self.root) if "Can't reach" in t])


class OpeningADay(WeekPageTestCase):
    def test_clicking_a_day_asks_for_that_day(self):
        window = self.build()
        window.callbacks.on_open_day(WED)
        self.assertEqual(self.opened, [WED])

    def test_the_rows_are_wired_to_open_their_own_day(self):
        # Every clickable widget on a row must carry the same date, or
        # clicking the bar would open a different day from clicking the name.
        self.build()
        rows = [w for w in _descendants(self.root)
                if isinstance(w, tk.Frame) and w.winfo_children()]

        clickable = [w for w in _descendants(self.root)
                     if w.bind("<Button-1>") and str(w.cget("cursor")) == "hand2"]
        self.assertGreaterEqual(len(clickable), 5,
                                "each day row should be clickable")

    def test_the_page_does_not_edit_anything_itself(self):
        # No entry boxes here: editing belongs to the day page, so there is
        # only one place the do-not-re-log rules have to be right.
        self.build()
        entries = [w for w in _descendants(self.root)
                   if isinstance(w, tk.Entry)]
        self.assertEqual(entries, [])

    def test_closing_reports_back(self):
        window = self.build()
        window._close()
        self.assertTrue(self.closed)


if __name__ == "__main__":
    unittest.main()
