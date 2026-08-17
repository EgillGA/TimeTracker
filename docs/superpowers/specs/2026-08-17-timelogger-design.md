# Timelogger — Design Spec

Date: 2026-08-17
Status: Approved for planning
Author: Egill Grétar Andrason (with Claude)

## 1. Problem

Hours worked are not reliably recorded in Tempo. The failure is not a lack of
data — Jira already knows what was worked on — but a lack of a prompt at a
moment when the day is still fresh. Time is reconstructed days later, or not at
all, and the week is discovered to be short only when it is too late to
remember what filled it.

Timelogger addresses this in two ways, either of which works alone:

- **Push.** At 15:30 on weekdays a window appears, pre-filled with the issues
  worked on, needing only numbers and a click.
- **Pull.** An optional live timer records work as it happens, so the 15:30
  window is a review rather than an act of memory.

Fridays add a week view that makes a short week visible while it can still be
fixed.

## 2. Goals

1. Filling in a normal day takes under 30 seconds and no thinking about *what*
   was worked on.
2. A day is never silently missed — if the machine was off at 15:30, the prompt
   arrives at next logon.
3. A short week is impossible to overlook on Friday.
4. The live timer is optional; every feature works without ever starting it.
5. Zero-maintenance installation: no pip, no virtualenv, no package that breaks
   on a Python upgrade.

## 3. Non-goals

Explicitly excluded, with reasons, so they are not re-litigated during
implementation:

| Excluded | Why |
|---|---|
| Idle / screen-lock auto-pause | A timer that pauses itself through a long meeting produces confidently wrong worklogs. The hourly check-in covers the same ground honestly. |
| Reading required hours from Tempo's work schedule | Flat 8 h/day is correct for nearly every day. Holidays will show as a gap and be ignored. Revisit only if that proves annoying. |
| Editing or deleting existing Tempo worklogs | Read and create only. Corrections happen in Tempo's own UI, which already does this well. |
| Multi-user support, other trackers, mobile | Single user, single machine. |
| Auto-starting the timer based on activity | Guessing which issue someone is on is worse than asking. |

## 4. Environment and constraints

- Windows 11, single user machine.
- Python 3.13 present, launched via the `py` launcher. `pythonw.exe` for
  windowless runs.
- **Standard library only.** `tkinter` for UI, `urllib.request` for HTTP,
  `tomllib` for config, `ctypes` for Windows work-area geometry, and JSON
  files for local state. No third-party packages, and no database — the data
  is one small file per day and must stay readable and fixable by hand.
- Jira Cloud at `https://apt-oz.atlassian.net`.
- Tempo Cloud, integrated into that Jira site.
- Corporate network; requests may traverse a proxy and may fail.

## 5. Architecture

```
Timelogger/
├─ timelogger/
│  ├─ __main__.py      entry point; mode selection
│  ├─ config.py        config.toml + credentials.toml loading, validation
│  ├─ jira.py          JQL search, issue key ↔ id resolution
│  ├─ tempo.py         read worklogs, create worklogs
│  ├─ store.py         local day record, drafts, timer state (crash-safe)
│  ├─ week.py          pure logic: targets, totals, gaps, aggregation
│  ├─ duration.py      pure logic: parsing and formatting durations
│  ├─ theme.py         design tokens (colours, fonts, spacing, metrics)
│  ├─ ui_strip.py      the always-on-top timer strip
│  ├─ ui_day.py        the big day window
│  └─ ui_week.py       the Friday week overview
├─ tests/
├─ docs/superpowers/specs/
├─ config.toml               settings (safe to read, safe to share)
├─ credentials.toml          API tokens — user-created, never committed
├─ .gitignore                excludes credentials.toml and state/
└─ run_timelogger.vbs        silent launcher for Task Scheduler
```

