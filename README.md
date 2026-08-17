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

## One window

TimeTracker is one program in one window. The day and the week are pages inside
it, so moving between them is navigation rather than a pile of windows to sort
through.

The timer strip is the single exception: borderless and always on top over the
clock is not something a page inside a normal window can be.

## The week

The **▦ Week** button at the top of the day page opens Monday to Friday with
what each day holds against its eight hours, and the week's shortfall at the
bottom.

Click any day and you get the ordinary day page for that date — the same page,
the same tabs, the same rules. There is no separate back-dated editor, which
means there is only one place the protections against logging the same hours
twice have to be right. Hours already in Tempo show as text beside an empty box
that adds new time to the same issue.

Fridays open on the week rather than the day, because by Friday the four days
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

### Pinning it to the taskbar

`py install.py` also adds a **TimeTracker** shortcut to the Start Menu. Find
it there, right-click, and choose **Pin to taskbar**.

This exists because the scheduled task runs `wscript.exe` on a `.vbs`
launcher, and a running window with no shortcut behind it is either unable to
be pinned at all, or gets pinned as a bare `pyw.exe` with none of the
arguments that make it TimeTracker. The Start Menu shortcut carries the same
application id as the running window, so pinning from there does the right
thing. `py uninstall.py` removes it again — unpin first if you had pinned it,
since removing the shortcut leaves a pin with nothing behind it.

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
  icon.py      the window icon
  win.py       taskbar identity and dark title bar
  shortcut.py  the Start Menu shortcut install.py creates, so it can be pinned
  session.py   which page is up, and what stopping a timer means
  ui_shell.py  one window, several pages
assets/        icon at every size Windows asks for
scripts/       smoke test and utilities
docs/          design spec
```

The icon is committed as PNGs and a packed `.ico`. To rebuild it from new
artwork, point `scripts/make_icon.ps1` at the source image and run:

```
powershell -File scripts\make_icon.ps1    crop and render the sizes
py scripts\build_icon.py                  pack them into icon.ico
```

Both are authoring steps. The program only ever loads the results, so it keeps
its no-dependencies promise.

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
