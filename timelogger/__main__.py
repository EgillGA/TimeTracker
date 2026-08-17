"""Entry point.

    py -m timelogger              day window
    py -m timelogger --week       week overview
    py -m timelogger --preview    the day window with invented data

Wiring to live Jira and Tempo data arrives with the app service; for now
--preview is the way to look at the window.
"""

import sys


def main(argv):
    if "--preview" in argv:
        from timelogger.ui_day import preview

        theme = "light" if "light" in argv else "dark"
        preview(theme)
        return 0

    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