Local state lives in `%APPDATA%\Timelogger\` — not in the source folder — so
the code directory stays clean and disposable.

### Module boundaries

The rule: **pure logic knows nothing about tkinter or HTTP.**

- `week.py`, `duration.py` are pure functions over plain data. Fully unit
  tested; this is where the arithmetic that must be right lives.
- `jira.py`, `tempo.py` are the only modules that make network calls. Each
  exposes a small interface returning plain dicts, so tests substitute
  recorded fixtures.
- `store.py` is the only module that touches disk.
- The `ui_*` modules are thin: layout, event wiring, and calls into the above.
  They hold no business rules and are verified by running them.

This split exists so that a bug in the hours arithmetic can be reproduced in a
unit test rather than by clicking through a window at 15:30.

## 6. Data model

### Local day record

One JSON file per day, `%APPDATA%\Timelogger\days\2026-08-17.json`:

```json
{
  "date": "2026-08-17",
  "submitted_at": null,
  "entries": [
    {
      "issue_key": "AV-412",
      "issue_id": 10412,
      "summary": "Fix altimeter calculation",
      "seconds": 5400,
      "note": "",
      "source": "timer",
      "confirmed": true,
      "submitted": false,
      "tempo_worklog_id": null
    }
  ],
  "segments": [
    {"issue_key": "AV-412", "start": "2026-08-17T09:15:03",
     "end": "2026-08-17T10:45:03", "confirmed": true}
  ]
}
```

`source` is `"timer"` or `"manual"`. `segments` is the raw audit trail of timer
runs; `entries` is the per-issue aggregate that gets submitted. Keeping both
means a suspicious total can always be traced back to when it was recorded.

`submitted` is per-entry, not per-day, so a partial submission failure leaves
the successful rows alone and retries only what failed.

### Live timer state

`%APPDATA%\Timelogger\timer.json`, flushed every 30 seconds while running:

```json
{
  "issue_key": "AV-412",
  "issue_id": 10412,
  "summary": "Fix altimeter calculation",
  "started_at": "2026-08-17T09:15:03",
  "last_heartbeat": "2026-08-17T10:44:33",
  "last_confirmed_at": "2026-08-17T10:15:03",
  "paused_total_seconds": 0
}
```

On launch, if this file exists the app offers recovery: *"A timer for AV-412
was running when Timelogger last closed, from 09:15 to 10:44. Keep that time?"*
The heartbeat, not the current clock, bounds the recovered segment — a machine
that was asleep for four hours must not award itself four hours.

## 7. External APIs

Both endpoint families below are the current documented ones but **must be
verified against the live site during the first implementation step**, before
any UI work. A connectivity smoke script that authenticates, runs one search,
and reads one worklog is the first deliverable.

### Jira Cloud

- Base: `https://apt-oz.atlassian.net`
- Auth: HTTP Basic — Atlassian account email plus an API token from
  <https://id.atlassian.com/manage-profile/security/api-tokens>
- Search: `POST /rest/api/3/search/jql` with `jql`, `fields`, `maxResults`,
  and `nextPageToken` cursor paging. If that endpoint is unavailable, fall
  back to `GET /rest/api/2/search`. The client detects this once and caches
  which worked.
- `GET /rest/api/3/myself` — resolves `accountId`, required by Tempo.

Candidate issue query, the union of two searches, deduplicated by key:

```
assignee = currentUser() AND statusCategory != Done ORDER BY updated DESC
```
```
(assignee WAS currentUser() OR worklogAuthor = currentUser())
  AND updated >= -7d ORDER BY updated DESC
```

A third query backs the Internal tab. It is deliberately **not** filtered by
assignee — internal issues are typically unassigned or owned by someone else,
which is precisely why this work never appears in the normal list and never
gets logged:

```
project = AI AND statusCategory != Done ORDER BY key ASC
```

All three JQL strings live in `config.toml` so they can be tuned without
editing code. Results are capped at 50 per query. The internal list changes
rarely, so it is fetched once per launch and cached in memory; if the fetch
fails, the last successful list is read from
`%APPDATA%\Timelogger\internal_cache.json` and shown with a staleness note,
because losing access to the admin issues is the difference between logging a
day and abandoning it.

### Tempo Cloud

- Base: `https://api.tempo.io/4/`
- Auth: `Authorization: Bearer <token>`, token generated in Jira under
  Apps → Tempo → Settings → API integration.
- `GET /worklogs/user/{accountId}?from=&to=` — existing worklogs for the week.
- `POST /worklogs` — create, with `issueId` (numeric Jira id, not the key),
  `timeSpentSeconds`, `startDate`, `startTime`, `description`,
  `authorAccountId`.

