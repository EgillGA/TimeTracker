"""The always-on-top timer strip.

A borderless bar parked in the bottom-right corner of the work area, above the
clock. It is the most-seen part of the whole application, so two things matter
more than anything else here: that running and paused are unmistakable from
across a desk, and that it never steals focus from whatever is being typed in.

The hourly check-in expands the strip in place rather than opening a dialog.
It asks; it never overrules. A timer left running is flagged, not stopped —
being told your timer ran unattended is recoverable, having it silently
stopped at the wrong moment is not.
"""

import ctypes
import tkinter as tk
from dataclasses import dataclass
from datetime import datetime

from timetracker import icon, notify, timer
from timetracker.duration import format_hhmmss
from timetracker.theme import Theme

TICK_MILLISECONDS = 1000

# Characters of the issue title the strip has room for. Real summaries run to
# sixty or more, and tkinter labels do not ellipsize on their own.
SUMMARY_LIMIT = 26


def shorten(text, limit=SUMMARY_LIMIT):
    """Trim an issue title to fit the strip, ending in an ellipsis."""
    collapsed = " ".join(str(text or "").split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[:limit - 1].rstrip() + "…"


@dataclass
class StripCallbacks:
    on_persist: callable = lambda state: None
    on_stop: callable = lambda segment: None
    on_open_day: callable = lambda: None


def work_area():
    """The screen minus the taskbar, as (left, top, right, bottom).

    Asking Windows rather than guessing a taskbar height keeps the strip
    correct at any taskbar position, size or DPI scaling.
    """
    class Rect(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    rect = Rect()
    try:
        ok = ctypes.windll.user32.SystemParametersInfoW(
            0x0030, 0, ctypes.byref(rect), 0  # SPI_GETWORKAREA
        )
        if ok:
            return (rect.left, rect.top, rect.right, rect.bottom)
    except (AttributeError, OSError):
        pass
    return None


def strip_position(area, width, height, margin):
    """Bottom-right of the work area, pulled back on screen if it will not fit."""
    left, top, right, bottom = area
    x = right - width - margin
    y = bottom - height - margin
    return (max(left, x), max(top, y))


class TimerStrip:
    def __init__(self, master, issue, config, callbacks=None, theme=None,
                 now=None):
        self.master = master
        self.config = config
        self.callbacks = callbacks or StripCallbacks()
        self.theme = theme or Theme(getattr(config, "theme", "dark"))
        self.state = timer.start(issue, now or datetime.now())
        self.checkin_visible = False
        self._last_persist = now or datetime.now()
        self._expanded = False
        self._drag_origin = None

        self.window = tk.Toplevel(master)
        self._configure_window()
        self._build()
        self._place()

        # Write it down straight away. Until the state is on disk nothing else
        # can see the timer: the day window finds no running row, and a crash
        # in the first half-minute loses the run completely.
        self.callbacks.on_persist(self.state)

        self.tick(now or datetime.now())
        self._schedule_tick()

    # -- window -------------------------------------------------------------

    def _configure_window(self):
        self.window.overrideredirect(True)      # no title bar
        self.window.attributes("-topmost", True)
        self.window.configure(bg=self.theme["border"])

    def _place(self, size="strip_resting"):
        width, height = self.theme.metrics[size]
        margin = self.theme.metrics["strip_margin"]

        area = work_area() or (
            0, 0,
            self.window.winfo_screenwidth(), self.window.winfo_screenheight(),
        )
        x, y = strip_position(area, width, height, margin)
        self.window.geometry(f"{width}x{height}+{x}+{y}")

    def _build(self):
        # A one-pixel border, since a borderless window with no outline
        # dissolves into a dark desktop.
        self.body = tk.Frame(self.window, bg=self.theme["surface"])
        self.body.pack(fill="both", expand=True, padx=1, pady=1)

        self.dot = tk.Label(self.body, text="●", bg=self.theme["surface"],
                            fg=self.theme["accent"],
                            font=self.theme.font("body"))
        self.dot.pack(side="left", padx=(self.theme.space["sm"], 0))

        self.key_label = tk.Label(self.body, text=self.state["issue_key"],
                                  bg=self.theme["surface"],
                                  fg=self.theme["text"],
                                  font=self.theme.font("issue_key"))
        self.key_label.pack(side="left", padx=(self.theme.space["sm"], 0))

        # The clock is packed before the title on purpose. Tk allocates space
        # in packing order, so whatever comes last is what gets squeezed when
        # the strip is too narrow — and that has to be the title, never the
        # clock or the controls.
        self.time_label = tk.Label(self.body, text="0:00:00",
                                   bg=self.theme["surface"],
                                   fg=self.theme["text"],
                                   font=self.theme.font("timer"))
        self.time_label.pack(side="right", padx=(0, self.theme.space["sm"]))

        self.summary_label = tk.Label(
            self.body, text=shorten(self.state.get("summary")),
            bg=self.theme["surface"], fg=self.theme["text_muted"],
            font=self.theme.font("small"), anchor="w",
        )
        self.summary_label.pack(side="left", fill="x", expand=True,
                                padx=(self.theme.space["sm"], 0))

        self.controls = tk.Frame(self.body, bg=self.theme["surface"])
        self.pause_button = self._control("⏸", self.toggle_pause)
        self.stop_button = self._control("⏹", self.stop)
        self.open_button = self._control("⤡", self._open_day)

        self.checkin = tk.Frame(self.window, bg=self.theme["surface"])
        self._build_checkin()

        for widget in (self.body, self.dot, self.key_label, self.time_label):
            widget.bind("<Enter>", self._expand)
            widget.bind("<Leave>", self._collapse)
            widget.bind("<Button-1>", self._grab)
            widget.bind("<B1-Motion>", self._drag)

    def _control(self, glyph, command):
        button = tk.Label(self.controls, text=glyph, bg=self.theme["surface"],
                          fg=self.theme["text_muted"],
                          font=self.theme.font("body"), cursor="hand2")
        button.pack(side="left", padx=self.theme.space["xs"])
        button.bind("<Button-1>", lambda _e: command())
        button.bind("<Enter>", lambda _e, w=button: w.configure(
            fg=self.theme["text"]))
        button.bind("<Leave>", lambda _e, w=button: w.configure(
            fg=self.theme["text_muted"]))
        return button

    def _build_checkin(self):
        self.checkin_question = tk.Label(
            self.checkin, text="", bg=self.theme["surface"],
            fg=self.theme["text"], font=self.theme.font("body"), anchor="w",
        )
        self.checkin_question.pack(fill="x", padx=self.theme.space["sm"])

        buttons = tk.Frame(self.checkin, bg=self.theme["surface"])
        buttons.pack(fill="x", padx=self.theme.space["sm"],
                     pady=(self.theme.space["xs"], self.theme.space["sm"]))

        for text, command in (("Keep going", self.keep_going),
                              ("Switch", self._open_day),
                              ("Stop", self.stop)):
            button = tk.Label(buttons, text=text, bg=self.theme["surface_hi"],
                              fg=self.theme["text"],
                              font=self.theme.font("small"),
                              padx=self.theme.space["sm"], pady=2,
                              cursor="hand2")
            button.pack(side="left", padx=(0, self.theme.space["xs"]))
            button.bind("<Button-1>", lambda _e, c=command: c())

    # -- dragging -----------------------------------------------------------

    def _grab(self, event):
        self._drag_origin = (event.x_root, event.y_root,
                             self.window.winfo_x(), self.window.winfo_y())

    def _drag(self, event):
        if not self._drag_origin:
            return
        start_x, start_y, window_x, window_y = self._drag_origin
        self.window.geometry(
            f"+{window_x + event.x_root - start_x}"
            f"+{window_y + event.y_root - start_y}"
        )

    # -- hover --------------------------------------------------------------

    def _expand(self, _event=None):
        if self._expanded or self.checkin_visible:
            return
        self._expanded = True
        self._place("strip_hover")
        # `before` puts the controls ahead of the title in the packing order,
        # so they are allocated their width first. Packed after it, they were
        # given whatever the title left over, which was nothing.
        self.controls.pack(side="right", before=self.summary_label,
                           padx=(0, self.theme.space["xs"]))

    def _collapse(self, _event=None):
        if not self._expanded:
            return
        # Only collapse once the pointer has really left the whole strip.
        pointer = self.window.winfo_containing(
            self.window.winfo_pointerx(), self.window.winfo_pointery()
        )
        if pointer and str(pointer).startswith(str(self.window)):
            return
        self._expanded = False
        self.controls.pack_forget()
        self._place()

    # -- the clock ----------------------------------------------------------

    def _schedule_tick(self):
        try:
            self.window.after(TICK_MILLISECONDS, self._on_tick)
        except tk.TclError:
            pass

    def _on_tick(self):
        # Stopping destroys this window while a tick is already queued. Let
        # that last beat land on nothing rather than on dead widgets.
        try:
            self.tick(datetime.now())
        except tk.TclError:
            return
        self._schedule_tick()

    def tick(self, now):
        """One beat: refresh the display, persist occasionally, ask if due."""
        self.time_label.configure(text=format_hhmmss(
            timer.elapsed_seconds(self.state, now)
        ))

        if (now - self._last_persist).total_seconds() >= self.config.heartbeat_seconds:
            self.state = timer.heartbeat(self.state, now)
            self.callbacks.on_persist(self.state)
            self._last_persist = now

        if not self.checkin_visible and timer.needs_checkin(
            self.state, now, self.config.checkin_minutes
        ):
            self._show_checkin(now)

    # -- check-in -----------------------------------------------------------

    def _show_checkin(self, now):
        self.checkin_visible = True
        elapsed = format_hhmmss(timer.elapsed_seconds(self.state, now))
        self.checkin_question.configure(
            text=f"Still on {self.state['issue_key']}?  running {elapsed}\n"
                 f"{shorten(self.state.get('summary'), limit=40)}"
        )

        width, height = self.theme.metrics["strip_checkin"]
        x, y = strip_position(
            work_area() or (0, 0, self.window.winfo_screenwidth(),
                            self.window.winfo_screenheight()),
            width, height, self.theme.metrics["strip_margin"],
        )
        self.window.geometry(f"{width}x{height}+{x}+{y}")
        self.checkin.pack(fill="both", expand=True, padx=1, pady=(0, 1))

        # The strip alone is easy to miss — small, silent, and often behind
        # whatever the screen actually belongs to. A real notification is
        # what gets noticed away from the corner.
        notify.toast(
            self.window, "Still tracking?",
            f"{self.state['issue_key']} — running {elapsed}",
            icon_path=icon.ICO,
        )

    def _hide_checkin(self):
        self.checkin_visible = False
        self.checkin.pack_forget()
        self._place()

    def keep_going(self, now=None):
        self.state = timer.confirm(self.state, now or datetime.now())
        self.callbacks.on_persist(self.state)
        self._hide_checkin()

    # -- controls -----------------------------------------------------------

    def is_paused(self):
        return timer.is_paused(self.state)

    def toggle_pause(self, now=None):
        now = now or datetime.now()
        if self.is_paused():
            self.state = timer.resume(self.state, now)
        else:
            self.state = timer.pause(self.state, now)

        paused = self.is_paused()
        self.dot.configure(
            fg=self.theme["text_muted"] if paused else self.theme["accent"]
        )
        self.time_label.configure(
            fg=self.theme["text_muted"] if paused else self.theme["text"]
        )
        self.pause_button.configure(text="▶" if paused else "⏸")
        self.callbacks.on_persist(self.state)

    def stop(self, now=None):
        now = now or datetime.now()
        piece = timer.segment(self.state, now, self.config.checkin_minutes)
        self.callbacks.on_stop(piece)
        self.close()

    def close(self):
        try:
            self.window.destroy()
        except tk.TclError:
            pass

    def _open_day(self):
        self.callbacks.on_open_day()
