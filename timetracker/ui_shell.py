"""One window, several pages.

TimeTracker is one program with one window. The day and the week are pages
inside it rather than separate windows, so there is never a pile of them to
sort through and going between them is navigation instead of window
management.

The timer strip is the deliberate exception: it is borderless, always on top
and parked over the clock, which a page inside a normal window cannot be.

The shell owns the window — its title, its size, and which page is showing.
The pages know only how to fill the frame they are handed.
"""

import tkinter as tk
from datetime import date

from timetracker import icon
from timetracker.theme import Theme

DAY = "day"
WEEK = "week"


class Shell:
    def __init__(self, window, build_day, build_week, theme=None,
                 on_quit=None):
        self.window = window
        self.build_day = build_day
        self.build_week = build_week
        self.theme = theme or Theme()
        self.on_quit = on_quit or (lambda: None)

        self.page = None
        self.view = None
        self.showing = None

        self.window.configure(bg=self.theme["bg"])
        icon.apply(self.window)
        width, height = self.theme.metrics["day_window"]
        self.window.geometry(f"{width}x{height}")
        self.window.minsize(560, 420)

        self.container = tk.Frame(self.window, bg=self.theme["bg"])
        self.container.pack(fill="both", expand=True)

        self.window.protocol("WM_DELETE_WINDOW", self.on_quit)

    # -- navigation ---------------------------------------------------------

    def show_day(self, day=None):
        day = day or date.today()
        self.showing = DAY
        self.window.title(f"TimeTracker — {day:%A %d %B}")
        self.view = self._swap(lambda frame: self.build_day(frame, day))
        return self.view

    def show_week(self):
        self.showing = WEEK
        self.window.title("TimeTracker — this week")
        self.view = self._swap(self.build_week)
        return self.view

    def _swap(self, build):
        """Replace the page. Old key bindings go with the old toplevel-level
        handlers being rebound by whatever is built next."""
        for child in self.container.winfo_children():
            child.destroy()

        for sequence in ("<Escape>", "<Control-Return>", "<Control-Tab>"):
            self.window.unbind(sequence)

        page = tk.Frame(self.container, bg=self.theme["bg"])
        page.pack(fill="both", expand=True)
        self.page = page
        return build(page)

    # -- window -------------------------------------------------------------

    def present(self):
        self.window.deiconify()
        self.window.lift()
        self.window.focus_force()

    def hide(self):
        self.window.withdraw()

    def is_visible(self):
        return self.window.winfo_exists() and self.window.state() != "withdrawn"
