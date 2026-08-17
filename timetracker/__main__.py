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
        from timetracker import ui_notice

        ui_notice.show("Not built yet",
                       "The week overview is the next thing being built.\n\n"
                       "For now, open the day window without --week.")
        return 0

    return open_day()


def run_auto():
    """The scheduled path: decide, then get out of the way if there is nothing."""
    from timetracker import launch
    from timetracker.config import load_config
    from timetracker.single_instance import SingleInstance
    from timetracker.store import Store

    config = load_config(ROOT)
    record = Store().load_day(date.today())

    if launch.decide(datetime.now(), record, config) == launch.NOTHING:
        return 0

    # A window is already open — probably the one you are typing into. The
    # logon trigger must not stack a second copy of the day on top of it.
    with SingleInstance() as lock:
        if not lock.acquired:
            return 0
        return open_day()


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
    return _run_session(open_with_timer=None)


def _build_day_window(master, service, theme, on_start_timer, on_running=None):
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
        ),
        theme,
    )


def run_timer(issue_key):
    """Start the strip on an issue and stay running until it is stopped."""
    return _run_session(open_with_timer=issue_key)


def _run_session(open_with_timer):
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
        ),
    )

    if open_with_timer:
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
