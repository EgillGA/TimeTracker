"""Remove TimeTracker's scheduled task.

    py uninstall.py

Deletes only the task. Your config, credentials and recorded days are left
alone, so reinstalling picks up exactly where you left off.

This exists and is documented because an automation you cannot easily turn
off is one that gets killed crudely instead.
"""

import os
import subprocess
import sys
from pathlib import Path

TASK_NAME = "TimeTracker"
START_MENU_SHORTCUT = (
    Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows"
    / "Start Menu" / "Programs" / "TimeTracker.lnk"
)


def remove_shortcut():
    try:
        START_MENU_SHORTCUT.unlink()
        return True
    except FileNotFoundError:
        return False


def main():
    result = subprocess.run(
        ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
        capture_output=True, text=True,
    )

    task_missing = False
    if result.returncode != 0:
        output = (result.stdout or result.stderr).strip()
        if "cannot find" not in output.lower():
            print(f"Could not remove the task:\n\n{output}")
            return result.returncode
        task_missing = True

    removed_shortcut = remove_shortcut()

    if task_missing and not removed_shortcut:
        print(f"'{TASK_NAME}' was not installed. Nothing to do.")
        return 0

    print(f"Removed. TimeTracker will no longer open on its own.")
    print("Your settings and recorded days are untouched.")
    if removed_shortcut:
        print("\nAlso removed the Start Menu shortcut. If you had pinned it to")
        print("the taskbar, that pin is now broken and worth unpinning by hand.")
    print("\n  py -m timetracker    still opens it by hand")
    print("  py install.py        puts it back")
    return 0


if __name__ == "__main__":
    sys.exit(main())
