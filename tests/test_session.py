"""One window, several pages, and a timer that outlives them.

These rules were buried in closures inside the entry point where nothing could
reach them, and were wrong three times running. What they have to do:

  - opening a day shows the day page for that date
  - stopping a timer lands on today with the run folded in
  - starting a timer leaves the page alone
  - closing the window hides it while a timer runs, and ends the program
    when nothing is
"""

import tkinter as tk
import unittest
from copy import deepcopy
from datetime import date, datetime, timedelta

from timetracker import dayview, timer
from timetracker.session import TimerSession
from timetracker.ui_shell import Shell

HOUR = 3600
TODAY = date.today()
LAST_WEDNESDAY = date(2026, 8, 19)
ISSUE = {"key": "AP-7500", "id": 7500, "summary": "LOPA change"}


class FakeStrip:
    def __init__(self, issue, now):
        self.state = timer.start(issue, now)


class FakePage:
    """A page: something with data and a refresh, built into a frame."""

    def __init__(self, frame, day=None, record=None):
        self.frame = frame
        self.data = type("Data", (), {
            "record": record if record is not None else fresh_record(day),
            "day": day, "running": None,
        })()
        self.refreshed = 0

    def refresh(self):
        self.refreshed += 1


def fresh_record(day=None):
    return {"date": (day or TODAY).isoformat(), "submitted_at": None,
            "entries": [], "segments": []}


def segment(seconds=90 * 60):
    return {"issue_key": "AP-7500", "issue_id": 7500, "summary": "LOPA change",
            "seconds": seconds, "start": "2026-08-17T09:00:00",
            "end": "2026-08-17T10:30:00", "confirmed": True}


def has_display():
    try:
        tk.Tk().destroy()
        return True
    except tk.TclError:
        return False


@unittest.skipUnless(has_display(), "no display available")
class SessionTestCase(unittest.TestCase):
    def setUp(self):
        self.window = tk.Tk()
        self.window.geometry("720x700+40+40")
        self.window.attributes("-alpha", 0.0)
        self.saved = []
        self.cleared = []
        self.days_built = []
        self.weeks_built = []
        self.quit_called = []
        self.addCleanup(self._teardown)

        self.shell = Shell(
            self.window,
            build_day=self._build_day,
            build_week=self._build_week,
            on_quit=lambda: self.quit_called.append(True),
        )
        self.session = TimerSession(
            shell=self.shell,
            record=fresh_record(),
            save_day=self.saved.append,
            clear_timer=lambda: self.cleared.append(True),
            load_day=self._load_day,
        )

    def _teardown(self):
        try:
            self.window.destroy()
        except tk.TclError:
            pass

    def _load_day(self, day):
        # As the real service does: read what was last saved for that day.
        for record in reversed(self.saved):
            if record["date"] == day.isoformat():
                return deepcopy(record)
        return fresh_record(day)

    def _build_day(self, frame, day):
        page = FakePage(frame, day=day, record=self._load_day(day))
        self.days_built.append(page)
        return page

    def _build_week(self, frame):
        page = FakePage(frame)
        self.weeks_built.append(page)
        return page

    def begin_timing(self):
        return self.session.start_timer(
            lambda parent: FakeStrip(ISSUE, datetime.now())
        )


class Navigation(SessionTestCase):
    def test_the_day_page_opens_on_today_by_default(self):
        self.session.show_day()
        self.assertEqual(self.days_built[-1].data.day, TODAY)

    def test_a_named_day_opens_that_day(self):
        self.session.show_day(LAST_WEDNESDAY)
        self.assertEqual(self.days_built[-1].data.day, LAST_WEDNESDAY)

    def test_opening_a_day_uses_the_same_page_as_today(self):
        # "Exactly like the daily tracker" — one page, whatever the date.
        self.session.show_day(TODAY)
        self.session.show_day(LAST_WEDNESDAY)
        self.assertEqual(len(self.days_built), 2)
        self.assertIsInstance(self.days_built[0], type(self.days_built[1]))

    def test_the_week_replaces_the_day_rather_than_stacking_on_it(self):
        self.session.show_day()
        self.session.show_week()

        self.assertEqual(self.shell.showing, "week")
        self.assertEqual(len(self.window.winfo_children()), 1,
                         "one window, one page")

    def test_going_back_and_forth_leaves_one_page_up(self):
        self.session.show_day()
        self.session.show_week()
        self.session.show_day()

        self.assertEqual(self.shell.showing, "day")
        self.assertEqual(len(self.shell.container.winfo_children()), 1)

    def test_the_window_title_says_which_page(self):
        self.session.show_week()
        self.assertIn("week", self.window.title())

        self.session.show_day(LAST_WEDNESDAY)
        self.assertIn("Wednesday", self.window.title())


