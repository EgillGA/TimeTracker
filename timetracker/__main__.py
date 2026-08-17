"""Entry point.

    py -m timetracker              the day window, with live Jira and Tempo
    py -m timetracker --auto       what the scheduled task runs
    py -m timetracker --week       the week overview (not built yet)
    py -m timetracker --preview    the day window with invented data

--auto is the one the Task Scheduler calls, at 15:30 on weekdays and again
after logon. It decides for itself whether there is anything worth showing
and exits silently when there is not, so an unlock at ten in the morning
costs nothing.
"""

import sys
import tkinter as tk
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main(argv):
    if "--preview" in argv:
        from timetracker.ui_day import preview

        preview("light" if "light" in argv else "dark")
        return 0

    if "--auto" in argv:
        return run_auto()

    if "--timer" in argv:
        index = argv.index("--timer")
        if index + 1 >= len(argv):
            print("--timer needs an issue key, e.g. --timer AP-7500")
            return 2
        return run_timer(argv[index + 1])

    if "--week" in argv:
        return open_week()

    return open_day()


def run_auto():
    """The scheduled path: decide, then get out of the way if there is nothing."""
    from timetracker import launch
    from timetracker.config import load_config
    from timetracker.single_instance import SingleInstance
    from timetracker.store import Store

    config = load_config(ROOT)
    record = Store().load_day(date.today())

    action = launch.decide(datetime.now(), record, config)
    if action == launch.NOTHING:
        return 0

    # A window is already open — probably the one you are typing into. The
    # logon trigger must not stack a second copy of the day on top of it.
    with SingleInstance() as lock:
        if not lock.acquired:
            return 0
        # Fridays open on the week: today's hours matter less than the four
        # days behind it that can still be fixed.
        return open_week() if action == launch.WEEK else open_day()


def _service_or_setup(theme):
    from timetracker import app, ui_notice
    from timetracker.config import MissingCredentials

    try:
        return app.build(ROOT)
    except MissingCredentials as error:
        ui_notice.show("TimeTracker needs setting up", str(error),
                       open_path=ROOT / "credentials.toml", theme=theme)
        return None


def open_day():
    """The day window, with ▶ able to start a timer without closing it."""
    return _run_session()


def open_week():
    """The week overview on its own."""
    return _run_session(start_on_week=True)


def _build_day_window(master, service, theme, on_start_timer, on_running=None,
                      on_show_week=None):
    """Attach a day window to an existing root or toplevel."""
    from timetracker.ui_day import DayCallbacks, DayWindow

    data = service.load_day()
    return DayWindow(
        master, data,
        DayCallbacks(
            on_change=service.save,
            on_submit=lambda record: service.submit(record, data.day),
            on_lookup=service.lookup,
            on_start_timer=on_start_timer,
            on_running=on_running,
            on_show_week=on_show_week or (lambda: None),
        ),
        theme,
    )


def _build_week_window(master, service, theme):
    """Attach the week overview to an existing toplevel."""
    from timetracker.ui_week import WeekCallbacks, WeekWindow

    return WeekWindow(
        master, service.load_week(),
        WeekCallbacks(
            on_change=service.save,
            on_submit=service.submit,
            on_lookup=service.lookup,
        ),
        theme,
    )


def run_timer(issue_key):
    """Start the strip on an issue and stay running until it is stopped."""
    return _run_session(open_with_timer=issue_key)


def _run_session(open_with_timer=None, start_on_week=False):
    """One session, one event loop, whichever end you come in from.

    Both the day window and the timer strip belong to the same TimerSession,
    so starting a timer never closes the day window and stopping one never
    rebuilds it.
    """
    from timetracker import ui_notice
    from timetracker.config import load_config
    from timetracker.session import TimerSession
    from timetracker.store import Store
    from timetracker.theme import Theme
    from timetracker.ui_strip import StripCallbacks, TimerStrip

    config = load_config(ROOT)
    theme = Theme(config.theme)

    service = _service_or_setup(theme)
    if service is None:
        return 1

    store = Store()
    root = tk.Tk()
    root.withdraw()

    # One event loop for both windows, and one object owning when each of them
    # exists. Those rules used to live in closures right here, where no test
    # could reach them, and were wrong twice as a result. See session.py.
    def begin(issue):
        """Put the strip on screen for an issue, leaving windows alone."""
        return session.start_timer(lambda parent: TimerStrip(
            parent, issue, config,
            StripCallbacks(
                on_persist=store.save_timer,
                on_stop=session.stop,
                on_open_day=session.show_day,
            ),
            theme,
        ))

    session = TimerSession(
        root=root,
        record=store.load_day(date.today()),
        save_day=store.save_day,
        clear_timer=store.clear_timer,
        day_builder=lambda toplevel, on_running: _build_day_window(
            toplevel, service, theme,
            on_start_timer=begin,
            # The strip is the authority while it runs, so ask it rather than
            # re-reading the file it only writes every 30 seconds.
            on_running=on_running,
            on_show_week=lambda: session.show_week(),
        ),
        week_builder=lambda toplevel: _build_week_window(
            toplevel, service, theme
        ),
    )

    if start_on_week:
        session.show_week()
    elif open_with_timer:
        issue = service.lookup(open_with_timer)
        if issue is None:
            ui_notice.show("No such issue",
                           f"Couldn't find {open_with_timer} in Jira.",
                           theme=theme)
            return 1
        begin(issue)
    else:
        session.show_day()

    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
