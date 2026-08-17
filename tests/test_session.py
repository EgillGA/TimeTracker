"""The window lifecycle for one timer run.

This was buried in closures inside run_timer, where nothing could test it, and
I got it wrong twice as a result. The rules it has to obey:

  - stopping the timer must not replace an open day window
  - stopping with no window open must produce one
  - closing the day window while a timer runs must leave the timer alone
  - closing it once the timer has stopped must end the process, or an
    invisible root keeps running with nothing on screen
"""

import tkinter as tk
import unittest
from copy import deepcopy
from datetime import datetime, timedelta

from timetracker import dayview, timer
from timetracker.session import TimerSession

HOUR = 3600
ISSUE = {"key": "AP-7500", "id": 7500, "summary": "LOPA change"}


class FakeStrip:
    """Stands in for the real strip: it only has to hold timer state."""

    def __init__(self, issue, now):
        self.state = timer.start(issue, now)
        self.closed = False

    def close(self):
        self.closed = True


class FakeDayWindow:
    """Builds its own record, exactly as the real builder does.

    The real day window gets its record from service.load_day(), so it is a
    different dict from whatever the session was holding. If the session does
    not adopt it, stopping the timer saves one dict and refreshes another —
    and any hours typed into the window are overwritten.
    """

    def __init__(self, master, record=None):
        self.master = master
        self.data = type("Data", (), {"record": record or fresh_record(),
                                      "running": None})()
        self.refreshed = 0

    def refresh(self):
        self.refreshed += 1


def fresh_record():
    return {"date": "2026-08-17", "submitted_at": None,
            "entries": [], "segments": []}


