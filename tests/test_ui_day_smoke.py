"""Does the day window actually build?

tkinter layout is not worth unit testing — but a typo, a missing token or a
bad pack() call raises, and finding that at 15:30 rather than here would be a
poor trade. These tests construct the real window against real data, pump the
event loop, and drive the interactions that change state.

Skipped automatically where there is no display.
"""

import tkinter as tk
import unittest
from datetime import date

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
        """Type into an hours field the way a person would."""
        field = window._fields[issue_key]
        field.delete(0, "end")
        field.focus_force()
        self.root.update()
        field.insert(0, text)
        field.event_generate("<KeyRelease>", keysym=text[-1])
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
        for name in ("dark", "light"):
            with self.subTest(theme=name):
                root = tk.Tk()
                root.withdraw()
                DayWindow(root, DayData(day=date(2026, 8, 17), record=record()),
                          DayCallbacks(), Theme(name))
                root.update()
                root.destroy()

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
        field.event_generate("<KeyRelease>", keysym="BackSpace")
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
        self.assertIn("SUGGESTIONS", labels)

    def test_ctrl_tab_switches_tabs(self):
        window = self.build()
        window._toggle_tab()
        self.assertEqual(window.tab, INTERNAL)
        window._toggle_tab()
        self.assertEqual(window.tab, MY_WORK)


if __name__ == "__main__":
    unittest.main()
