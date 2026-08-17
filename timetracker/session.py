"""Window lifecycle for one timer run.

The strip and the day window share a single Tk root and a single event loop, so
one of them has to own the rules about when each exists. That ownership lived
in closures inside the entry point, where nothing could test it — and stopping
the timer tore down the root and rebuilt the day window, which looked exactly
like the window closing and reopening.

Kept separate from tkinter widget construction: `day_builder` is injected, so
these transitions can be tested without a real day window.
"""

import tkinter as tk

from timetracker import dayview


class TimerSession:
    def __init__(self, root, record, save_day, clear_timer, day_builder):
        self.root = root
        self.record = record
        self.save_day = save_day
        self.clear_timer = clear_timer
        self.day_builder = day_builder

        self.strip = None
        self.toplevel = None
        self.day = None
        # False until a timer is actually running. That matters for the rule
        # below about closing the day window: with no timer going, closing it
        # is the end of the run.
        self.timing = False

    # -- the timer ----------------------------------------------------------

    def start_timer(self, strip_factory):
        """Begin timing, leaving any open day window exactly where it is.

        Starting a timer used to tear the day window down and rebuild it when
        the timer stopped, which read as the window closing and reopening.
        Both now live in the same session, so neither disturbs the other.
        """
        self.strip = strip_factory(self.root)
        self.timing = True
        return self.strip

    # -- what the day window asks -------------------------------------------

    def running_state(self):
        """The timer's state, or None once it has stopped.

        A paused timer still reports itself: the elapsed figure freezes, which
        is what paused looks like, rather than the row vanishing.
        """
        if not self.timing or self.strip is None:
            return None
        return self.strip.state

    # -- windows ------------------------------------------------------------

    def day_is_open(self):
        return self.toplevel is not None and self.toplevel.winfo_exists()

    def show_day(self):
        """Open the day window, or bring the one already open to the front."""
        if self.day_is_open():
            self.toplevel.deiconify()
            self.toplevel.lift()
            self.toplevel.focus_force()
            return self.day

        self.toplevel = tk.Toplevel(self.root)
        self.day = self.day_builder(self.toplevel, self.running_state)

        # The window loads its own record. Adopt it, so there is exactly one
        # of them: otherwise stopping the timer would add the run to the
        # session's copy, save that, and overwrite whatever had been typed
        # into the window.
        window_record = getattr(self.day.data, "record", None)
        if window_record is not None:
            self.record = window_record

        self._end_run_when_closed(self.toplevel)
        return self.day

    def _end_run_when_closed(self, toplevel):
        """Once the timer has stopped this is the only window left, so closing
        it must end the run. While a timer is still going it must not: the
        strip is still there doing its job."""
        def closed(event):
            if event.widget is toplevel and not self.timing:
                try:
                    self.root.destroy()
                except tk.TclError:
                    pass

        toplevel.bind("<Destroy>", closed)

    # -- stopping -----------------------------------------------------------

    def stop(self, piece):
        """Fold a finished run into the day and show it.

        The record is the one the open window is already holding, so the window
        and the file stay the same thing and the window never has to be rebuilt
        to see the new hours.
        """
        self.timing = False
        self.clear_timer()

        dayview.add_segment(self.record, piece)
        self.save_day(self.record)

        if self.day_is_open():
            self.day.data.running = None
            self.day.refresh()
            self.show_day()
            return self.day

        return self.show_day()
