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


def open_day():
    from timetracker import app, ui_notice
    from timetracker.config import MissingCredentials, load_config
    from timetracker.theme import Theme

    theme = Theme(load_config(ROOT).theme)

    try:
        service = app.build(ROOT)
    except MissingCredentials as error:
        ui_notice.show("TimeTracker needs setting up", str(error),
                       open_path=ROOT / "credentials.toml", theme=theme)
        return 1

    data = service.load_day()

    from timetracker.ui_day import DayCallbacks, DayWindow

    root = tk.Tk()
    DayWindow(
        root, data,
        DayCallbacks(
            on_change=service.save,
            on_submit=lambda record: service.submit(record, data.day),
            on_lookup=service.lookup,
            on_start_timer=lambda issue: _timer_not_ready(theme),
        ),
        theme,
    )
    root.mainloop()
    return 0


def _timer_not_ready(theme):
    from timetracker import ui_notice

    ui_notice.show(
        "The live timer is not built yet",
        "Starting a timer from an issue arrives in a later step.\n\n"
        "For now, type the hours straight into the box.",
        theme=theme,
    )


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
