"""Remove TimeTracker's scheduled task.

    py uninstall.py

Deletes only the task. Your config, credentials and recorded days are left
alone, so reinstalling picks up exactly where you left off.

This exists and is documented because an automation you cannot easily turn
off is one that gets killed crudely instead.
"""

import subprocess
import sys

TASK_NAME = "TimeTracker"


def main():
    result = subprocess.run(
        ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
        capture_output=True, text=True,
    )

    if result.returncode != 0:
        output = (result.stdout or result.stderr).strip()
        if "cannot find" in output.lower():
            print(f"'{TASK_NAME}' was not installed. Nothing to do.")
            return 0
        print(f"Could not remove the task:\n\n{output}")
        return result.returncode

    print(f"Removed. TimeTracker will no longer open on its own.")
    print("Your settings and recorded days are untouched.")
    print("\n  py -m timetracker    still opens it by hand")
    print("  py install.py        puts it back")
    return 0


if __name__ == "__main__":
    sys.exit(main())