Because Tempo v4 takes a numeric issue id, `jira.py` maintains a key → id map
cached in `%APPDATA%\Timelogger\issue_ids.json`, populated from search results
and filled on demand for manually typed keys.

## 8. Configuration

`config.toml` — created with sensible defaults on first run:

```toml
[jira]
site  = "https://apt-oz.atlassian.net"
email = "egill@aptoz.is"

[schedule]
hours_per_day  = 8.0
prompt_time    = "15:30"
week_view_day  = "friday"

[timer]
checkin_minutes  = 60
heartbeat_seconds = 30

[ui]
theme = "dark"          # "dark" or "light"

[internal]
project = "AI"

[jql]
assigned = "assignee = currentUser() AND statusCategory != Done ORDER BY updated DESC"
recent   = "(assignee WAS currentUser() OR worklogAuthor = currentUser()) AND updated >= -7d ORDER BY updated DESC"
internal = "project = AI AND statusCategory != Done ORDER BY key ASC"
```

`credentials.toml` — **created by the user, listed in `.gitignore`, never
displayed, never logged, never sent anywhere but the two APIs above:**

```toml
jira_api_token  = ""
tempo_api_token = ""
```

If either token is missing or empty, the app opens a setup window with the two
links and a button that opens the file in Notepad. It does not ask for tokens
through any other channel.

## 9. Visual design

The brief is *easy to use and visually good*. Concretely, that means: no
default grey tkinter widgets, no dialog boxes for routine actions, generous
spacing, one accent colour used consistently to mean "this is the thing you
came here to do", and numbers that do not jitter as they count.

### Tokens (`theme.py`)

All colours and metrics are named constants in one module. No literal colours
anywhere else in the codebase.

**Dark (default)**

| Token | Value | Use |
|---|---|---|
| `bg` | `#16181D` | window background |
| `surface` | `#1E2127` | rows, panels |
| `surface_hi` | `#262A32` | hover / focused row |
| `border` | `#2E333D` | hairlines |
| `text` | `#EDEFF2` | primary text |
| `text_muted` | `#8D96A5` | issue summaries, secondary labels |
| `accent` | `#3FB950` | running timer, submit button, on-target |
| `warn` | `#D29922` | unconfirmed segments |
| `danger` | `#F85149` | missing hours, failed submissions |

**Light** — the same token names remapped (`bg #FAFBFC`, `surface #FFFFFF`,
`text #1B1F24`, `text_muted #656D76`, borders `#D8DEE4`, same three status
colours). Because every widget reads tokens, switching themes is a config
change, not a rewrite.

### Typography

- UI text: **Segoe UI** 10 pt; issue keys Segoe UI Semibold 10 pt; summaries
  9.5 pt in `text_muted`.
- **All numbers — elapsed time, hours, totals — in Cascadia Mono 10 pt**
  (fallback Consolas). Proportional digits make a live counter visibly wobble;
  monospaced digits sit still. This is not decoration, it is the difference
  between a timer that looks finished and one that looks broken.

### Spacing and metrics

8 px base unit. Row height 44 px, comfortably clickable. Window padding 20 px.
Corner radius is unavailable in plain tkinter — borderless windows use flat
edges with a 1 px `border` outline rather than faking rounding badly.

### Screen: the strip

Borderless, always on top, no taskbar button. Parked in the bottom-right of the
**work area** — obtained from `SystemParametersInfoW(SPI_GETWORKAREA)` via
`ctypes`, so it sits above the taskbar at any taskbar height, position, or DPI
scaling — with a 12 px margin. Draggable; the chosen position persists.

```
resting        260 × 36
┌──────────────────────────────────┐
│  ⏺  AV-412        1:02:47        │     accent dot, pulsing 1 s
└──────────────────────────────────┘

hover          300 × 44
┌────────────────────────────────────────┐
│  ⏺  AV-412  Fix altimeter…             │
│     1:02:47          ⏸    ⏹    ⇱       │
└────────────────────────────────────────┘
                     pause stop open
```

Paused state: dot and time switch to `text_muted`, dot stops pulsing, ⏸
becomes ▶. The state must be unmistakable at a glance from across the desk —
this is the single most-seen element in the whole application.

