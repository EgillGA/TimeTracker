"""The week overview.

Monday to Friday with what each day holds against its target, and the
shortfall totalled at the bottom. Its whole reason for existing is that a
short Wednesday is invisible on Wednesday and unfixable by the next Monday.

Clicking a day opens that day in the ordinary day page rather than unfolding a
second, smaller editor here. One editor, used for every day, means back-dated
entry behaves exactly like today's — including everything that stops the same
hours being logged twice.
"""

import tkinter as tk
from dataclasses import dataclass
from datetime import date

from timetracker.duration import format_hm
from timetracker.theme import Theme

BAR_SEGMENTS = 20


@dataclass
class WeekCallbacks:
    on_open_day: callable = lambda day: None
    on_close: callable = lambda: None


class WeekWindow:
    def __init__(self, master, data, callbacks=None, theme=None):
        self.master = master
        self.data = data
        self.callbacks = callbacks or WeekCallbacks()
        self.theme = theme or Theme()

        master.configure(bg=self.theme["bg"])
        self._build()
        self.master.winfo_toplevel().bind("<Escape>", lambda _e: self._close())
        self.refresh()

    # -- construction -------------------------------------------------------

    def _build(self):
        pad = self.theme.space["lg"]

        header = tk.Frame(self.master, bg=self.theme["bg"])
        header.pack(fill="x", padx=pad, pady=(pad, 0))

        first, last = self.data.days[0].date, self.data.days[-1].date
        title = (f"Week of {first:%d %B}" if first.month == last.month
                 else f"{first:%d %b} – {last:%d %b}")
        tk.Label(header, text=title, bg=self.theme["bg"],
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

        hint = tk.Label(self.master, text="Click a day to fill it in",
                        bg=self.theme["bg"], fg=self.theme["text_muted"],
                        font=self.theme.font("small"), anchor="w")
        hint.pack(fill="x", padx=pad, pady=(self.theme.space["sm"], 0))

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
        for day in self.data.days:
            self._day_row(day)

    def _day_row(self, day):
        background = self.theme["surface"]
        frame = tk.Frame(self.body, bg=background, height=44)
        frame.pack(fill="x", pady=1)
        frame.pack_propagate(False)

        today = day.date == date.today()
        name = tk.Label(
            frame, text=f"{day.date:%a %d}", bg=background,
            fg=self.theme["text"],
            font=self.theme.font("body_bold" if today else "body"),
            width=8, anchor="w",
        )
        name.pack(side="left", padx=(self.theme.space["md"], 0))

        bar = tk.Label(frame, text=self._bar(day), bg=background,
                       fg=self._day_color(day), font=self.theme.font("number"))
        bar.pack(side="left", padx=self.theme.space["md"])

        hours = tk.Label(frame, text=format_hm(day.total_seconds),
                         bg=background, fg=self._day_color(day),
                         font=self.theme.font("number"), width=6, anchor="e")
        hours.pack(side="left")

        arrow = tk.Label(frame, text="›", bg=background,
                         fg=self.theme["text_muted"],
                         font=self.theme.font("body"))
        arrow.pack(side="right", padx=(0, self.theme.space["md"]))

        widgets = [frame, name, bar, hours, arrow]

        if day.missing_seconds:
            missing = tk.Label(
                frame, text=f"{format_hm(day.missing_seconds)} missing",
                bg=background, fg=self.theme["danger"],
                font=self.theme.font("small"),
            )
            missing.pack(side="left", padx=self.theme.space["md"])
            widgets.append(missing)

        for widget in widgets:
            widget.configure(cursor="hand2")
            widget.bind("<Button-1>",
                        lambda _e, d=day.date: self.callbacks.on_open_day(d))

        _hover(frame, background, self.theme["surface_hi"],
               children=tuple(widgets[1:]))

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

    def _close(self):
        self.callbacks.on_close()


def _hover(widget, normal, highlight, children=()):
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
