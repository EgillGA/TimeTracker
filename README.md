# TimeTracker

A 15:30 nudge that turns "what did I do today?" into a filled-in Tempo
timesheet, plus an optional live timer and a Friday check that the week is
actually complete.

Built for one person on one Windows machine, against Jira Cloud and Tempo.

## Why it exists

The hours get worked; the logging doesn't happen. Not for lack of data — Jira
already knows what was touched — but for lack of a prompt while the day is
still fresh. TimeTracker asks at 15:30, pre-filled, and takes about twenty
seconds to answer.

## Requirements

Python 3.11 or newer, and nothing else. No pip, no virtualenv, no
dependencies — standard library only, so it cannot break because a package
moved on without it.

## Setup

1. Create two API tokens:
   - **Jira** — <https://id.atlassian.com/manage-profile/security/api-tokens>
   - **Tempo** — in Jira: Apps → Tempo → Settings → API integration
2. Copy `credentials.example.toml` to `credentials.toml` and paste both in.
   That file is git-ignored and never leaves your machine.
3. Check the connection:

   ```
   py scripts\smoke_test.py
   ```

   Read-only. It authenticates, runs the issue queries, and prints your week
   from Tempo. Add `--write-test AV-412` to also log one test minute against
   an issue you name.

4. Adjust `config.toml` if needed — Jira site, hours per day, prompt time,
   which project counts as internal, and the JQL behind each list.

## Running

| Command | What happens |
|---|---|
| `py -m timetracker` | Day window |
| `py -m timetracker --week` | Week overview |
| `py -m timetracker --timer AP-7500` | Start the live timer on an issue |
| `py -m timetracker --preview` | Day window with invented data, no network |
| `py -m timetracker --auto` | What the scheduled task runs |

## The week

The **▦ Week** button at the top of the day window opens Monday to Friday with
what each day holds against its eight hours, and the week's shortfall at the
bottom.

Click any day to open it in place. Hours already in Tempo are shown as text and
never in a box — back-dated entry is where logging the same hours twice is
easiest to do and hardest to notice. Beside them is an empty box that takes
more time for the same issue, and a button that adds only what you have typed.

Fridays open here rather than on the day, because on a Friday the four days
behind you matter more than today and are the last chance to fix them.

## The live timer

Press `▶` on any issue in the day window, or start one from the command line.
A thin strip parks in the bottom-right corner above the clock, showing the
issue and the elapsed time. Hovering reveals pause and stop.

Every hour it expands in place to ask whether that is still what you are
doing. It asks; it never overrules. Ignore it and the timer keeps running, but
the time is flagged and shows amber in the day window rather than being
quietly billed.

Stopping adds the time to today and opens the day window, so stopping the
timer is also how the day gets closed out. Nothing reaches Tempo until you
press Submit.

If the process dies while a timer is running, the next launch folds the time
back in — bounded by the last heartbeat rather than the wall clock, so a
machine that slept through lunch does not bill for it. Recovered time is
always flagged.

## Appearing on its own

```
py install.py
```

Creates one scheduled task, as you, with no administrator rights. It fires at
15:30 on weekdays and again two minutes after logon, and each time the program
decides for itself whether there is anything worth showing — so unlocking your
laptop at ten in the morning costs nothing, while a day the machine was off at
15:30 still gets its prompt.

It stays silent when the day is settled: something reached Tempo and nothing
is still waiting. A part-submitted day is not settled, and does prompt.

```
py install.py --status     is it installed, when does it next run
py install.py --dry-run    print the task definition, change nothing
schtasks /Run /TN TimeTracker    trigger it now
py uninstall.py            remove it
```

Removal is documented as prominently as installation on purpose: an automation
you cannot easily switch off is one that gets killed crudely instead.

## Tests

```
py -m unittest discover -s tests
```

Everything that can be tested without opening a window is. The pure logic —
duration parsing, week arithmetic, storage — has no I/O; the API clients take
their transport as an argument and are tested against recorded responses.

## Layout

```
timetracker/
  config.py    settings and credentials
  duration.py  parsing "1,5" / "1:30" / "90m" into seconds
  http.py      shared transport and error handling
  jira.py      issue search, key to id resolution
  tempo.py     reading the week, creating worklogs
  store.py     local day records and timer state
  week.py      targets, totals, gaps
  theme.py     design tokens
  ui_*.py      the windows
scripts/       smoke test and utilities
docs/          design spec
```

## Design

The full design, including the reasoning behind what was deliberately left
out, is in
[`docs/superpowers/specs/2026-08-17-timetracker-design.md`](docs/superpowers/specs/2026-08-17-timetracker-design.md).

## Status

Everything in the design is built: the day window against live Jira and Tempo,
submission with real start times, the scheduled task, the live timer with its
hourly check-in and crash recovery, and the week overview with back-dated
editing.

Deliberately absent, with reasons in the design document: editing or deleting
worklogs already in Tempo, idle detection that pauses the timer for you, and
reading required hours from Tempo's work schedule.
