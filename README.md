# Timelogger

A 15:30 nudge that turns "what did I do today?" into a filled-in Tempo
timesheet, plus an optional live timer and a Friday check that the week is
actually complete.

Built for one person on one Windows machine, against Jira Cloud and Tempo.

## Why it exists

The hours get worked; the logging doesn't happen. Not for lack of data — Jira
already knows what was touched — but for lack of a prompt while the day is
still fresh. Timelogger asks at 15:30, pre-filled, and takes about twenty
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
| `py -m timelogger` | Day window |
| `py -m timelogger --week` | Week overview |
| `py -m timelogger --timer AV-412` | Start the timer on an issue |

Automatic launch at 15:30 on weekdays, plus a catch-up at logon if the machine
was off, is installed with `py install.py` and removed with `py uninstall.py`.

## Tests

```
py -m unittest discover -s tests
```

Everything that can be tested without opening a window is. The pure logic —
duration parsing, week arithmetic, storage — has no I/O; the API clients take
their transport as an argument and are tested against recorded responses.

## Layout

```
timelogger/
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
[`docs/superpowers/specs/2026-08-17-timelogger-design.md`](docs/superpowers/specs/2026-08-17-timelogger-design.md).

## Status

Working: configuration, storage, week arithmetic, duration parsing, Jira and
Tempo clients, connection smoke test.

Not yet built: the windows themselves, the timer strip, and the Task Scheduler
installer.
