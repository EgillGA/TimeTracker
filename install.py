"""Install the scheduled task that makes TimeTracker appear on its own.

    py install.py             install or replace the task
    py install.py --dry-run   print the task definition, change nothing
    py install.py --status    show whether it is installed

Runs as you, needs no administrator rights, and touches nothing outside your
own Task Scheduler. Remove it with `py uninstall.py`.

One task with two triggers rather than two tasks: half past three on weekdays,
and again two minutes after logon. Both run the same command, and the program
decides whether to show anything — so the rule about when to appear lives in
tested code rather than being split across two task definitions that could
drift apart.
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from timetracker import shortcut, win
from timetracker.config import load_config
from timetracker.duration import format_clock, parse_clock

ROOT = Path(__file__).resolve().parent
TASK_NAME = "TimeTracker"
LAUNCHER = ROOT / "run_timetracker.vbs"
ICON = ROOT / "assets" / "icon.ico"
START_MENU_SHORTCUT = (
    Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows"
    / "Start Menu" / "Programs" / "TimeTracker.lnk"
)

TASK_XML = """<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Opens TimeTracker so the day's hours reach Tempo.</Description>
    <URI>\\{task_name}</URI>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>2026-01-05T{prompt_time}</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByWeek>
        <DaysOfWeek>
          <Monday /><Tuesday /><Wednesday /><Thursday /><Friday />
        </DaysOfWeek>
        <WeeksInterval>1</WeeksInterval>
      </ScheduleByWeek>
    </CalendarTrigger>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>{user}</UserId>
      <Delay>PT2M</Delay>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{user}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>wscript.exe</Command>
      <Arguments>"{launcher}" --auto</Arguments>
      <WorkingDirectory>{root}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def current_user():
    domain = os.environ.get("USERDOMAIN", "")
    name = os.environ.get("USERNAME", "")
    return f"{domain}\\{name}" if domain else name


def build_xml():
    config = load_config(ROOT)
    prompt_seconds = parse_clock(config.prompt_time, 15 * 3600 + 30 * 60)

    return TASK_XML.format(
        task_name=TASK_NAME,
        prompt_time=format_clock(prompt_seconds),
        user=current_user(),
        launcher=LAUNCHER,
        root=ROOT,
    )


def install_shortcut():
    """A Start Menu entry for the same launch the scheduled task uses.

    The scheduled task runs wscript.exe on the .vbs launcher - fine for Task
    Scheduler, but nothing a taskbar pin can point at. This gives it a real
    shortcut, carrying the same application id the running window claims, so
    right-clicking that shortcut and choosing "Pin to taskbar" actually works.
    """
    wscript = shutil.which("wscript.exe") or str(
        Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "wscript.exe"
    )
    START_MENU_SHORTCUT.parent.mkdir(parents=True, exist_ok=True)
    return shortcut.create(
        str(START_MENU_SHORTCUT),
        target=wscript,
        arguments=f'"{LAUNCHER}"',
        working_dir=str(ROOT),
        icon=str(ICON) if ICON.exists() else "",
        description="Open TimeTracker",
        app_id=win.APP_ID,
    )


def install():
    if not LAUNCHER.exists():
        print(f"Can't find {LAUNCHER.name}. Run this from the TimeTracker folder.")
        return 1

    # schtasks insists on UTF-16 for task XML.
    handle, path = tempfile.mkstemp(suffix=".xml")
    os.close(handle)
    Path(path).write_text(build_xml(), encoding="utf-16")

    try:
        result = subprocess.run(
            ["schtasks", "/Create", "/TN", TASK_NAME, "/XML", path, "/F"],
            capture_output=True, text=True,
        )
    finally:
        Path(path).unlink(missing_ok=True)

    if result.returncode != 0:
        print("Could not create the task:\n")
        print(result.stdout or result.stderr)
        return result.returncode

    config = load_config(ROOT)
    print(f"Installed. TimeTracker will open at {config.prompt_time} on weekdays,")
    print("and shortly after logon if the machine was off at the time.")
    print(f"\nIt stays quiet unless there is something to deal with.")

    if install_shortcut():
        print(f"\nAdded a Start Menu shortcut named TimeTracker - right-click it")
        print('there and choose "Pin to taskbar" to keep it one click away.')
    else:
        print("\nCould not create the Start Menu shortcut. The scheduled task")
        print("is unaffected, but there's nothing new to pin to the taskbar.")

    print(f"\n  py install.py --status     check it")
    print(f"  py uninstall.py            remove it")
    print(f"  schtasks /Run /TN {TASK_NAME}   try it now")
    return 0


def status():
    result = subprocess.run(
        ["schtasks", "/Query", "/TN", TASK_NAME, "/V", "/FO", "LIST"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"'{TASK_NAME}' is not installed. Run: py install.py")
        return 1

    wanted = ("TaskName", "Status", "Next Run Time", "Last Run Time",
              "Last Result", "Task To Run", "Scheduled Task State")
    for line in result.stdout.splitlines():
        if any(line.strip().startswith(field) for field in wanted):
            print(f"  {line.strip()}")

    if START_MENU_SHORTCUT.exists():
        print("  Start Menu shortcut: present (right-click it to pin)")
    else:
        print("  Start Menu shortcut: missing - run py install.py to add it")
    return 0


def main(argv):
    if "--dry-run" in argv:
        print(build_xml())
        return 0
    if "--status" in argv:
        return status()
    return install()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
