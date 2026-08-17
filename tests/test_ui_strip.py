"""The always-on-top timer strip.

The geometry is pure arithmetic and tested as such: parking the strip over the
taskbar, or off the edge of a screen that changed while you were docked, is
how a small always-visible window becomes unusable.
"""

import tkinter as tk
import unittest
from datetime import datetime, timedelta

from timetracker.config import Config, default_jql
from timetracker.ui_strip import (
    StripCallbacks,
    TimerStrip,
    shorten,
    strip_position,
)

ISSUE = {"key": "AP-7500", "id": 7500, "summary": "CRA252159 LOPA change"}
NINE = datetime(2026, 8, 17, 9, 0, 0)

# A 1920x1080 screen with a 40px taskbar along the bottom.
WORK_AREA = (0, 0, 1920, 1040)


def config(**overrides):
    values = dict(
        jira_site="x", jira_email="x", hours_per_day=8.0, prompt_time="15:30",
        week_view_day="friday", day_starts_at="08:00", checkin_minutes=60,
        heartbeat_seconds=30, theme="dark", internal_project="AI",
        jql=default_jql("AI"),
    )
    values.update(overrides)
    return Config(**values)


class WhereTheStripParks(unittest.TestCase):
    def test_bottom_right_of_the_work_area(self):
        # The work area excludes the taskbar, so this sits above the clock.
        x, y = strip_position(WORK_AREA, width=260, height=36, margin=12)

        self.assertEqual(x, 1920 - 260 - 12)
        self.assertEqual(y, 1040 - 36 - 12)

    def test_it_never_covers_the_taskbar(self):
        _, y = strip_position(WORK_AREA, width=260, height=36, margin=12)
        self.assertLessEqual(y + 36, 1040)

    def test_a_work_area_that_does_not_start_at_zero(self):
        # Taskbar on the left, or a second monitor above and to the left.
        x, y = strip_position((80, 0, 2000, 1040), width=260, height=36,
                              margin=12)
        self.assertEqual(x, 2000 - 260 - 12)
        self.assertEqual(y, 1040 - 36 - 12)

    def test_a_strip_wider_than_the_screen_is_pulled_back_on(self):
        # Disconnecting a monitor can leave a tiny work area behind.
        x, y = strip_position((0, 0, 200, 200), width=260, height=36, margin=12)

        self.assertGreaterEqual(x, 0)
        self.assertGreaterEqual(y, 0)

    def test_negative_origins_are_respected(self):
        # A monitor arranged left of the primary one has negative coordinates.
        x, _ = strip_position((-1920, 0, 0, 1040), width=260, height=36,
                              margin=12)
        self.assertEqual(x, 0 - 260 - 12)


class FittingTheTitleOnTheStrip(unittest.TestCase):
    """Real summaries run to sixty characters. The strip has room for about
    half that, and tkinter labels do not ellipsize on their own."""

    def test_a_short_title_is_left_alone(self):
        self.assertEqual(shorten("PSU Drawing", limit=26), "PSU Drawing")

    def test_a_long_title_is_cut_with_an_ellipsis(self):
        result = shorten("CRA252159 - 767 - ANG - ISN/O LOPA change", limit=26)

        self.assertEqual(len(result), 26)
        self.assertTrue(result.endswith("…"))
        self.assertTrue(result.startswith("CRA252159"))

    def test_a_title_exactly_at_the_limit_is_not_cut(self):
        text = "a" * 26
        self.assertEqual(shorten(text, limit=26), text)

    def test_no_ragged_space_before_the_ellipsis(self):
        self.assertEqual(shorten("hello world again", limit=12), "hello world…")

    def test_runs_of_whitespace_are_collapsed(self):
        self.assertEqual(shorten("EEL  change\n A320", limit=26),
                         "EEL change A320")

    def test_an_empty_title_is_empty(self):
        self.assertEqual(shorten("", limit=26), "")

    def test_a_missing_title_does_not_crash(self):
        self.assertEqual(shorten(None, limit=26), "")


def has_display():
    try:
        tk.Tk().destroy()
        return True
    except tk.TclError:
        return False