class StartingATimer(SessionTestCase):
    def test_the_page_is_left_alone(self):
        self.session.show_day()
        page = self.shell.view

        self.begin_timing()

        self.assertIs(self.shell.view, page)
        self.assertEqual(len(self.days_built), 1)

    def test_it_can_be_started_from_the_week_page(self):
        self.session.show_week()
        self.begin_timing()

        self.assertEqual(self.shell.showing, "week")
        self.assertTrue(self.session.timing)

    def test_nothing_is_reported_running_before_one_starts(self):
        self.assertIsNone(self.session.running_state())

    def test_the_running_state_is_reported_once_it_does(self):
        self.begin_timing()
        self.assertEqual(self.session.running_state()["issue_key"], "AP-7500")


class StoppingATimer(SessionTestCase):
    def test_it_lands_on_today(self):
        self.session.show_week()
        self.begin_timing()

        self.session.stop(segment())

        self.assertEqual(self.shell.showing, "day")
        self.assertEqual(self.shell.view.data.day, TODAY)

    def test_the_run_is_in_the_day_it_lands_on(self):
        self.session.show_week()
        self.begin_timing()

        self.session.stop(segment())

        self.assertEqual(dayview.total_seconds(self.shell.view.data.record),
                         90 * 60)

    def test_todays_page_is_kept_rather_than_rebuilt(self):
        self.session.show_day()
        self.begin_timing()
        page = self.shell.view

        self.session.stop(segment())

        self.assertIs(self.shell.view, page, "the page must not be replaced")
        self.assertEqual(len(self.days_built), 1)
        self.assertGreaterEqual(page.refreshed, 1)

    def test_the_run_lands_in_that_kept_page(self):
        self.session.show_day()
        self.begin_timing()

        self.session.stop(segment())

        self.assertEqual(dayview.total_seconds(self.shell.view.data.record),
                         90 * 60)

    def test_hours_typed_before_the_stop_survive_it(self):
        self.session.show_day()
        self.begin_timing()
        self.shell.view.data.record["entries"].append({
            "issue_key": "AP-1", "issue_id": 1, "summary": "typed",
            "seconds": 2 * HOUR, "note": "", "source": "manual",
            "confirmed": True, "submitted": False, "tempo_worklog_id": None,
        })

        self.session.stop(segment())

        self.assertEqual(dayview.total_seconds(self.shell.view.data.record),
                         2 * HOUR + 90 * 60)

    def test_stopping_while_looking_at_another_day_does_not_touch_it(self):
        self.session.show_day(LAST_WEDNESDAY)
        wednesday = self.shell.view.data.record
        self.begin_timing()

        self.session.stop(segment())

        self.assertEqual(dayview.total_seconds(wednesday), 0)
        self.assertEqual(self.shell.view.data.day, TODAY)

    def test_the_day_is_saved_and_the_timer_file_cleared(self):
        self.session.show_day()
        self.begin_timing()
        self.session.stop(segment())

        self.assertTrue(self.saved)
        self.assertTrue(self.cleared)

    def test_nothing_is_reported_running_afterwards(self):
        self.session.show_day()
        self.begin_timing()
        self.session.stop(segment())

        self.assertIsNone(self.session.running_state())


class ClosingTheWindow(SessionTestCase):
    def test_with_a_timer_running_it_only_hides(self):
        # The strip is still doing its job; killing the window would throw
        # away the run.
        self.session.show_day()
        self.begin_timing()

        ended = self.session.close_window()

        self.assertFalse(ended)
        self.assertTrue(self.window.winfo_exists())
        self.assertFalse(self.shell.is_visible())

    def test_a_hidden_window_comes_back_when_asked(self):
        self.session.show_day()
        self.begin_timing()
        self.session.close_window()

        self.session.show_day()

        self.assertTrue(self.shell.is_visible())

    def test_with_nothing_running_it_ends_the_program(self):
        self.session.show_day()

        ended = self.session.close_window()

        self.assertTrue(ended)
        with self.assertRaises(tk.TclError):
            self.window.update()
            self.window.winfo_exists()

    def test_stopping_a_timer_brings_a_hidden_window_back(self):
        self.session.show_day()
        self.begin_timing()
        self.session.close_window()

        self.session.stop(segment())

        self.assertTrue(self.shell.is_visible())


if __name__ == "__main__":
    unittest.main()
