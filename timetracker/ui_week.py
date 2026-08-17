"""The week overview.

Mon–Fri with what each day holds, and any day openable in place to fix it.
Its whole reason for existing is that a short Wednesday is invisible until
Friday and unfixable by Monday, so looking is not enough — every day here can
be edited and submitted without leaving the window.

Hours already in Tempo are shown as text and never in a box. Back-dated entry
is where logging the same hours twice is easiest to do and hardest to notice,
so the interface makes it structurally impossible rather than merely unwise.
"""

import tkinter as tk
from dataclasses import dataclass

from timetracker import dayview
from timetracker.duration import InvalidDuration, format_hm, parse_hours
from timetracker.theme import Theme

BAR_SEGMENTS = 20


@dataclass
class WeekCallbacks:
    on_change: callable = lambda record: None
    on_submit: callable = lambda record, day: []
    on_lookup: callable = lambda key: None
    on_close: callable = lambda: None


class WeekWindow:
    def __init__(self, master, data, callbacks=None, theme=None):
        self.master = master
        self.data = data
        self.callbacks = callbacks or WeekCallbacks()
        self.theme = theme or Theme()
        self.open_day = None
        self.row_status = {}
        self._fields = {}

        first, last = data.days[0].date, data.days[-1].date
        master.title(f"TimeTracker — week of {first:%d %B}"
                     if first.month == last.month
                     else f"TimeTracker — {first:%d %b} to {last:%d %b}")
        master.configure(bg=self.theme["bg"])
        width, height = self.theme.metrics["week_window"]
        master.geometry(f"{width}x{height}")
        master.minsize(560, 420)

        self._build()
        master.bind("<Escape>", lambda _e: self._close())
        self.refresh()

    # -- construction -------------------------------------------------------

    def _build(self):
        pad = self.theme.space["lg"]

        header = tk.Frame(self.master, bg=self.theme["bg"])
        header.pack(fill="x", padx=pad, pady=(pad, 0))

        tk.Label(header, text="This week", bg=self.theme["bg"],
                 fg=self.theme["text"], font=self.theme.font("heading"),
                 anchor="w").pack(side="left")

        self.total_label = tk.Label(
            header, bg=self.theme["bg"], fg=self.theme["text"],
            font=self.theme.font("number_large"), anchor="e",
        )
        self.total_label.pack(side="right")

        self.banner = tk.Label(
            self.master, bg=self.theme["bg"], fg=self.theme["warn"],
            font=self.theme.font("small"), anchor="w", justify="left",
            wraplength=self.theme.metrics["week_window"][0] - 2 * pad,
        )

        self.body = tk.Frame(self.master, bg=self.theme["bg"])
        self.body.pack(fill="both", expand=True, padx=pad,
                       pady=(self.theme.space["md"], 0))

        footer = tk.Frame(self.master, bg=self.theme["bg"])
        footer.pack(fill="x", padx=pad, pady=pad)

        self.missing_label = tk.Label(
            footer, bg=self.theme["bg"], fg=self.theme["text_muted"],
            font=self.theme.font("small"), anchor="w",
        )
        self.missing_label.pack(side="left")

        close = tk.Label(footer, text="Close", bg=self.theme["surface"],
                         fg=self.theme["text"], font=self.theme.font("body"),
                         padx=self.theme.space["md"],
                         pady=self.theme.space["sm"], cursor="hand2")
        close.bind("<Button-1>", lambda _e: self._close())
        close.pack(side="right")

    # -- rendering ----------------------------------------------------------

    def refresh(self):
        total = self.data.total_seconds
        target = self.data.week_target_seconds

        self.total_label.configure(
            text=f"{format_hm(total)} of {format_hm(target)}",
            fg=self.theme.status_color(complete=total >= target),
        )

        if self.data.banner:
            self.banner.configure(text=self.data.banner)
            self.banner.pack(fill="x", padx=self.theme.space["lg"],
                             pady=(self.theme.space["sm"], 0), before=self.body)
        else:
            self.banner.pack_forget()

        missing = sum(day.missing_seconds for day in self.data.days)
        self.missing_label.configure(
            text=f"{format_hm(missing)} missing this week" if missing
            else "The week is complete.",
            fg=self.theme["danger"] if missing else self.theme["accent"],
        )

        for child in self.body.winfo_children():
            child.destroy()
        self._fields.clear()

        for day in self.data.days:
            self._day_row(day)
            if self.open_day == day.date:
                self._day_detail(day)

    def _day_row(self, day):
        is_open = self.open_day == day.date
        background = self.theme["surface_hi"] if is_open else self.theme["surface"]

        frame = tk.Frame(self.body, bg=background, height=44)
        frame.pack(fill="x", pady=1)
        frame.pack_propagate(False)

        arrow = tk.Label(frame, text="▾" if is_open else "▸", bg=background,
                         fg=self.theme["text_muted"],
                         font=self.theme.font("small"))
        arrow.pack(side="left", padx=(self.theme.space["sm"], 0))

        name = tk.Label(frame, text=f"{day.date:%a %d}", bg=background,
                        fg=self.theme["text"], font=self.theme.font("body_bold"),
                        width=8, anchor="w")
        name.pack(side="left", padx=(self.theme.space["sm"], 0))

        bar = tk.Label(frame, text=self._bar(day), bg=background,
                       fg=self._day_color(day), font=self.theme.font("number"))
        bar.pack(side="left", padx=self.theme.space["md"])

        hours = tk.Label(frame, text=format_hm(day.total_seconds),
                         bg=background, fg=self._day_color(day),
                         font=self.theme.font("number"), width=6, anchor="e")
        hours.pack(side="left")

        if day.missing_seconds:
            tk.Label(frame, text=f"{format_hm(day.missing_seconds)} missing",
                     bg=background, fg=self.theme["danger"],
                     font=self.theme.font("small")).pack(
                side="left", padx=self.theme.space["md"])

        for widget in (frame, arrow, name, bar, hours):
            widget.bind("<Button-1>", lambda _e, d=day.date: self._toggle(d))
            widget.configure(cursor="hand2")

    def _bar(self, day):
        if not day.target_seconds:
            return ""
        filled = min(BAR_SEGMENTS,
                     round(BAR_SEGMENTS * day.total_seconds / day.target_seconds))
        return "█" * filled + "░" * (BAR_SEGMENTS - filled)

    def _day_color(self, day):
        return self.theme.status_color(
            missing=bool(day.missing_seconds), complete=day.is_complete
        )

    # -- one day, opened ----------------------------------------------------

    def _day_detail(self, day):
        record = self.data.records[day.date]
        panel = tk.Frame(self.body, bg=self.theme["bg"])
        panel.pack(fill="x", pady=(0, self.theme.space["sm"]))

        rows = dayview.tracked_rows(record)
        if not rows:
            tk.Label(panel, text="Nothing logged. Add an issue below.",
                     bg=self.theme["bg"], fg=self.theme["text_muted"],
                     font=self.theme.font("small"), anchor="w").pack(
                fill="x", padx=self.theme.space["xl"],
                pady=self.theme.space["xs"])

        for row in rows:
            self._entry_row(panel, day, row)

        self._add_by_key(panel, day)

        pending = sum(e["seconds"] for e in dayview.entries_to_submit(record))
        submit = tk.Label(
            panel,
            text=f"Add {format_hm(pending)} to {day.date:%A}" if pending
            else "Nothing to add",
            bg=self.theme["accent"] if pending else self.theme["surface"],
            fg=self.theme["accent_text"] if pending else self.theme["text_muted"],
            font=self.theme.font("body_bold" if pending else "body"),
            padx=self.theme.space["md"], pady=self.theme.space["sm"],
            cursor="hand2" if pending else "",
        )
        submit.pack(anchor="e", padx=self.theme.space["xl"],
                    pady=self.theme.space["sm"])
        if pending:
            submit.bind("<Button-1>", lambda _e, d=day: self._submit(d))

    def _entry_row(self, panel, day, row):
        frame = tk.Frame(panel, bg=self.theme["bg"])
        frame.pack(fill="x", padx=self.theme.space["xl"], pady=1)

        tk.Label(frame, text=row.issue_key, bg=self.theme["bg"],
                 fg=self.theme["text"], font=self.theme.font("issue_key"),
                 width=10, anchor="w").pack(side="left")

        tk.Label(frame, text=row.summary, bg=self.theme["bg"],
                 fg=self.theme["text_muted"], font=self.theme.font("summary"),
                 anchor="w").pack(side="left", fill="x", expand=True,
                                  padx=self.theme.space["sm"])

        entry = tk.Entry(
            frame, width=self.theme.metrics["hours_field_width"],
            bg=self.theme["field_bg"], fg=self.theme["text"],
            insertbackground=self.theme["text"],
            font=self.theme.font("number"), relief="flat", justify="right",
            highlightthickness=1, highlightbackground=self.theme["border"],
            highlightcolor=self.theme["accent"],
        )
        if row.seconds:
            entry.insert(0, format_hm(row.seconds))
        entry.pack(side="right", ipady=3)
        entry.bind("<KeyRelease>",
                   lambda _e, d=day, r=row, w=entry: self._typed(d, r, w))
        self._fields[(day.date, row.issue_key.upper())] = entry

        if row.logged_seconds:
            # Already in Tempo: shown, never editable. This is where logging
            # the same hours twice is easiest and least likely to be noticed.
            tk.Label(frame, text=f"{format_hm(row.logged_seconds)} logged",
                     bg=self.theme["bg"], fg=self.theme["accent"],
                     font=self.theme.font("number")).pack(
                side="right", padx=self.theme.space["sm"])

        message = self.row_status.get((day.date, row.issue_key.upper()))
        if message:
            tk.Label(panel, text=message, bg=self.theme["bg"],
                     fg=self.theme["danger"], font=self.theme.font("small"),
                     anchor="w", wraplength=600, justify="left").pack(
                fill="x", padx=self.theme.space["xl"])

    def _add_by_key(self, panel, day):
        frame = tk.Frame(panel, bg=self.theme["bg"])
        frame.pack(fill="x", padx=self.theme.space["xl"],
                   pady=(self.theme.space["sm"], 0))

        entry = tk.Entry(
            frame, width=16, bg=self.theme["field_bg"], fg=self.theme["text"],
            insertbackground=self.theme["text"], font=self.theme.font("body"),
            relief="flat", highlightthickness=1,
            highlightbackground=self.theme["border"],
            highlightcolor=self.theme["accent"],
        )
        entry.pack(side="left", ipady=3)

        tk.Label(frame, text="add issue by key", bg=self.theme["bg"],
                 fg=self.theme["text_muted"],
                 font=self.theme.font("small")).pack(
            side="left", padx=self.theme.space["sm"])

        self.add_error = tk.Label(frame, text="", bg=self.theme["bg"],
                                  fg=self.theme["danger"],
                                  font=self.theme.font("small"))
        self.add_error.pack(side="left")
        entry.bind("<Return>",
                   lambda _e, d=day, w=entry: self._add_typed_key(d, w))

    # -- events -------------------------------------------------------------

    def _toggle(self, day_date):
        self.open_day = None if self.open_day == day_date else day_date
        self.refresh()

    def _typed(self, day, row, widget):
        record = self.data.records[day.date]
        issue = {"key": row.issue_key, "id": row.issue_id,
                 "summary": row.summary}
        text = widget.get().strip()

        if not text:
            dayview.set_hours(record, issue, 0)
            self._mark(widget, valid=True)
            self.callbacks.on_change(record)
            return

        try:
            seconds = parse_hours(text)
        except InvalidDuration:
            self._mark(widget, valid=False)
            return

        self._mark(widget, valid=True)
        dayview.set_hours(record, issue, seconds)
        self.callbacks.on_change(record)

    def _mark(self, widget, valid):
        widget.configure(
            highlightbackground=self.theme["border"] if valid
            else self.theme["danger"],
            highlightcolor=self.theme["accent"] if valid
            else self.theme["danger"],
        )

    def _add_typed_key(self, day, widget):
        key = widget.get().strip().upper()
        if not key:
            return

        issue = self.callbacks.on_lookup(key)
        if not issue:
            self.add_error.configure(text=f"No issue {key}")
            return

        dayview.set_hours(self.data.records[day.date], issue, 0)
        self.callbacks.on_change(self.data.records[day.date])
        self.refresh()

    def _submit(self, day):
        record = self.data.records[day.date]
        results = self.callbacks.on_submit(record, day.date)

        self.row_status = {
            (day.date, r["issue_key"].upper()): r.get("message", "")
            for r in results if not r.get("ok")
        }
        self.refresh()

    def _close(self):
        self.callbacks.on_close()
        self.master.destroy()