### Screen: the hourly check-in

The strip expands in place. It does **not** steal focus, does not appear as a
dialog, and does not block typing in whatever is being worked on.

```
320 × 96
┌────────────────────────────────────────────┐
│  Still on AV-412?                          │
│  Fix altimeter calculation                 │
│  running 1:00:00, since 09:15              │
│                                            │
│  [ Keep going ]   [ Switch ]   [ Stop ]    │
└────────────────────────────────────────────┘
```

If ignored for 5 minutes it collapses back to the resting strip and the segment
from that point on is flagged `confirmed: false`. Unconfirmed time appears
amber in the day window with the hint *"timer ran unattended — check this"*.
The timer is never stopped automatically; the user is told, not overruled.

### Screen: the day window (720 × 560)

```
┌ Timelogger — Monday 17 August ─────────────────────────────┐
│                                                            │
│   Today          6.5 of 8.0 hours          ▁▁▁▁▁▁▁▁▁░░░    │
│                                                            │
│   ┃ My work ┃   Internal                                   │
│   ━━━━━━━━━━━────────────────────────────────────────────  │
│   ── Tracked today ──────────────────────────────────────  │
│   AV-412   Fix altimeter calculation      [ 3.0 ]  ⏱      │
│   AV-388   CCL review for MOD-2291        [ 2.5 ]  ⏱  ⚠   │
│   AI-1     Meetings                       [ 1.0 ]         │
│                                                            │
│   ── Suggestions ────────────────────────────────────────  │
│   AV-455   Wiring diagram update          [     ]  ▶      │
│   AV-390   Update EWIS report             [     ]  ▶      │
│                                                            │
│   + add issue by key…                                      │
│                                                            │
│   1.5 h unaccounted        [ Fill remaining ]              │
│                                                            │
│                       [ Close ]      [ Submit 6.5 h ]      │
└────────────────────────────────────────────────────────────┘
```

Switching to **Internal** swaps only the middle list. The header, the total,
the unaccounted line and the buttons stay exactly where they are, so the
day's state never leaves the screen while hunting for an admin issue:

```
│   My work   ┃ Internal ┃                                   │
│   ──────────━━━━━━━━━━━──────────────────────────────────  │
│   AI-1     Meetings                       [     ]  +  ▶   │
│   AI-2     Administration                 [ 1.0 ]  ✓      │
│   AI-7     Training and courses           [     ]  +  ▶   │
│   AI-12    Tooling and IT                 [     ]  +  ▶   │
│   AI-15    Quality management system      [     ]  +  ▶   │
```

- The progress bar is the emotional centre: `accent` when at or over target,
  `text_muted` while under, never red — the daily view informs, the Friday
  view judges.
- `⏱` marks hours that came from the timer, `⚠` marks unconfirmed time.
- `▶` on any suggestion or internal row starts the timer on that issue
  immediately, closing the window. This is the fast path into tracking and
  should need exactly one click from a cold start.
- On the Internal tab, `+` adds the issue to today with an empty hours box and
  jumps straight back to **My work** with that box focused — one click, then
  type the number. Typing directly into an internal row's box does the same
  without leaving the tab, for adding several at once. An issue already on
  today's list shows `✓` and its current hours instead of `+`, so the same
  thing is never added twice.
- Tab state is not remembered between launches. The window always opens on
  **My work**, because that is what the 15:30 prompt is for; Internal is a
  deliberate detour, not a place to get stranded.
- **Fill remaining** distributes the shortfall to the last-touched issue —
  one click for the common case of "the rest was all that one thing".
- The Submit button carries the number, so the amount is confirmed by reading
  the button rather than by trusting a total elsewhere on screen.

### Screen: the week window (760 × 520)

```
┌ Timelogger — week of 17 August ────────────────────────────┐
│                                                            │
│   This week          33.5 of 40.0 hours                    │
│                                                            │
│   Mon 17   ████████████████████   8.0                      │
│   Tue 18   ████████████████████   8.0                      │
│   Wed 19   ██████████░░░░░░░░░░   4.0    4.0 h missing  ▸  │
│   Thu 20   ████████████████████   8.0                      │
│   Fri 21   ██████████████░░░░░░   5.5    2.5 h missing  ▸  │
│                                                            │
│   ▸ Wednesday 19 August — 4.0 of 8.0                       │
│     AV-412  Fix altimeter calculation     4.0 logged       │
│     AV-388  CCL review                    [     ]          │
│     + add issue by key…                                    │
│                     [ Add 0.0 h to Wednesday ]             │
│                                                            │
│                                          [ Close ]         │
└────────────────────────────────────────────────────────────┘
```

