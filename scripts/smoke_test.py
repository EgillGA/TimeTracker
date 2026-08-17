"""Check TimeTracker's assumptions against the real Jira and Tempo.

Run this once, before trusting anything else. It answers the questions the
unit tests cannot: does authentication work, does this site use the newer
search endpoint, does Tempo accept a worklog without extra attributes.

    py scripts\\smoke_test.py

Read-only by default. To also test writing a worklog — one minute against an
issue you name — pass the issue key explicitly:

    py scripts\\smoke_test.py --write-test AV-412

Nothing is written unless you pass that flag with a key.
"""

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from timetracker.config import MissingCredentials, load_config, load_credentials
from timetracker.http import ApiError
from timetracker.jira import JiraClient
from timetracker.tempo import TempoClient
from timetracker.week import weekdays_of_week

ROOT = Path(__file__).resolve().parent.parent


def heading(text):
    print(f"\n{text}\n{'-' * len(text)}")


def check(label, function):
    """Run one probe, print a verdict, and keep going when it fails."""
    try:
        result = function()
    except Exception as error:  # noqa: BLE001 - the point is to report anything
        print(f"  FAIL  {label}\n        {error}")
        return None
    print(f"  ok    {label}")
    return result


def main(argv):
    write_test_key = None
    if "--write-test" in argv:
        index = argv.index("--write-test")
        if index + 1 >= len(argv):
            print("--write-test needs an issue key, e.g. --write-test AV-412")
            return 2
        write_test_key = argv[index + 1]

    config = load_config(ROOT)
    try:
        jira_token, tempo_token = load_credentials(ROOT)
    except MissingCredentials as error:
        print(error)
        return 1

    jira = JiraClient(config.jira_site, config.jira_email, jira_token)
    tempo = TempoClient(tempo_token)

    heading(f"Jira — {config.jira_site}")
    account_id = check("authenticate and read account id", jira.account_id)
    if account_id:
        print(f"        accountId = {account_id}")

    issues = {}
    for name in ("assigned", "recent", "internal"):
        found = check(f"JQL [{name}]", lambda n=name: jira.search(config.jql[n]))
        if found is not None:
            issues[name] = found
            print(f"        {len(found)} issue(s)")
            for entry in found[:3]:
                print(f"          {entry['key']:<10} {entry['summary'][:48]}")

    print(f"\n        search endpoint: "
          f"{'legacy /rest/api/2/search' if jira._use_legacy_search else 'enhanced /rest/api/3/search/jql'}")

    if "internal" in issues and not issues["internal"]:
        print(f"\n  WARNING  project '{config.internal_project}' returned no open "
              f"issues.\n           Check [internal] project in config.toml.")

    heading("Tempo — this week")
    if account_id:
        week = weekdays_of_week(date.today())
        totals = check(
            "read worklogs",
            lambda: tempo.seconds_by_date(account_id, week[0], week[-1]),
        )
        if totals is not None:
            if not totals:
                print("        no worklogs this week")
            for day in week:
                seconds = totals.get(day, 0)
                print(f"        {day:%a %d %b}  {seconds / 3600:5.2f} h")

    heading("Tempo — writing")
    if not write_test_key:
        print("  skipped — pass --write-test <ISSUE-KEY> to test creating a worklog.")
        print("            It logs one minute, which you can delete in Tempo.")
    elif account_id:
        issue_id = check(f"resolve {write_test_key}",
                         lambda: jira.issue_id(write_test_key))
        if issue_id:
            worklog_id = check(
                "create a 1-minute worklog",
                lambda: tempo.create_worklog(
                    account_id=account_id, issue_id=issue_id, seconds=60,
                    day=date.today(), description="TimeTracker smoke test",
                ),
            )
            if worklog_id:
                print(f"        created worklog {worklog_id} — delete it in Tempo.")
                print("        No extra work attributes were required.")

    heading("What this told us")
    print("  If every line above says ok, the assumptions in the design spec hold")
    print("  and the day window can be built directly on them.")
    print("\n  If the write test failed with a message about a required attribute")
    print("  or account, that changes the design: every row in the day window")
    print("  will need one extra dropdown. Send me the exact message.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except ApiError as error:
        print(f"\nStopped: {error}")
        sys.exit(1)