def record():
    return {"date": "2026-08-17", "submitted_at": None,
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
        self.root = tk.Tk()
        self.root.withdraw()
        self.saved = []
        self.cleared = []
        self.built = []
        self.addCleanup(self._teardown)

        self.session = TimerSession(
            root=self.root,
            record=record(),
            save_day=self.saved.append,
            clear_timer=lambda: self.cleared.append(True),
            day_builder=self._build_day,
        )
        self.session.start_timer(
            lambda root: FakeStrip(ISSUE, datetime.now())
        )

    def _teardown(self):
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def _build_day(self, master, on_running):
        # The real builder calls service.load_day(), which reads the file. So
        # a window built after a save must see what was saved.
        loaded = deepcopy(self.saved[-1]) if self.saved else fresh_record()
        window = FakeDayWindow(master, loaded)
        window.on_running = on_running
        self.built.append(window)
        return window


class StoppingKeepsTheWindowYouHave(SessionTestCase):
    def test_the_same_window_survives_a_stop(self):
        self.session.show_day()
        toplevel = self.session.toplevel

        self.session.stop(segment())

        self.assertIs(self.session.toplevel, toplevel)
        self.assertTrue(toplevel.winfo_exists())

    def test_no_second_window_is_built(self):
        self.session.show_day()
        self.session.stop(segment())
        self.assertEqual(len(self.built), 1)

    def test_the_root_is_not_destroyed(self):
        self.session.show_day()
        self.session.stop(segment())
        self.assertTrue(self.root.winfo_exists())

    def test_the_finished_run_lands_in_that_window_s_record(self):
        day = self.session.show_day()
        self.session.stop(segment())

        self.assertEqual(dayview.total_seconds(day.data.record), 90 * 60)
        self.assertGreaterEqual(day.refreshed, 1)

    def test_the_day_is_saved(self):
        self.session.show_day()
        self.session.stop(segment())
        self.assertTrue(self.saved)

    def test_the_timer_file_is_cleared(self):
        self.session.show_day()
        self.session.stop(segment())
        self.assertTrue(self.cleared)


class StoppingWithNoWindowOpen(SessionTestCase):
    def test_a_window_is_built(self):
        self.session.stop(segment())

        self.assertEqual(len(self.built), 1)
        self.assertTrue(self.session.toplevel.winfo_exists())

    def test_the_time_is_in_it(self):
        self.session.stop(segment())
        self.assertEqual(dayview.total_seconds(self.session.record), 90 * 60)


class OneRecordNotTwo(SessionTestCase):
    """The window's record and the session's must be the same object, or a
    stop saves one and refreshes the other."""

    def test_the_session_adopts_the_window_s_record(self):
        day = self.session.show_day()
        self.assertIs(self.session.record, day.data.record)

    def test_hours_typed_before_a_stop_are_not_lost(self):
        day = self.session.show_day()
        day.data.record["entries"].append({
            "issue_key": "AP-1", "issue_id": 1, "summary": "typed by hand",
            "seconds": 2 * HOUR, "note": "", "source": "manual",
            "confirmed": True, "submitted": False, "tempo_worklog_id": None,
        })

        self.session.stop(segment())

        self.assertEqual(dayview.total_seconds(day.data.record),
                         2 * HOUR + 90 * 60)
        self.assertEqual(dayview.total_seconds(self.saved[-1]),
                         2 * HOUR + 90 * 60)


class ShowingTheDayTwice(SessionTestCase):
    def test_the_second_press_reuses_the_window(self):
        first = self.session.show_day()
        second = self.session.show_day()

        self.assertIs(first, second)
        self.assertEqual(len(self.built), 1)

    def test_a_closed_window_is_rebuilt(self):
        self.session.show_day()
        self.session.toplevel.destroy()
        self.root.update()

        self.session.show_day()
        self.assertEqual(len(self.built), 2)


class WhatTheDayWindowIsToldAboutTheTimer(SessionTestCase):
    def test_it_reports_the_running_state(self):
        self.session.show_day()
        self.assertEqual(self.session.running_state()["issue_key"], "AP-7500")

    def test_it_reports_nothing_once_stopped(self):
        self.session.show_day()
        self.session.stop(segment())
        self.assertIsNone(self.session.running_state())


class StartingATimerFromTheDayWindow(unittest.TestCase):
    """The ▶ button used to destroy the day window and rebuild it when the
    timer stopped, which is the restart the user actually saw."""

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.built = []
        self.addCleanup(self._teardown)

        self.session = TimerSession(
            root=self.root, record=record(), save_day=lambda r: None,
            clear_timer=lambda: None,
            day_builder=self._build_day,
        )

    def _teardown(self):
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def _build_day(self, master, on_running):
        window = FakeDayWindow(master)
        self.built.append(window)
        return window

    def test_the_day_window_survives_starting_a_timer(self):
        day = self.session.show_day()
        toplevel = self.session.toplevel

        self.session.start_timer(lambda root: FakeStrip(ISSUE, datetime.now()))

        self.assertIs(self.session.day, day)
        self.assertIs(self.session.toplevel, toplevel)
        self.assertTrue(toplevel.winfo_exists())

    def test_and_survives_the_stop_that_follows(self):
        self.session.show_day()
        toplevel = self.session.toplevel
        self.session.start_timer(lambda root: FakeStrip(ISSUE, datetime.now()))

        self.session.stop(segment())

        self.assertIs(self.session.toplevel, toplevel)
        self.assertEqual(len(self.built), 1, "only ever one window")

    def test_with_no_timer_running_nothing_is_reported_as_running(self):
        self.session.show_day()
        self.assertIsNone(self.session.running_state())

    def test_closing_the_day_with_no_timer_ends_the_run(self):
        self.session.show_day()
        self.session.toplevel.destroy()

        with self.assertRaises(tk.TclError):
            self.root.update()
            self.root.winfo_exists()


class TheWeekWindow(SessionTestCase):
    def setUp(self):
        super().setUp()
        self.weeks = []
        self.session.week_builder = self._build_week

    def _build_week(self, master):
        window = FakeDayWindow(master)
        self.weeks.append(window)
        return window

    def test_it_opens(self):
        self.session.show_week()

        self.assertEqual(len(self.weeks), 1)
        self.assertTrue(self.session.week_toplevel.winfo_exists())

    def test_pressing_again_reuses_it(self):
        first = self.session.show_week()
        second = self.session.show_week()

        self.assertIs(first, second)
        self.assertEqual(len(self.weeks), 1)

    def test_closing_it_ends_nothing(self):
        # It is somewhere you go to look and fix, not what holds the session
        # open. Closing it must not stop a running timer.
        self.session.show_week()
        self.session.week_toplevel.destroy()
        self.root.update()

        self.assertTrue(self.root.winfo_exists())
        self.assertTrue(self.session.timing)

    def test_a_closed_week_window_reopens(self):
        self.session.show_week()
        self.session.week_toplevel.destroy()
        self.root.update()

        self.session.show_week()
        self.assertEqual(len(self.weeks), 2)

    def test_it_can_be_open_alongside_the_day(self):
        self.session.show_day()
        self.session.show_week()

        self.assertTrue(self.session.day_is_open())
        self.assertTrue(self.session.week_is_open())


class ClosingTheDayWindow(SessionTestCase):
    def test_while_a_timer_runs_the_process_stays_alive(self):
        self.session.show_day()
        self.session.toplevel.destroy()
        self.root.update()

        self.assertTrue(self.root.winfo_exists(),
                        "closing the day must not kill a running timer")

    def test_once_the_timer_has_stopped_it_ends_the_run(self):
        # Otherwise an invisible root keeps the process alive forever.
        self.session.show_day()
        self.session.stop(segment())

        self.session.toplevel.destroy()

        # Destroying the root tears down the interpreter, so even asking
        # whether it still exists fails. That failure is the evidence.
        with self.assertRaises(tk.TclError):
            self.root.update()
            self.root.winfo_exists()


if __name__ == "__main__":
    unittest.main()