Short days show their bar and remainder in `danger`; complete days in `accent`.
Clicking `▸` expands that day inline for back-dated entry — no second window,
no navigation away and back. The suggestions shown for a past day are the
issues that day's Jira activity touched, not today's. The expanded day carries
the same **My work / Internal** tabs as the day window — a forgotten Wednesday
is at least as likely to have been meetings and admin as project work.

Hours already in Tempo are shown as read-only text — `4.0 logged`, never in an
editable box — and only empty boxes accept input. The button reads *Add N h*
rather than *Submit*, and N counts only the new hours. Back-dated entry is
where double-posting is most likely and least likely to be noticed; the
interface makes it structurally impossible rather than merely discouraged.

### Ease-of-use rules, binding on implementation

1. **Keyboard first.** Tab moves between hours fields, Enter submits, Escape
   closes, Ctrl+Enter submits from anywhere, Ctrl+Tab switches between My work
   and Internal. The day window can be completed without touching the mouse.
2. **Tolerant input.** `1,5` `1.5` `1:30` `90m` `1h30` all mean 90 minutes.
   Parsing lives in `duration.py` and is exhaustively unit tested. Invalid
   input turns the field border `danger` and blocks submit; it never throws
   away what was typed.
3. **No modal dialogs** for anything routine. Confirmation and error text
   appears inline, in the window, next to the thing it concerns.
4. **Nothing is ever lost.** Every keystroke in an hours field writes to the
   day record within a second.
5. **One idea per screen.** The strip tracks. The day window fills in a day.
   The week window fixes a week. None of them grows a settings panel.

## 10. Behaviour

### Launch modes

`__main__.py` selects on flags, defaulting by context:

| Invocation | Behaviour |
|---|---|
| `--day` | Day window |
| `--week` | Week window |
| `--timer AV-412` | Start timer directly |
| `--scheduled` | Day window, or week window if today is Friday. Exits silently if today is already submitted. |
| `--catchup` | As `--scheduled`, but exits silently unless today's prompt was missed |
| no flag | Day window (the manual-open path) |

Only one instance may run. A lock file in `%APPDATA%` holding the process id
guards this; a second launch raises and focuses the existing window rather
than opening a duplicate.

### Scheduling

Two Windows Task Scheduler tasks, created by `install.py` for the current user,
with no admin rights required, both running `run_timelogger.vbs` so no console
window flashes:

1. **Timelogger Daily** — 15:30, Mon–Fri, `--scheduled`. *Run task as soon as
   possible after a scheduled start is missed* is enabled.
2. **Timelogger Catchup** — at logon, `--catchup`, delayed 2 minutes.

`install.py` also prints how to disable both, and `uninstall.py` removes them.
An automation that cannot be easily turned off will be resented and killed
crudely.

### Submission

On Submit, for each entry with hours and `submitted: false`:

1. Resolve issue key → numeric id, from cache or Jira.
2. `POST /worklogs`.
3. On success, record the returned worklog id and mark `submitted: true`.
4. On failure, leave the row, mark it `danger`, show the API's message inline.

Rows are submitted independently. A partial failure never resubmits what
already succeeded, and pressing Submit again retries only the failures — the
worklog ids make double-posting impossible.

### Week aggregation

`week.py` merges two sources for Monday–Friday of the current week: worklogs
read from Tempo, and unsubmitted local entries. Tempo is authoritative for
submitted time; local entries are shown as pending and included in the total
with a distinct marker. Hours logged by other means — Tempo's own UI, a
colleague logging on your behalf — therefore appear correctly, because Tempo
is queried rather than assumed.

## 11. Error handling

