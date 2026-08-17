"""What one run of TimeTracker consists of.

One window showing one page at a time, and optionally a timer strip. This
owns the rules connecting them: which page is up, what happens when a timer
stops, and what closing the window means depending on whether one is running.

Those rules used to live in closures inside the entry point where nothing
could test them, and were wrong three times as a result.
"""

from datetime import date

from timetracker import dayview


class TimerSession:
    def __init__(self, shell, record, save_day, clear_timer, load_day=None):
        self.shell = shell
        self.record = record
        self.save_day = save_day
        self.clear_timer = clear_timer
        self.load_day = load_day or (lambda day: record)

        self.strip = None
        self.timing = False

    # -- the timer ----------------------------------------------------------

    def start_timer(self, strip_factory):
        """Begin timing, leaving whatever page is up exactly where it is."""
        self.strip = strip_factory(self.shell.window)
        self.timing = True
        return self.strip

    def running_state(self):
        """The timer's state, or None once it has stopped.

        A paused timer still reports itself: its figure freezes, which is what
        paused looks like, rather than the row vanishing.
        """
        if not self.timing or self.strip is None:
            return None
        return self.strip.state

    # -- pages --------------------------------------------------------------

    def show_day(self, day=None):
        day = day or date.today()
        view = self.shell.show_day(day)
        self.shell.present()

        # Today's page owns the record this session writes to, so that folding
        # in a finished run and refreshing the page touch the same dict.
        if day == date.today():
            record = getattr(getattr(view, "data", None), "record", None)
            if record is not None:
                self.record = record
        return view

    def show_week(self):
        view = self.shell.show_week()
        self.shell.present()
        return view

    # -- stopping -----------------------------------------------------------

    def stop(self, piece):
        """Fold a finished run into today and show it.

        Always lands on today's page: stopping the timer is how a day gets
        closed out, and the hours just recorded are today's.
        """
        self.timing = False
        self.clear_timer()

        today = date.today()
        on_today = (self.shell.showing == "day"
                    and getattr(getattr(self.shell.view, "data", None),
                                "day", None) == today)

        if on_today:
            dayview.add_segment(self.record, piece)
            self.save_day(self.record)
            self.shell.view.data.running = None
            self.shell.view.refresh()
            self.shell.present()
            return self.shell.view

        # Save against today's record on disk, then let the page load it.
        record = self.load_day(today)
        dayview.add_segment(record, piece)
        self.save_day(record)
        return self.show_day(today)

    # -- closing ------------------------------------------------------------

    def close_window(self):
        """The window's X, or Escape.

        With a timer running the window only hides — the strip is still doing
        its job and killing it would throw away the run. With nothing running
        there is nothing left, so this ends the program.
        """
        if self.timing:
            self.shell.hide()
            return False

        self.shell.window.destroy()
        return True
