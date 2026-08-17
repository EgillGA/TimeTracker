"""Does the day window actually build?

tkinter layout is not worth unit testing — but a typo, a missing token or a
bad pack() call raises, and finding that at 15:30 rather than here would be a
poor trade. These tests construct the real window against real data, pump the
event loop, and drive the interactions that change state.

Skipped automatically where there is no display.
"""

import tkinter as tk
import unittest
from datetime import date, datetime, timedelta

from timetracker import dayview
from timetracker.theme import Theme
from timetracker.ui_day import INTERNAL, MY_WORK, DayCallbacks, DayData, DayWindow

HOUR = 3600

ASSIGNED = [
    {"key": "AP-7500", "id": 7500, "summary": "CRA252159 - 767 - ANG - LOPA change"},
    {"key": "AP-7429", "id": 7429, "summary": "MI252159-1 - PSU Drawing"},
]
INTERNAL_ISSUES = [
    {"key": "AI-1", "id": 1, "summary": "INTERNAL - WORK"},
    {"key": "AI-2", "id": 2, "summary": "INTERNAL - OTHER"},
    {"key": "AI-3", "id": 3, "summary": "INTERNAL - HOLIDAY"},
]


def record(entries=None):
    return {"date": "2026-08-17", "submitted_at": None,
            "entries": entries or [], "segments": []}


def _descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from _descendants(child)


def has_display():
    try:
        tk.Tk().destroy()
        return True
    except tk.TclError:
        return False