| Failure | Response |
|---|---|
| No network / proxy blocks | Window still opens with local data and a banner: *"Can't reach Jira — showing what's saved locally."* Manual entry works. Submit is disabled with the reason shown. |
| 401 / 403 | Plain sentence naming which token failed, with the link to regenerate it, and a button opening `credentials.toml`. Never a stack trace. |
| Tempo rejects a worklog | The API's own message inline on that row. Common causes — closed period, missing required attribute — are recognised and rephrased in plain language. |
| Unknown issue key typed | Field goes `danger`, text stays, message *"No issue AV-999 — check the key."* |
| Internal project fetch fails | The cached list from the last successful fetch is shown with a *"last updated <date>"* note. Entry still works — the issue keys are what matter and they don't change. |
| Internal project misconfigured or inaccessible | Tab shows *"Can't read project AI — check `[internal] project` in config.toml."* The rest of the window is unaffected. |
| Corrupt local state file | Moved aside to `*.corrupt-<timestamp>`, a fresh one started, banner explaining what happened and where the old file went. Never silently deleted. |
| Crash while timing | Next launch offers recovery bounded by the last heartbeat. |
| Timer running at 15:30 | Day window shows the live segment as a running row; it keeps running unless stopped. |

Uncaught exceptions are written to `%APPDATA%\Timelogger\logs\error.log` with a
timestamp, and shown as a short message with the log path — a scheduled task
that dies invisibly is indistinguishable from one that was never installed.
Logs redact anything token-shaped.

## 12. Testing

Test-driven, in this order. The rule: everything that can be tested without a
window, is.

**Unit — pure logic, no I/O.** `duration.py` parsing and formatting across the
full accepted grammar plus malformed input. `week.py` totals, gap detection,
target arithmetic, week boundaries across a month end and a year end, merging
Tempo and local entries without double counting.

**Unit — with fakes.** `store.py` against a temp directory: write, reload,
corrupt-file recovery, heartbeat-bounded timer recovery, concurrent write
safety. `jira.py` and `tempo.py` against recorded JSON fixtures via an injected
transport: pagination, key→id resolution, 401, 500, malformed payloads,
timeouts, internal-list caching and stale-cache fallback, and de-duplication
when an internal issue is also assigned to the user and would otherwise appear
in both tabs.

**Integration — one live smoke test**, run manually, not in the normal suite:
authenticate, one search, one worklog read, and a worklog write to a
designated scratch issue. This is the first thing built, because it is the
step most likely to invalidate assumptions in section 7.

**Manual, before calling it done.** A checklist covering: strip parks correctly
at 100 % / 150 % scaling, on a second monitor, and after disconnecting one;
strip survives RDP and lock/unlock; hourly check-in does not steal focus from
a document being typed in; day window completes by keyboard alone; both themes
legible.

## 13. Build order

1. Live smoke test against Jira and Tempo — confirm section 7 before anything
   is built on it.
2. `duration.py`, `week.py`, `store.py` with tests. All the arithmetic, none
   of the UI.
3. `jira.py`, `tempo.py` with fixture tests.
4. `theme.py` and the day window, including both tabs; manual entry and
   submission working end to end. **At this point the tool is already useful**
   — the 15:30 prompt plus manual entry solves the original problem, and
   everything after is improvement.
5. Task Scheduler install, catch-up, single-instance lock.
6. Week window.
7. Timer strip, hourly check-in, crash recovery.

Each step ends with a working program. If work stops after step 4 or 6, what
exists still earns its keep.

## 14. Open items

- **Tempo required attributes.** Some Tempo configurations require an account
  or work attribute on every worklog. Whether this site does is unknown until
  the step 1 smoke test. If it does, the day window gains one dropdown per row
  and the spec is amended.
- **Git.** This directory is not a repository. Worth initialising before
  implementation so the build order above is reviewable step by step —
  to be confirmed.
- **Theme default.** Specified as dark. Both palettes are defined; if light
  reads better in the office it is a one-line config change.

## 15. Security

- Tokens live only in `credentials.toml`, which is git-ignored and is created
  by the user. They are never printed, logged, included in error messages, or
  transmitted anywhere other than `apt-oz.atlassian.net` and `api.tempo.io`
  over HTTPS.
- No telemetry, no analytics, no network calls beyond those two hosts.
- All local state is confined to `%APPDATA%\Timelogger\`.