@unittest.skipUnless(has_display(), "no display available")
class TheStripItself(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.persisted = []
        self.stopped = []
        self.addCleanup(self._teardown)

    def _teardown(self):
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def build(self, now=NINE, **overrides):
        settings = overrides.pop("config", config())
        strip = TimerStrip(
            self.root, ISSUE, settings,
            StripCallbacks(on_persist=self.persisted.append,
                           on_stop=self.stopped.append,
                           on_open_day=lambda: None),
            now=now,
        )
        self.root.update()
        return strip

    def test_it_builds_and_shows_the_issue(self):
        strip = self.build()
        self.assertIn("AP-7500", strip.key_label.cget("text"))

    def test_the_title_is_on_the_strip(self):
        # The key alone does not say what you are working on.
        strip = self.build()
        self.assertIn("CRA252159", strip.summary_label.cget("text"))

    def test_a_long_title_is_trimmed_to_fit(self):
        long_issue = dict(ISSUE, summary="CRA252159 - 767 - ANG - "
                                         "ISN/O LOPA change for Icelandair")
        strip = TimerStrip(self.root, long_issue, config(),
                           StripCallbacks(), now=NINE)
        self.root.update()

        self.assertTrue(strip.summary_label.cget("text").endswith("…"))

    def test_the_check_in_names_the_title_too(self):
        strip = self.build()
        strip.tick(NINE + timedelta(minutes=61))
        self.assertIn("CRA252159", strip.checkin_question.cget("text"))

    def test_the_elapsed_time_reads_as_a_clock(self):
        strip = self.build()
        strip.tick(NINE + timedelta(minutes=62, seconds=47))
        self.assertEqual(strip.time_label.cget("text"), "1:02:47")

    def test_it_starts_running_not_paused(self):
        self.assertFalse(self.build().is_paused())

    def test_hovering_reveals_controls_with_room_to_be_seen(self):
        """The title is packed on the left; if it is given space before the
        controls on the right, they get allocated nothing and vanish."""
        long_issue = dict(ISSUE, summary="CRA252159 - 767 - ANG - "
                                         "ISN/O LOPA change for Icelandair")
        strip = TimerStrip(self.root, long_issue, config(),
                           StripCallbacks(), now=NINE)
        strip._expand()
        self.root.update()

        for name, button in (("pause", strip.pause_button),
                             ("stop", strip.stop_button),
                             ("expand", strip.open_button)):
            with self.subTest(button=name):
                self.assertTrue(button.winfo_ismapped(),
                                f"the {name} button is not on screen")
                self.assertGreater(button.winfo_width(), 1,
                                   f"the {name} button has no width")

    def test_the_clock_keeps_its_room_when_the_title_is_long(self):
        long_issue = dict(ISSUE, summary="x" * 200)
        strip = TimerStrip(self.root, long_issue, config(),
                           StripCallbacks(), now=NINE)
        self.root.update()

        self.assertTrue(strip.time_label.winfo_ismapped())
        self.assertGreater(strip.time_label.winfo_width(), 1)

    def test_pausing_freezes_the_display(self):
        strip = self.build()
        strip.toggle_pause(NINE + timedelta(minutes=30))

        strip.tick(NINE + timedelta(minutes=90))
        self.assertEqual(strip.time_label.cget("text"), "0:30:00")
        self.assertTrue(strip.is_paused())

    def test_resuming_carries_on(self):
        strip = self.build()
        strip.toggle_pause(NINE + timedelta(minutes=30))
        strip.toggle_pause(NINE + timedelta(minutes=90))

        strip.tick(NINE + timedelta(minutes=100))
        self.assertEqual(strip.time_label.cget("text"), "0:40:00")

    def test_a_paused_strip_looks_different_at_a_glance(self):
        strip = self.build()
        running = strip.dot.cget("fg")
        strip.toggle_pause(NINE + timedelta(minutes=30))

        self.assertNotEqual(strip.dot.cget("fg"), running)

    def test_stopping_hands_over_the_finished_segment(self):
        strip = self.build()
        strip.stop(NINE + timedelta(minutes=90))

        self.assertEqual(len(self.stopped), 1)
        self.assertEqual(self.stopped[0]["issue_key"], "AP-7500")
        self.assertEqual(self.stopped[0]["seconds"], 90 * 60)

    def test_the_timer_is_on_disk_the_moment_it_starts(self):
        """Nothing else can see the timer until it is written down.

        Waiting for the first heartbeat left a half-minute window where the
        day window found no timer and showed no running row, and where a crash
        lost the run entirely."""
        self.build()

        self.assertTrue(self.persisted, "the strip must persist on start")
        self.assertEqual(self.persisted[0]["issue_key"], "AP-7500")

    def test_state_is_written_to_disk_as_it_runs(self):
        # A crash costs at most one heartbeat, not the whole afternoon.
        strip = self.build()
        strip.tick(NINE + timedelta(seconds=31))

        self.assertEqual(len(self.persisted), 2)
        self.assertEqual(self.persisted[-1]["issue_key"], "AP-7500")

    def test_it_does_not_write_on_every_single_tick(self):
        strip = self.build()
        writes_after_start = len(self.persisted)

        strip.tick(NINE + timedelta(seconds=1))
        strip.tick(NINE + timedelta(seconds=2))

        self.assertEqual(len(self.persisted), writes_after_start)

    def test_the_heartbeat_it_writes_on_start_is_current(self):
        # A stale first heartbeat would read as a crashed timer, and its time
        # would be recovered out from under the running strip.
        self.build()
        self.assertEqual(self.persisted[0]["last_heartbeat"], NINE.isoformat())

    def test_the_check_in_appears_after_an_hour(self):
        strip = self.build()
        self.assertFalse(strip.checkin_visible)

        strip.tick(NINE + timedelta(minutes=61))
        self.assertTrue(strip.checkin_visible)

    def test_answering_the_check_in_hides_it(self):
        strip = self.build()
        strip.tick(NINE + timedelta(minutes=61))
        strip.keep_going(NINE + timedelta(minutes=61))

        self.assertFalse(strip.checkin_visible)

    def test_answering_means_the_time_stays_trusted(self):
        strip = self.build()
        strip.tick(NINE + timedelta(minutes=61))
        strip.keep_going(NINE + timedelta(minutes=61))
        strip.stop(NINE + timedelta(minutes=90))

        self.assertTrue(self.stopped[0]["confirmed"])

    def test_ignoring_the_check_in_flags_the_time_but_keeps_running(self):
        # Never stop the timer for someone. Tell them; do not overrule them.
        strip = self.build()
        strip.tick(NINE + timedelta(minutes=200))
        strip.stop(NINE + timedelta(minutes=201))

        self.assertEqual(self.stopped[0]["seconds"], 201 * 60)
        self.assertFalse(self.stopped[0]["confirmed"])

    def test_a_paused_timer_is_never_asked_to_check_in(self):
        strip = self.build()
        strip.toggle_pause(NINE + timedelta(minutes=5))
        strip.tick(NINE + timedelta(minutes=200))

        self.assertFalse(strip.checkin_visible)

    def test_the_check_in_interval_is_configurable(self):
        strip = self.build(config=config(checkin_minutes=30))
        strip.tick(NINE + timedelta(minutes=31))
        self.assertTrue(strip.checkin_visible)


if __name__ == "__main__":
    unittest.main()
