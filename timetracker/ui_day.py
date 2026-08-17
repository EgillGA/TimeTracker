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
from datetime import date, datetime

from timetracker import timer

from timetracker import dayview
from timetracker.dayview import DayData
from timetracker.duration import (
    InvalidDuration,
    format_hhmmss,
    format_hm,
    parse_hours,
)
from timetracker.theme import Theme


@dataclass
class DayCallbacks:
    on_change: callable = lambda record: None
    on_submit: callable = lambda record: []
    on_start_timer: callable = lambda issue: None
    on_lookup: callable = lambda key: None
    on_close: callable = lambda: None
    on_show_week: callable = lambda: None
    # Asked every second for the timer's current state, so pausing or stopping
    # from the strip is reflected here instead of the window counting on
    # against a timer that is no longer running.
    on_running: callable = None


MY_WORK, INTERNAL = "My work", "Internal"

# How many rows a section shows before collapsing the rest. Five each, so
# Projects and Suggestions together fit the window without scrolling. Tracked
# rows do not push this over: an issue moves out of Projects as soon as it is
# tracked, so the total stays roughly constant through the day.
COLLAPSED_ROWS = 5


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
        self.expanded = {}
        self.suggestion_count = getattr(data, "suggestion_count", 5)
        self._fields = {}
        self._running_label = None
        self._shown_running = None

        master.configure(bg=self.theme["bg"])

        self._build()
        self._bind_keys()
        self.refresh()
        self._tick_running()

    # -- construction -------------------------------------------------------

    def _build(self):
        pad = self.theme.space["lg"]

        self.header = tk.Frame(self.master, bg=self.theme["bg"])
        self.header.pack(fill="x", padx=pad, pady=(pad, 0))

        self.title_label = tk.Label(
            self.header, text=self._day_name(), bg=self.theme["bg"],
            fg=self.theme["text"], font=self.theme.font("heading"), anchor="w",
        )
        self.title_label.pack(side="left")

        # The way out to the whole week. A short Wednesday is invisible from
        # here, so there has to be a door to where it can be seen and fixed.
        self.week_button = tk.Label(
            self.header, text="▦  Week", bg=self.theme["surface"],
            fg=self.theme["text"], font=self.theme.font("small"),
            padx=self.theme.space["sm"], pady=self.theme.space["xs"],
            cursor="hand2",
        )
        self.week_button.pack(side="left", padx=(self.theme.space["md"], 0))
        self.week_button.bind("<Button-1>",
                              lambda _e: self.callbacks.on_show_week())
        _hover(self.week_button, self.theme["surface"],
               self.theme["surface_hi"])

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
        # Equal padding above and below, so the buttons sit in the middle of
        # their own space rather than crowding the list above them.
        self.footer.pack(fill="x", padx=pad, pady=pad)

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

    def _day_name(self):
        """"Today" when it is, the date when it is not.

        The same page serves any day, so it has to say which one — a window
        that silently shows last Wednesday looks exactly like one showing now.
        """
        return ("Today" if self.data.day == date.today()
                else f"{self.data.day:%A %d %B}")

    def _bind_keys(self):
        # Bound on the toplevel: this view may be a frame inside one, and a
        # frame never receives keystrokes.
        window = self.master.winfo_toplevel()
        window.bind("<Escape>", lambda _e: self._close())
        window.bind("<Control-Return>", lambda _e: self._submit())
        window.bind("<Control-Tab>", lambda _e: self._toggle_tab())

    # -- rendering ----------------------------------------------------------

    def refresh(self):
        record, target = self.data.record, self.data.target_seconds
        # Running time is included so the header cannot contradict the strip,
        # but it stays out of the Submit figure: it is not in the record yet
        # and cannot be sent until the timer stops.
        total = dayview.total_seconds(record) + self._running_seconds()

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
            tracked = dayview.tracked_rows(self.data.record,
                                           running=self.running_row())
            if tracked:
                self._section("Tracked today")
                for row in tracked:
                    self._row(row)

            running = self.running_row()
            self._collapsible(
                "Projects",
                dayview.project_rows(self.data.record, self.data.assigned,
                                     self.data.internal, running),
            )
            # Suggestions stay shut unless asked for. They are a fallback for
            # work that is not assigned to you, and an open list of them
            # buries the Projects you actually came here for. Their data is
            # only fetched when the section is opened.
            self._collapsible(
                "Suggestions",
                dayview.suggestion_rows(
                    self.data.record, self._suggestions(), self.data.assigned,
                    self.data.internal, running,
                )[:self.suggestion_count],
                closed_by_default=True,
            )
            self._add_by_key()
        else:
            for row in dayview.internal_rows(self.data.record, self.data.internal):
                self._row(row)

    def _suggestions(self):
        """The Suggestions list, fetched the first time the section opens.

        Closed, it costs nothing. Open, it is normally already in flight from
        the prefetch, so the wait is imperceptible.
        """
        if not self.expanded.get("Suggestions", False):
            return self.data.recent

        if not self.data.recent and self.data.recent_provider is not None:
            self.data.recent = self.data.recent_provider() or []
        return self.data.recent

    def _collapsible(self, title, rows, closed_by_default=False):
        """A section that can hide its rows behind its own heading.

        Without a scrollbar there is nothing to hint that a list continues
        below the window, so a section that is holding rows back says so.
        """
        # A dropdown section still shows its heading when empty: it may simply
        # not have been fetched yet, and hiding it would remove the only way
        # to ask for it.
        if not rows and not closed_by_default:
            return

        # Untouched sections are closed. What "closed" means differs: an
        # always-shown section still offers its first few rows, while a
        # dropdown section shows none until asked.
        expanded = self.expanded.get(title, False)

        if closed_by_default:
            # No count until the list has actually been fetched — a confident
            # "(0)" on a section nobody has opened would simply be wrong.
            self._section(title, arrow="▾" if expanded else "▸",
                          count=len(rows) if expanded else None)
            for row in (rows if expanded else []):
                self._row(row)
            return

        self._section(title)
        visible = rows if expanded else rows[:COLLAPSED_ROWS]
        for row in visible:
            self._row(row)

        hidden = len(rows) - len(visible)
        if hidden <= 0 and not expanded:
            return

        label = f"+ {hidden} more" if hidden > 0 else "show fewer"
        toggle = tk.Label(self.list_frame, text=label, bg=self.theme["bg"],
                          fg=self.theme["text_muted"],
                          font=self.theme.font("small"), anchor="w",
                          cursor="hand2", pady=self.theme.space["sm"])
        toggle.pack(fill="x", padx=(self.theme.space["md"], 0))
        toggle.bind("<Button-1>", lambda _e, t=title: self._toggle_section(t))
        toggle.bind("<Enter>", lambda _e, w=toggle: w.configure(
            fg=self.theme["text"]))
        toggle.bind("<Leave>", lambda _e, w=toggle: w.configure(
            fg=self.theme["text_muted"]))

    def _toggle_section(self, title):
        self.expanded[title] = not self.expanded.get(title, False)
        self.refresh()

    def _section(self, title, arrow=None, count=None):
        text = title.upper()
        if arrow:
            text = f"{arrow}  {text}" + (f"  ({count})" if count else "")

        label = tk.Label(
            self.list_frame, text=text, bg=self.theme["bg"],
            fg=self.theme["text_muted"], font=self.theme.font("small"),
            anchor="w", cursor="hand2" if arrow else "",
        )
        label.pack(fill="x", pady=(self.theme.space["md"], self.theme.space["xs"]))

        if arrow:
            label.bind("<Button-1>",
                       lambda _e, t=title: self._toggle_section(t))
            label.bind("<Enter>", lambda _e, w=label: w.configure(
                fg=self.theme["text"]))
            label.bind("<Leave>", lambda _e, w=label: w.configure(
                fg=self.theme["text_muted"]))

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
        # Nothing to remove on a row that is only what Tempo already holds.
        if not row.on_day or not row.has_pending:
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
        # Only rows on today take hours. An issue is added first and valued
        # second, so the day is always built from a list you can see.
        if not row.on_day:
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

        if row.logged_seconds:
            # What Tempo already holds, shown but not editable — while the box
            # beside it still takes more hours for the same issue.
            tk.Label(frame, text=f"{format_hm(row.logged_seconds)} logged",
                     bg=self.theme["surface"], fg=self.theme["accent"],
                     font=self.theme.font("number")).pack(
                side="right", padx=(0, self.theme.space["sm"]))

    def _badges(self, frame, row):
        if row.is_running:
            # The live figure, in the same monospaced face as the strip so the
            # two read as the same number rather than two opinions.
            label = tk.Label(
                frame, text=f"● {format_hhmmss(row.running_seconds)}",
                bg=self.theme["surface"], fg=self.theme["accent"],
                font=self.theme.font("timer"),
            )
            label.pack(side="right", padx=(0, self.theme.space["sm"]))
            self._running_label = label

        for text, color, tip in (
            ("⏱", self.theme["text_muted"], row.from_timer),
            ("⚠", self.theme["warn"], row.unconfirmed),
        ):
            if tip:
                tk.Label(frame, text=text, bg=self.theme["surface"], fg=color,
                         font=self.theme.font("body")).pack(
                    side="right", padx=(0, self.theme.space["xs"]))

    def _row_actions(self, frame, row):
        if row.on_day:
            if self.tab == INTERNAL:
                # Already on today's list — say so, rather than offer an add
                # button that would invite putting it there twice.
                tk.Label(frame, text="✓", bg=self.theme["surface"],
                         fg=self.theme["accent"],
                         font=self.theme.font("body")).pack(
                    side="right", padx=(0, self.theme.space["sm"]))
            return

        add = tk.Label(frame, text="+", bg=self.theme["surface"],
                       fg=self.theme["text_muted"],
                       font=self.theme.font("body_bold"), cursor="hand2")
        add.pack(side="right", padx=(0, self.theme.space["md"]))
        add.bind("<Button-1>", lambda _e, r=row: self._add_to_today(r))
        add.bind("<Enter>", lambda _e, w=add: w.configure(
            fg=self.theme["accent"]))
        add.bind("<Leave>", lambda _e, w=add: w.configure(
            fg=self.theme["text_muted"]))

        start = tk.Label(frame, text="▶", bg=self.theme["surface"],
                         fg=self.theme["text_muted"],
                         font=self.theme.font("body"), cursor="hand2")
        start.pack(side="right", padx=(0, self.theme.space["sm"]))
        start.bind("<Button-1>", lambda _e, r=row: self._start_timer(r))
        _hover(start, self.theme["surface"], self.theme["surface_hi"])

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

    def _running_state(self):
        """The timer's state now, re-asked rather than remembered."""
        if self.callbacks.on_running is not None:
            return self.callbacks.on_running()
        return self.data.running

    def running_row(self):
        """The live timer as `{issue_key, issue_id, summary, seconds}`, or None.

        Elapsed is computed from the timer's own start time rather than the
        last figure it wrote to disk, so the number here matches the strip
        even though the strip only persists every half minute.
        """
        state = self._running_state()
        if not state:
            return None

        return {
            "issue_key": state["issue_key"],
            "issue_id": state.get("issue_id", 0),
            "summary": state.get("summary", ""),
            "seconds": timer.elapsed_seconds(state, datetime.now()),
        }

    def _running_seconds(self):
        row = self.running_row()
        return row["seconds"] if row else 0

    def _tick_running(self):
        """Keep the live figure moving without rebuilding the list."""
        row = self.running_row()

        if (row is None) != (self._shown_running is None):
            # Started or stopped since the last beat — the row itself has to
            # appear or disappear, which needs a rebuild.
            self._shown_running = row
            self.refresh()
        elif row is not None:
            self._shown_running = row
            if self._running_label is not None:
                try:
                    self._running_label.configure(
                        text=f"● {format_hhmmss(row['seconds'])}"
                    )
                except tk.TclError:
                    self._running_label = None
            self._refresh_totals_only()

        try:
            self.master.after(1000, self._tick_running)
        except tk.TclError:
            pass

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

    def _add_to_today(self, row):
        """Move an issue up into Tracked today, ready for its hours.

        Adding and valuing are separate steps: you assemble the day's list
        first, then say how long each took, rather than hunting for boxes
        scattered down a list of everything you might have worked on.
        """
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
        # The view does not destroy anything; whoever is hosting it decides
        # whether closing means going back, hiding, or leaving.
        self.callbacks.on_close()

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
        # Running time is included so the header cannot contradict the strip,
        # but it stays out of the Submit figure: it is not in the record yet
        # and cannot be sent until the timer stops.
        total = dayview.total_seconds(record) + self._running_seconds()
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
        assigned=[
            {"key": "AP-7492", "id": 7492,
             "summary": "CRA252158 - EEL change A320 MSN6319"},
            {"key": "ADS-150", "id": 150, "summary": "OVHD Bin Divider"},
            {"key": "AP-7455", "id": 7455, "summary": "Wiring diagram update"},
            {"key": "AP-7390", "id": 7390, "summary": "Update EWIS report"},
            {"key": "AP-7325", "id": 7325, "summary": "Modpack Summary Pumba V2"},
            {"key": "AP-7076", "id": 7076,
             "summary": "Noise certificate STC development"},
            {"key": "AP-7164", "id": 7164, "summary": "TF-FMS Tail Livery Logo"},
            {"key": "AP-6047", "id": 6047,
             "summary": "Icelandair B737 update of ICA documents"},
        ],
        recent=[
            {"key": "AP-6852", "id": 6852,
             "summary": "LHG - Umlaut installation in TF-FMS"},
            {"key": "AP-7239", "id": 7239, "summary": "AHK A330P2F ELT STC"},
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