@unittest.skipUnless(has_display(), "no display available")
class DayWindowSmoke(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        # Tk delivers a synthetic key event only when the target widget holds
        # focus AND its toplevel is viewable — both, not either. A withdrawn
        # window silently drops every event_generate, which looks exactly like
        # a broken binding. Keep it viewable but fully transparent so the
        # tests neither flash on screen nor lie about what they exercised.
        self.root.geometry("720x560+40+40")
        self.root.attributes("-alpha", 0.0)
        self.saved = []
        self.started = []
        self.addCleanup(self._teardown)

    def add_then_type(self, window, issue_key, text):
        """The real flow: press + to bring an issue up, then type its hours."""
        rows = {r.issue_key: r for r in
                dayview.project_rows(window.data.record, window.data.assigned,
                                     window.data.internal)}
        window._add_to_today(rows[issue_key])
        self.root.update()
        return self.type_into(window, issue_key, text)

    def type_into(self, window, issue_key, text):
        """Type into an hours field the way a person would.

        Focus is a machine-wide resource and other tests in this file own
        windows too, so focus_force does not always land on the first pump of
        the event loop. Waiting for it makes the difference between a suite
        that fails one run in four and one that means something.
        """
        field = window._fields[issue_key]
        field.delete(0, "end")
        field.focus_force()

        for _ in range(100):
            self.root.update()
            if self.root.focus_get() is field:
                break
        else:
            self.fail("could not give the hours field focus")

        field.insert(0, text)
        self.assertEqual(field.get(), text,
                         "the harness failed to put the text in the field")

        # An arrow key rather than the typed character: the handler does not
        # care which key it was, and a character keysym can be interpreted by
        # Tk as real input, which intermittently ate the last letter.
        field.event_generate("<KeyRelease>", keysym="Right")
        self.root.update()
        return field

    def _teardown(self):
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def build(self, data=None, **callbacks):
        data = data or DayData(
            day=date(2026, 8, 17), record=record(),
            assigned=ASSIGNED, internal=INTERNAL_ISSUES,
            target_seconds=8 * HOUR,
        )
        defaults = {
            "on_change": self.saved.append,
            "on_submit": lambda r: [],
            "on_start_timer": self.started.append,
            "on_lookup": lambda key: None,
            "on_close": lambda: None,
            "on_running": None,
        }
        defaults.update(callbacks)
        window = DayWindow(self.root, data, DayCallbacks(**defaults))
        self.root.update()
        return window

    # -- it builds ----------------------------------------------------------

    def test_an_empty_day_builds(self):
        window = self.build()
        self.assertEqual(window.tab, MY_WORK)

    def test_a_day_with_tracked_entries_builds(self):
        data = DayData(
            day=date(2026, 8, 17),
            record=record([
                {"issue_key": "AP-7500", "issue_id": 7500, "summary": "LOPA",
                 "seconds": 3 * HOUR, "source": "timer", "confirmed": False,
                 "submitted": False, "tempo_worklog_id": None, "note": ""},
                {"issue_key": "AI-1", "issue_id": 1, "summary": "INTERNAL - WORK",
                 "seconds": HOUR, "source": "manual", "confirmed": True,
                 "submitted": True, "tempo_worklog_id": 46580, "note": ""},
            ]),
            assigned=ASSIGNED, internal=INTERNAL_ISSUES,
        )
        self.build(data)

    def test_both_themes_build(self):
        # A Toplevel rather than a second tk.Tk: two Tk instances in one
        # process fight over focus, which is what made the typing tests flaky.
        for name in ("dark", "light"):
            with self.subTest(theme=name):
                window = tk.Toplevel(self.root)
                DayWindow(window,
                          DayData(day=date(2026, 8, 17), record=record()),
                          DayCallbacks(), Theme(name))
                self.root.update()
                window.destroy()

    def test_the_internal_tab_builds(self):
        window = self.build()
        window.show_tab(INTERNAL)
        self.root.update()
        self.assertEqual(window.tab, INTERNAL)

    # -- interactions change state -----------------------------------------

    def test_typing_hours_updates_the_record(self):
        data = DayData(day=date(2026, 8, 17), record=record(),
                       assigned=ASSIGNED, internal=[])
        window = self.build(data)

        self.add_then_type(window, "AP-7500","1,5")

        self.assertEqual(dayview.total_seconds(data.record), 90 * 60)
        self.assertTrue(self.saved, "the change should have been persisted")

    def test_typing_does_not_steal_focus_from_the_field(self):
        # Rebuilding rows on every keystroke would drop the caret mid-number.
        data = DayData(day=date(2026, 8, 17), record=record(),
                       assigned=ASSIGNED, internal=[])
        window = self.build(data)

        field = self.add_then_type(window, "AP-7500", "1,5")
        self.assertEqual(self.root.focus_get(), field)
        self.assertEqual(field.get(), "1,5")

    def test_invalid_hours_do_not_reach_the_record(self):
        data = DayData(day=date(2026, 8, 17), record=record(),
                       assigned=ASSIGNED, internal=[])
        window = self.build(data)

        self.add_then_type(window, "AP-7500","all morning")

        self.assertEqual(dayview.total_seconds(data.record), 0)

    def test_invalid_hours_are_flagged_but_not_erased(self):
        data = DayData(day=date(2026, 8, 17), record=record(),
                       assigned=ASSIGNED, internal=[])
        window = self.build(data)

        field = self.add_then_type(window, "AP-7500", "all morning")
        self.assertEqual(field.get(), "all morning")
        self.assertEqual(str(field.cget("highlightbackground")),
                         window.theme["danger"])

    def test_clearing_a_field_zeroes_the_row(self):
        data = DayData(day=date(2026, 8, 17), record=record(),
                       assigned=ASSIGNED, internal=[])
        window = self.build(data)

        self.add_then_type(window, "AP-7500","3")
        self.assertEqual(dayview.total_seconds(data.record), 3 * HOUR)

        field = window._fields["AP-7500"]
        field.delete(0, "end")
        field.event_generate("<KeyRelease>", keysym="Right")
        self.root.update()

        self.assertEqual(dayview.total_seconds(data.record), 0)

    def test_adding_from_the_internal_tab_returns_to_my_work(self):
        data = DayData(day=date(2026, 8, 17), record=record(),
                       assigned=[], internal=INTERNAL_ISSUES)
        window = self.build(data)
        window.show_tab(INTERNAL)
        self.root.update()

        window._add_to_today(
            dayview.internal_rows(data.record, INTERNAL_ISSUES)[0]
        )
        self.root.update()

        self.assertEqual(window.tab, MY_WORK)
        self.assertEqual(data.record["entries"][0]["issue_key"], "AI-1")

    def test_adding_an_issue_gives_it_an_hours_box_with_the_caret_in_it(self):
        # The point of + is that valuing the row is the very next keystroke.
        data = DayData(day=date(2026, 8, 17), record=record(),
                       assigned=ASSIGNED, internal=[])
        window = self.build(data)

        # focus_set only lands within a toplevel that itself holds focus. In
        # use the window has just been clicked; here it has to be said aloud.
        self.root.focus_force()
        self.root.update()

        row = dayview.project_rows(data.record, ASSIGNED, [])[0]
        window._add_to_today(row)
        self.root.update()

        self.assertIn("AP-7500", window._fields)
        self.assertEqual(self.root.focus_get(), window._fields["AP-7500"])

    def test_an_issue_not_yet_added_has_no_hours_box(self):
        data = DayData(day=date(2026, 8, 17), record=record(),
                       assigned=ASSIGNED, internal=[])
        self.build(data)
        self.assertEqual(self.build(data)._fields, {})

    def test_fill_remaining_tops_up_the_last_row(self):
        data = DayData(
            day=date(2026, 8, 17),
            record=record([{"issue_key": "AP-7500", "issue_id": 7500,
                            "summary": "LOPA", "seconds": 6 * HOUR,
                            "source": "manual", "confirmed": True,
                            "submitted": False, "tempo_worklog_id": None,
                            "note": ""}]),
            target_seconds=8 * HOUR,
        )
        window = self.build(data)
        window._fill_remaining()
        self.root.update()

        self.assertEqual(data.record["entries"][0]["seconds"], 8 * HOUR)

    def test_a_failed_submission_shows_tempo_s_message_on_the_row(self):
        data = DayData(
            day=date(2026, 8, 17),
            record=record([{"issue_key": "AP-7500", "issue_id": 7500,
                            "summary": "LOPA", "seconds": HOUR,
                            "source": "manual", "confirmed": True,
                            "submitted": False, "tempo_worklog_id": None,
                            "note": ""}]),
        )
        window = self.build(data, on_submit=lambda r: [
            {"issue_key": "AP-7500", "ok": False,
             "message": "Period is closed for the given date"}
        ])
        window._submit()
        self.root.update()

        self.assertIn("Period is closed", window.row_status["AP-7500"])

    def test_starting_a_timer_reports_the_issue(self):
        data = DayData(day=date(2026, 8, 17), record=record(),
                       assigned=ASSIGNED, internal=[])
        window = self.build(data)
        window._start_timer(
            dayview.project_rows(data.record, ASSIGNED, [])[0]
        )
        self.assertEqual(self.started[0]["key"], "AP-7500")

    def test_hours_are_shown_as_hours_and_minutes(self):
        data = DayData(
            day=date(2026, 8, 17),
            record=record([{"issue_key": "AP-7500", "issue_id": 7500,
                            "summary": "LOPA", "seconds": 5400,
                            "source": "manual", "confirmed": True,
                            "submitted": False, "tempo_worklog_id": None,
                            "note": ""}]),
            target_seconds=8 * HOUR,
        )
        window = self.build(data)

        self.assertEqual(window._fields["AP-7500"].get(), "1:30")
        self.assertEqual(window.total_label.cget("text"), "1:30 of 8:00")
        self.assertEqual(window.submit_button.cget("text"), "Submit 1:30")
        self.assertEqual(window.unaccounted_label.cget("text"),
                         "6:30 unaccounted")

    def test_a_tracked_row_can_be_removed(self):
        data = DayData(
            day=date(2026, 8, 17),
            record=record([{"issue_key": "AP-7500", "issue_id": 7500,
                            "summary": "LOPA", "seconds": 3 * HOUR,
                            "source": "manual", "confirmed": True,
                            "submitted": False, "tempo_worklog_id": None,
                            "note": ""}]),
        )
        window = self.build(data)
        window._remove(dayview.tracked_rows(data.record)[0])
        self.root.update()

        self.assertEqual(data.record["entries"], [])

    def test_removing_a_row_clears_any_error_shown_against_it(self):
        data = DayData(
            day=date(2026, 8, 17),
            record=record([{"issue_key": "AP-7500", "issue_id": 7500,
                            "summary": "LOPA", "seconds": HOUR,
                            "source": "manual", "confirmed": True,
                            "submitted": False, "tempo_worklog_id": None,
                            "note": ""}]),
        )
        window = self.build(data, on_submit=lambda r: [
            {"issue_key": "AP-7500", "ok": False, "message": "Period is closed"}
        ])
        window._submit()
        self.root.update()
        self.assertIn("AP-7500", window.row_status)

        window._remove(dayview.tracked_rows(data.record)[0])
        self.root.update()
        self.assertNotIn("AP-7500", window.row_status)

    def submitted_day(self):
        return DayData(
            day=date(2026, 8, 17),
            record=record([{"issue_key": "AP-7492", "issue_id": 7492,
                            "summary": "EEL change", "seconds": 4 * HOUR,
                            "source": "manual", "confirmed": True,
                            "submitted": True, "tempo_worklog_id": 46604,
                            "note": ""}]),
        )

    def test_an_already_submitted_issue_still_takes_more_hours(self):
        # Four hours are in Tempo; the afternoon on the same issue must be
        # loggable without hunting for a workaround.
        data = self.submitted_day()
        window = self.build(data)

        self.assertIn("AP-7492", window._fields)
        labels = [w.cget("text") for w in _descendants(self.root)
                  if isinstance(w, tk.Label)]
        self.assertIn("4:00 logged", labels)

    def test_hours_typed_on_a_submitted_issue_become_a_sendable_row(self):
        data = self.submitted_day()
        window = self.build(data)
        self.type_into(window, "AP-7492", "2")

        pending = dayview.entries_to_submit(data.record)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["seconds"], 2 * HOUR)
        self.assertEqual(dayview.total_seconds(data.record), 6 * HOUR)

    def test_a_submitted_issue_shows_as_one_row_not_two(self):
        data = self.submitted_day()
        window = self.build(data)
        self.type_into(window, "AP-7492", "2")
        window.refresh()
        self.root.update()

        keys = [w.cget("text") for w in _descendants(self.root)
                if isinstance(w, tk.Label) and w.cget("text") == "AP-7492"]
        self.assertEqual(len(keys), 1)

    def test_the_logged_part_cannot_be_removed(self):
        # Its hours are in Tempo and nothing here can unlog them.
        window = self.build(self.submitted_day())
        labels = [w.cget("text") for w in _descendants(self.root)
                  if isinstance(w, tk.Label)]
        self.assertNotIn("✕", labels)

    def running_state(self, minutes=42):
        started = datetime.now() - timedelta(minutes=minutes)
        return {"issue_key": "AP-7500", "issue_id": 7500,
                "summary": "LOPA change",
                "started_at": started.isoformat(),
                "last_heartbeat": started.isoformat(),
                "last_confirmed_at": started.isoformat(),
                "paused_total_seconds": 0, "paused_at": None}

    def test_a_running_timer_shows_in_tracked_today(self):
        window = self.build(DayData(day=date(2026, 8, 17), record=record(),
                                    assigned=ASSIGNED,
                                    running=self.running_state()))
        labels = [w.cget("text") for w in _descendants(self.root)
                  if isinstance(w, tk.Label)]

        self.assertIn("TRACKED TODAY", labels)
        self.assertIn("AP-7500", labels)
        self.assertTrue([t for t in labels if t.startswith("● 0:42")])

    def test_running_time_counts_toward_the_header_total(self):
        window = self.build(DayData(day=date(2026, 8, 17), record=record(),
                                    running=self.running_state(minutes=90)))
        self.assertEqual(window.total_label.cget("text"), "1:30 of 8:00")

    def test_running_time_is_not_offered_for_submission(self):
        # It is not in the record and cannot be sent until the timer stops.
        data = DayData(day=date(2026, 8, 17), record=record(),
                       running=self.running_state(minutes=90))
        window = self.build(data)

        self.assertEqual(window.submit_button.cget("text"), "Submit")
        self.assertEqual(dayview.entries_to_submit(data.record), [])

    def test_the_running_issue_is_not_also_offered_under_projects(self):
        window = self.build(DayData(
            day=date(2026, 8, 17), record=record(),
            assigned=[{"key": "AP-7500", "id": 7500, "summary": "LOPA change"}],
            running=self.running_state(),
        ))
        keys = [w.cget("text") for w in _descendants(self.root)
                if isinstance(w, tk.Label) and w.cget("text") == "AP-7500"]
        self.assertEqual(len(keys), 1)

    def test_the_timer_state_is_re_asked_not_remembered(self):
        """Pausing on the strip must stop the window counting.

        The window used to hold a snapshot taken when it opened, so it carried
        on ticking against a timer that had been paused minutes earlier."""
        live = {"state": self.running_state(minutes=10)}
        window = self.build(
            DayData(day=date(2026, 8, 17), record=record()),
            on_running=lambda: live["state"],
        )
        first = window.running_row()["seconds"]

        # Pause it, as the strip would.
        live["state"] = dict(live["state"],
                             paused_at=datetime.now().isoformat())
        window._tick_running()
        self.root.update()

        frozen = window.running_row()["seconds"]
        self.assertLessEqual(abs(frozen - first), 2)
        self.assertTrue(window.running_row(), "a paused timer still shows")

    def test_stopping_the_timer_removes_the_row(self):
        live = {"state": self.running_state()}
        window = self.build(
            DayData(day=date(2026, 8, 17), record=record(), assigned=ASSIGNED),
            on_running=lambda: live["state"],
        )
        self.assertIsNotNone(window.running_row())

        live["state"] = None
        window._tick_running()
        self.root.update()

        labels = [w.cget("text") for w in _descendants(self.root)
                  if isinstance(w, tk.Label)]
        self.assertEqual([t for t in labels if t.startswith("● ")], [])

    def test_a_stopped_run_appears_in_the_same_window(self):
        """Stopping the timer must not need a new window.

        The old code destroyed the root and built a fresh day window, which
        read as the window closing and reopening. Folding the finished run
        into the record the window already holds and refreshing keeps it."""
        live = {"state": self.running_state(minutes=90)}
        data = DayData(day=date(2026, 8, 17), record=record(),
                       assigned=ASSIGNED)
        window = self.build(data, on_running=lambda: live["state"])
        toplevel_before = window.master

        # What on_stop does: fold the segment in, drop the timer, refresh.
        dayview.add_segment(data.record, {
            "issue_key": "AP-7500", "issue_id": 7500, "summary": "LOPA change",
            "seconds": 90 * 60, "start": "2026-08-17T09:00:00",
            "end": "2026-08-17T10:30:00", "confirmed": True,
        })
        live["state"] = None
        window.refresh()
        self.root.update()

        self.assertIs(window.master, toplevel_before,
                      "the same window must still be the one on screen")
        self.assertTrue(window.master.winfo_exists())
        self.assertEqual(dayview.total_seconds(data.record), 90 * 60)
        self.assertEqual(window._fields["AP-7500"].get(), "1:30")

        labels = [w.cget("text") for w in _descendants(self.root)
                  if isinstance(w, tk.Label)]
        self.assertEqual([t for t in labels if t.startswith("● ")], [],
                         "the live figure should be gone")

    def test_no_running_timer_means_no_live_figure(self):
        window = self.build()
        labels = [w.cget("text") for w in _descendants(self.root)
                  if isinstance(w, tk.Label)]
        self.assertEqual([t for t in labels if t.startswith("● ")], [])

    def test_the_footer_has_equal_padding_above_and_below(self):
        window = self.build()
        info = window.footer.pack_info()
        self.assertEqual(str(info["pady"]), str(window.theme.space["lg"]))

    def test_there_is_no_scrollbar(self):
        window = self.build()
        scrollbars = [
            child for child in _descendants(self.root)
            if isinstance(child, tk.Scrollbar)
        ]
        self.assertEqual(scrollbars, [])

    def test_a_long_section_collapses_and_says_how_many_are_hidden(self):
        # Without a scrollbar, a list that runs past the window bottom is
        # invisible. The section has to admit it is holding rows back.
        many = [{"key": f"AP-{n}", "id": n, "summary": f"issue {n}"}
                for n in range(16)]
        window = self.build(DayData(day=date(2026, 8, 17), record=record(),
                                    assigned=many))

        labels = [w.cget("text") for w in _descendants(self.root)
                  if isinstance(w, tk.Label)]
        self.assertIn("+ 11 more", labels)

    def test_expanding_a_section_shows_the_rest(self):
        many = [{"key": f"AP-{n}", "id": n, "summary": f"issue {n}"}
                for n in range(16)]
        window = self.build(DayData(day=date(2026, 8, 17), record=record(),
                                    assigned=many))
        window._toggle_section("Projects")
        self.root.update()

        labels = [w.cget("text") for w in _descendants(self.root)
                  if isinstance(w, tk.Label)]
        shown = [text for text in labels if text.startswith("AP-")]

        self.assertEqual(len(shown), 16)
        self.assertIn("show fewer", labels)

    def test_a_short_section_has_no_toggle(self):
        window = self.build(DayData(day=date(2026, 8, 17), record=record(),
                                    assigned=ASSIGNED))
        labels = [w.cget("text") for w in _descendants(self.root)
                  if isinstance(w, tk.Label)]
        self.assertNotIn("show fewer", labels)
        self.assertFalse([t for t in labels if t.startswith("+ ")])

    def test_projects_and_suggestions_are_separate_sections(self):
        window = self.build(DayData(
            day=date(2026, 8, 17), record=record(),
            assigned=[{"key": "AP-7500", "id": 7500, "summary": "LOPA"}],
            recent=[{"key": "AP-9000", "id": 9000, "summary": "someone else's"}],
        ))
        labels = [w.cget("text") for w in _descendants(self.root)
                  if isinstance(w, tk.Label)]

        self.assertIn("PROJECTS", labels)
        # Suggestions is a dropdown: shut, with its count on the heading.
        suggestions = [text for text in labels if "SUGGESTIONS" in text]
        self.assertEqual(len(suggestions), 1)
        self.assertIn("▸", suggestions[0])
        self.assertNotIn("AP-9000", labels)

    def test_the_suggestions_dropdown_opens(self):
        window = self.build(DayData(
            day=date(2026, 8, 17), record=record(),
            assigned=[{"key": "AP-7500", "id": 7500, "summary": "LOPA"}],
            recent=[{"key": "AP-9000", "id": 9000, "summary": "someone else's"}],
        ))
        window._toggle_section("Suggestions")
        self.root.update()

        labels = [w.cget("text") for w in _descendants(self.root)
                  if isinstance(w, tk.Label)]
        self.assertIn("AP-9000", labels)
        self.assertIn("▾", [t for t in labels if "SUGGESTIONS" in t][0])

    def test_suggestions_are_capped(self):
        many = [{"key": f"AP-{n}", "id": n, "summary": f"issue {n}"}
                for n in range(20)]
        window = self.build(DayData(day=date(2026, 8, 17), record=record(),
                                    recent=many, suggestion_count=5))
        window._toggle_section("Suggestions")
        self.root.update()

        labels = [w.cget("text") for w in _descendants(self.root)
                  if isinstance(w, tk.Label)]
        self.assertEqual(len([t for t in labels if t.startswith("AP-")]), 5)

    def test_ctrl_tab_switches_tabs(self):
        window = self.build()
        window._toggle_tab()
        self.assertEqual(window.tab, INTERNAL)
        window._toggle_tab()
        self.assertEqual(window.tab, MY_WORK)


if __name__ == "__main__":
    unittest.main()
