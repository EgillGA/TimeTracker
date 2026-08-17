"""The 15:30 window.

Deliberately thin: every decision about what to show or send lives in
dayview.py, and every colour and measurement in theme.py. What is left here is
layout and event wiring.

Plain tk widgets rather than ttk throughout, because ttk on Windows fights
attempts to colour it and the result is a window that looks half-themed.
"""

import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass, field
from datetime import date

from timetracker import dayview
from timetracker.dayview import DayData
from timetracker.duration import InvalidDuration, format_hm, parse_hours
from timetracker.theme import Theme


@dataclass
class DayCallbacks:
    on_change: callable = lambda record: None
    on_submit: callable = lambda record: []
    on_start_timer: callable = lambda issue: None
    on_lookup: callable = lambda key: None
    on_close: callable = lambda: None


MY_WORK, INTERNAL = "My work", "Internal"


class DayWindow:
    def __init__(self, master, data, callbacks=None, theme=None):
        self.master = master
        self.data = data
        self.callbacks = callbacks or DayCallbacks()
        self.theme = (theme or Theme()).resolve_mono(
            available_families=_installed_families(master)
        )
        self.tab = MY_WORK
        self.row_status = {}
        self._fields = {}

        master.title(f"TimeTracker — {data.day:%A %d %B}")
        master.configure(bg=self.theme["bg"])
        width, height = self.theme.metrics["day_window"]
        master.geometry(f"{width}x{height}")
        master.minsize(560, 420)

        self._build()
        self._bind_keys()
        self.refresh()

    # -- construction -------------------------------------------------------

    def _build(self):
        pad = self.theme.space["lg"]

        self.header = tk.Frame(self.master, bg=self.theme["bg"])
        self.header.pack(fill="x", padx=pad, pady=(pad, 0))

        self.title_label = tk.Label(
            self.header, text="Today", bg=self.theme["bg"],
            fg=self.theme["text"], font=self.theme.font("heading"), anchor="w",
        )
        self.title_label.pack(side="left")

        self.total_label = tk.Label(
            self.header, bg=self.theme["bg"], fg=self.theme["text"],
            font=self.theme.font("number_large"), anchor="e",
        )
        self.total_label.pack(side="right")

        self.progress = tk.Canvas(
            self.master, height=6, bg=self.theme["surface"],
            highlightthickness=0, bd=0,
        )
        self.progress.pack(fill="x", padx=pad, pady=(self.theme.space["sm"], 0))

        self.banner = tk.Label(
            self.master, bg=self.theme["bg"], fg=self.theme["warn"],
            font=self.theme.font("small"), anchor="w", justify="left",
            wraplength=self.theme.metrics["day_window"][0] - 2 * pad,
        )

        self._build_tabs(pad)
        self._build_list(pad)
        self._build_footer(pad)

    def _build_tabs(self, pad):
        self.tabs = tk.Frame(self.master, bg=self.theme["bg"])
        self.tabs.pack(fill="x", padx=pad, pady=(self.theme.space["md"], 0))

        self.tab_buttons = {}
        for name in (MY_WORK, INTERNAL):
            button = tk.Label(
                self.tabs, text=name, bg=self.theme["bg"],
                fg=self.theme["text_muted"], font=self.theme.font("body"),
                padx=self.theme.space["md"], pady=self.theme.space["sm"],
                cursor="hand2",
            )
            button.pack(side="left")
            button.bind("<Button-1>", lambda _e, n=name: self.show_tab(n))
            self.tab_buttons[name] = button

        self.tab_rule = tk.Frame(self.master, bg=self.theme["border"], height=1)
        self.tab_rule.pack(fill="x", padx=pad)

    def _build_list(self, pad):
        container = tk.Frame(self.master, bg=self.theme["bg"])
        container.pack(fill="both", expand=True, padx=pad)

        # No scrollbar: the list is short by design — nine or so issues — and
        # a permanent grey bar down the side is more visual noise than the
        # rare overflow is worth. The wheel still scrolls.
        self.canvas = tk.Canvas(
            container, bg=self.theme["bg"], highlightthickness=0, bd=0
        )
        self.canvas.pack(side="left", fill="both", expand=True)

        self.list_frame = tk.Frame(self.canvas, bg=self.theme["bg"])
        self._list_window = self.canvas.create_window(
            (0, 0), window=self.list_frame, anchor="nw"
        )
        self.list_frame.bind(
            "<Configure>",
            lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self.canvas.bind(
            "<Configure>",
            lambda e: self.canvas.itemconfigure(self._list_window, width=e.width),
        )
        self.canvas.bind_all("<MouseWheel>", self._on_wheel)

    def _build_footer(self, pad):
        self.footer = tk.Frame(self.master, bg=self.theme["bg"])
        self.footer.pack(fill="x", padx=pad, pady=(0, pad))

        self.unaccounted_label = tk.Label(
            self.footer, bg=self.theme["bg"], fg=self.theme["text_muted"],
            font=self.theme.font("small"), anchor="w",
        )
        self.unaccounted_label.pack(side="left")

        self.fill_button = self._button(
            self.footer, "Fill remaining", self._fill_remaining, primary=False
        )
        self.fill_button.pack(side="left", padx=self.theme.space["sm"])

        self.submit_button = self._button(
            self.footer, "Submit", self._submit, primary=True
        )
        self.submit_button.pack(side="right")

        self.close_button = self._button(
            self.footer, "Close", self._close, primary=False
        )
        self.close_button.pack(side="right", padx=self.theme.space["sm"])

    def _button(self, parent, text, command, primary):
        colors = (
            (self.theme["accent"], self.theme["accent_text"])
            if primary else (self.theme["surface"], self.theme["text"])
        )
        button = tk.Label(
            parent, text=text, bg=colors[0], fg=colors[1],
            font=self.theme.font("body_bold" if primary else "body"),
            padx=self.theme.space["md"], pady=self.theme.space["sm"],
            cursor="hand2",
        )
        button.bind("<Button-1>", lambda _e: command())
        _hover(button, colors[0], self.theme["surface_hi"] if not primary
               else self.theme["accent"])
        return button

    def _bind_keys(self):
        self.master.bind("<Escape>", lambda _e: self._close())
        self.master.bind("<Control-Return>", lambda _e: self._submit())
        self.master.bind("<Control-Tab>", lambda _e: self._toggle_tab())

    # -- rendering ----------------------------------------------------------

    def refresh(self):
        record, target = self.data.record, self.data.target_seconds
        total = dayview.total_seconds(record)

        self.total_label.configure(
            text=f"{format_hm(total)} of {format_hm(target)}",
            fg=self.theme.status_color(complete=total >= target),
        )
        self._draw_progress(total, target)

        if self.data.banner:
            self.banner.configure(text=self.data.banner)
            self.banner.pack(fill="x", padx=self.theme.space["lg"],
                             pady=(self.theme.space["sm"], 0),
                             before=self.tabs)
        else:
            self.banner.pack_forget()

        for name, button in self.tab_buttons.items():
            active = name == self.tab
            button.configure(
                fg=self.theme["text"] if active else self.theme["text_muted"],
                font=self.theme.font("body_bold" if active else "body"),
            )

        missing = dayview.unaccounted_seconds(record, target)
        self.unaccounted_label.configure(
            text=f"{format_hm(missing)} unaccounted" if missing else "",
        )
        self.fill_button.configure(
            fg=self.theme["text"] if missing else self.theme["text_muted"]
        )

        pending = sum(e["seconds"] for e in dayview.entries_to_submit(record))
        self.submit_button.configure(text=f"Submit {format_hm(pending)}"
                                     if pending else "Submit")

        self._render_rows()

    def _draw_progress(self, total, target):
        self.progress.delete("all")
        width = self.progress.winfo_width() or self.theme.metrics["day_window"][0]
        filled = 0 if not target else min(1.0, total / target) * width
        color = (self.theme["accent"] if total >= target
                 else self.theme["text_muted"])
        if filled:
            self.progress.create_rectangle(0, 0, filled, 6, fill=color, width=0)

    def _render_rows(self):
        for child in self.list_frame.winfo_children():
            child.destroy()
        self._fields.clear()

        if self.tab == MY_WORK:
            tracked = dayview.tracked_rows(self.data.record)
            if tracked:
                self._section("Tracked today")
                for row in tracked:
                    self._row(row)

            suggestions = dayview.suggestion_rows(
                self.data.record, self.data.candidates, self.data.internal
            )
            if suggestions:
                self._section("Suggestions")
                for row in suggestions:
                    self._row(row)

            self._add_by_key()
        else:
            for row in dayview.internal_rows(self.data.record, self.data.internal):
                self._row(row)

    def _section(self, title):
        label = tk.Label(
            self.list_frame, text=title.upper(), bg=self.theme["bg"],
            fg=self.theme["text_muted"], font=self.theme.font("small"),
            anchor="w",
        )
        label.pack(fill="x", pady=(self.theme.space["md"], self.theme.space["xs"]))

    def _row(self, row):
        frame = tk.Frame(self.list_frame, bg=self.theme["surface"],
                         height=self.theme.metrics["row_height"])
        frame.pack(fill="x", pady=1)
        frame.pack_propagate(False)

        key = tk.Label(frame, text=row.issue_key, bg=self.theme["surface"],
                       fg=self.theme["text"], font=self.theme.font("issue_key"),
                       width=10, anchor="w")
        key.pack(side="left", padx=(self.theme.space["md"], 0))

        summary = tk.Label(frame, text=row.summary, bg=self.theme["surface"],
                           fg=self.theme["text_muted"],
                           font=self.theme.font("summary"), anchor="w")
        summary.pack(side="left", fill="x", expand=True,
                     padx=(self.theme.space["sm"], 0))

        self._remove_button(frame, row)
        self._row_actions(frame, row)
        self._hours_field(frame, row)
        self._badges(frame, row)

        _hover(frame, self.theme["surface"], self.theme["surface_hi"],
               children=(key, summary))

        message = self.row_status.get(row.issue_key.upper())
        if message:
            note = tk.Label(self.list_frame, text=message, bg=self.theme["bg"],
                            fg=self.theme["danger"], font=self.theme.font("small"),
                            anchor="w", wraplength=600, justify="left")
            note.pack(fill="x", padx=(self.theme.space["md"], 0))

    def _remove_button(self, frame, row):
        """Take a row off the day. Absent on rows already in Tempo — removing
        one would hide time that really is logged, and nothing here can unlog
        it."""
        if not row.on_day or row.submitted:
            return

        remove = tk.Label(frame, text="✕", bg=self.theme["surface"],
                          fg=self.theme["text_muted"],
                          font=self.theme.font("body"), cursor="hand2")
        remove.pack(side="right", padx=(0, self.theme.space["md"]))
        remove.bind("<Button-1>", lambda _e, r=row: self._remove(r))
        remove.bind("<Enter>", lambda _e, w=remove: w.configure(
            fg=self.theme["danger"]))
        remove.bind("<Leave>", lambda _e, w=remove: w.configure(
            fg=self.theme["text_muted"]))

    def _hours_field(self, frame, row):
        if row.submitted:
            tk.Label(frame, text=f"{format_hm(row.seconds)} logged",
                     bg=self.theme["surface"], fg=self.theme["accent"],
                     font=self.theme.font("number")).pack(
                side="right", padx=self.theme.space["sm"])
            return

        entry = tk.Entry(
            frame, width=self.theme.metrics["hours_field_width"],
            bg=self.theme["field_bg"], fg=self.theme["text"],
            insertbackground=self.theme["text"], font=self.theme.font("number"),
            relief="flat", justify="right",
            highlightthickness=1, highlightbackground=self.theme["border"],
            highlightcolor=self.theme["accent"],
        )
        if row.seconds:
            entry.insert(0, format_hm(row.seconds))
        entry.pack(side="right", padx=self.theme.space["sm"], ipady=4)
        entry.bind("<KeyRelease>", lambda _e, r=row, w=entry: self._typed(r, w))
        entry.bind("<Return>", lambda _e: self._submit())
        self._fields[row.issue_key.upper()] = entry

    def _badges(self, frame, row):
        for text, color, tip in (
            ("⏱", self.theme["text_muted"], row.from_timer),
            ("⚠", self.theme["warn"], row.unconfirmed),
        ):
            if tip:
                tk.Label(frame, text=text, bg=self.theme["surface"], fg=color,
                         font=self.theme.font("body")).pack(
                    side="right", padx=(0, self.theme.space["xs"]))

    def _row_actions(self, frame, row):
        if self.tab == INTERNAL and row.on_day:
            # Already on today's list — show that, rather than an add button
            # that would invite putting it there twice.
            tk.Label(frame, text="✓", bg=self.theme["surface"],
                     fg=self.theme["accent"], font=self.theme.font("body")).pack(
                side="right", padx=(0, self.theme.space["sm"]))
            return

        if row.on_day and row.seconds:
            return

        start = tk.Label(frame, text="▶", bg=self.theme["surface"],
                         fg=self.theme["text_muted"],
                         font=self.theme.font("body"), cursor="hand2")
        start.pack(side="right", padx=(0, self.theme.space["sm"]))
        start.bind("<Button-1>", lambda _e, r=row: self._start_timer(r))
        _hover(start, self.theme["surface"], self.theme["surface_hi"])

        if self.tab == INTERNAL and not row.on_day:
            add = tk.Label(frame, text="+", bg=self.theme["surface"],
                           fg=self.theme["text_muted"],
                           font=self.theme.font("body_bold"), cursor="hand2")
            add.pack(side="right", padx=(0, self.theme.space["xs"]))
            add.bind("<Button-1>", lambda _e, r=row: self._add_from_internal(r))
            _hover(add, self.theme["surface"], self.theme["surface_hi"])

    def _add_by_key(self):
        frame = tk.Frame(self.list_frame, bg=self.theme["bg"])
        frame.pack(fill="x", pady=(self.theme.space["md"], 0))

        entry = tk.Entry(
            frame, bg=self.theme["field_bg"], fg=self.theme["text"],
            insertbackground=self.theme["text"], font=self.theme.font("body"),
            relief="flat", highlightthickness=1,
            highlightbackground=self.theme["border"],
            highlightcolor=self.theme["accent"], width=18,
        )
        entry.pack(side="left", ipady=5, padx=(self.theme.space["md"], 0))
        entry.insert(0, "")

        hint = tk.Label(frame, text="add issue by key", bg=self.theme["bg"],
                        fg=self.theme["text_muted"], font=self.theme.font("small"))
        hint.pack(side="left", padx=self.theme.space["sm"])

        self.add_error = tk.Label(frame, text="", bg=self.theme["bg"],
                                  fg=self.theme["danger"],
                                  font=self.theme.font("small"))
        self.add_error.pack(side="left")

        entry.bind("<Return>", lambda _e, w=entry: self._add_typed_key(w))

    # -- events -------------------------------------------------------------

    def show_tab(self, name):
        self.tab = name
        self.refresh()

    def _toggle_tab(self):
        self.show_tab(INTERNAL if self.tab == MY_WORK else MY_WORK)
        return "break"

    def _on_wheel(self, event):
        self.canvas.yview_scroll(-int(event.delta / 120), "units")

    def _typed(self, row, widget):
        text = widget.get().strip()
        issue = {"key": row.issue_key, "id": row.issue_id, "summary": row.summary}

        if not text:
            dayview.set_hours(self.data.record, issue, 0)
            self._mark_field(widget, valid=True)
            self._changed(rerender=False)
            return

        try:
            seconds = parse_hours(text)
        except InvalidDuration:
            self._mark_field(widget, valid=False)
            return

        self._mark_field(widget, valid=True)
        dayview.set_hours(self.data.record, issue, seconds)
        self._changed(rerender=False)

    def _mark_field(self, widget, valid):
        widget.configure(
            highlightbackground=self.theme["border"] if valid
            else self.theme["danger"],
            highlightcolor=self.theme["accent"] if valid else self.theme["danger"],
        )

    def _add_from_internal(self, row):
        issue = {"key": row.issue_key, "id": row.issue_id, "summary": row.summary}
        dayview.set_hours(self.data.record, issue, 0)
        self._changed()
        self.show_tab(MY_WORK)
        field = self._fields.get(row.issue_key.upper())
        if field:
            field.focus_set()

    def _add_typed_key(self, widget):
        key = widget.get().strip().upper()
        if not key:
            return
        issue = self.callbacks.on_lookup(key)
        if not issue:
            self.add_error.configure(text=f"No issue {key}")
            return
        self.add_error.configure(text="")
        dayview.set_hours(self.data.record, issue, 0)
        self._changed()

    def _start_timer(self, row):
        self.callbacks.on_start_timer(
            {"key": row.issue_key, "id": row.issue_id, "summary": row.summary}
        )

    def _remove(self, row):
        dayview.remove_entry(self.data.record, row.issue_key)
        self.row_status.pop(row.issue_key.upper(), None)
        self._changed()

    def _fill_remaining(self):
        dayview.fill_remaining(self.data.record, self.data.target_seconds)
        self._changed()

    def _submit(self):
        results = self.callbacks.on_submit(self.data.record)
        self.row_status = {
            r["issue_key"].upper(): r.get("message", "")
            for r in results if not r.get("ok")
        }
        self._changed()

    def _close(self):
        self.callbacks.on_close()
        self.master.destroy()

    def _changed(self, rerender=True):
        self.callbacks.on_change(self.data.record)
        if rerender:
            self.refresh()
        else:
            self._refresh_totals_only()

    def _refresh_totals_only(self):
        """Update the numbers without rebuilding rows — rebuilding on every
        keystroke would steal focus from the field being typed in."""
        record, target = self.data.record, self.data.target_seconds
        total = dayview.total_seconds(record)
        self.total_label.configure(
            text=f"{format_hm(total)} of {format_hm(target)}",
            fg=self.theme.status_color(complete=total >= target),
        )
        self._draw_progress(total, target)
        missing = dayview.unaccounted_seconds(record, target)
        self.unaccounted_label.configure(
            text=f"{format_hm(missing)} unaccounted" if missing else ""
        )
        pending = sum(e["seconds"] for e in dayview.entries_to_submit(record))
        self.submit_button.configure(
            text=f"Submit {format_hm(pending)}" if pending else "Submit"
        )


def preview(theme_name="dark"):
    """Open the window with invented data and no network.

        py -m timetracker.ui_day
        py -m timetracker.ui_day light

    For looking at it. Nothing here touches Jira, Tempo or your day files.
    """
    root = tk.Tk()
    data = DayData(
        day=date(2026, 8, 17),
        record={
            "date": "2026-08-17", "submitted_at": None, "segments": [],
            "entries": [
                {"issue_key": "AP-7500", "issue_id": 7500,
                 "summary": "CRA252159 - 767 - ANG - ISN/O LOPA change",
                 "seconds": 3 * 3600, "note": "", "source": "timer",
                 "confirmed": True, "submitted": False,
                 "tempo_worklog_id": None},
                {"issue_key": "AP-7429", "issue_id": 7429,
                 "summary": "MI252159-1 - PSU Drawing",
                 "seconds": 9000, "note": "", "source": "timer",
                 "confirmed": False, "submitted": False,
                 "tempo_worklog_id": None},
                {"issue_key": "AI-1", "issue_id": 1,
                 "summary": "INTERNAL - WORK", "seconds": 3600, "note": "",
                 "source": "manual", "confirmed": True, "submitted": True,
                 "tempo_worklog_id": 46580},
            ],
        },
        # Shaped like the real thing: both AP and ADS come back from
        # `assignee = currentUser()`, which has no project filter.
        candidates=[
            {"key": "AP-7492", "id": 7492,
             "summary": "CRA252158 - EEL change A320 MSN6319"},
            {"key": "ADS-150", "id": 150, "summary": "OVHD Bin Divider"},
            {"key": "AP-7455", "id": 7455, "summary": "Wiring diagram update"},
            {"key": "AP-7390", "id": 7390, "summary": "Update EWIS report"},
        ],
        internal=[
            {"key": "AI-1", "id": 1, "summary": "INTERNAL - WORK"},
            {"key": "AI-2", "id": 2, "summary": "INTERNAL - OTHER"},
            {"key": "AI-3", "id": 3, "summary": "INTERNAL - HOLIDAY"},
            {"key": "AI-4", "id": 4, "summary": "INTERNAL - SICK DAYS"},
            {"key": "AI-5", "id": 5, "summary": "INTERNAL - Development"},
            {"key": "AI-6", "id": 6, "summary": "INTERNAL - CHILDREN SICK"},
        ],
        target_seconds=8 * 3600,
    )
    DayWindow(root, data, DayCallbacks(
        on_submit=lambda record: [
            {"issue_key": e["issue_key"], "ok": True} for e in record["entries"]
        ],
    ), Theme(theme_name))
    root.mainloop()


def _installed_families(master):
    """Font families Tk can actually see, or an empty set if it cannot say.

    An empty set makes resolve_mono fall back to Consolas, which is the safe
    direction: worst case the numbers are monospaced in a slightly duller face.
    """
    try:
        return set(tkfont.families(master))
    except tk.TclError:  # pragma: no cover - only on a broken display
        return set()


def _hover(widget, normal, highlight, children=()):
    """Light up a row or button under the cursor."""
    def enter(_event):
        widget.configure(bg=highlight)
        for child in children:
            child.configure(bg=highlight)

    def leave(_event):
        widget.configure(bg=normal)
        for child in children:
            child.configure(bg=normal)

    widget.bind("<Enter>", enter)
    widget.bind("<Leave>", leave)
    for child in children:
        child.bind("<Enter>", enter)
        child.bind("<Leave>", leave)
