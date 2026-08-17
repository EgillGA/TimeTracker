"""What the day window shows and what it sends.

Pure functions over the day record. The window itself only lays these out and
wires up events, which is what keeps the untested tkinter surface thin.

Day records are treated as mutable and returned for chaining; the window holds
exactly one and writes it to disk after every change.
"""

from dataclasses import dataclass, field, replace
from datetime import date


@dataclass
class DayData:
    """Everything one day's window needs.

    Defined here rather than in ui_day so that the service which assembles it
    never has to import tkinter.

    `assigned` and `recent` stay separate rather than being merged: they are
    different kinds of thing. Assigned issues are work you own and appear
    under Projects; recent ones are work you merely touched, and appear under
    Suggestions. Merging them loses the distinction, and a row put back after
    being removed then lands in the wrong place.
    """

    day: date
    record: dict
    assigned: list = field(default_factory=list)
    recent: list = field(default_factory=list)
    internal: list = field(default_factory=list)
    target_seconds: int = 8 * 3600
    suggestion_count: int = 5
    running: dict = None
    banner: str = ""


@dataclass(frozen=True)
class Row:
    issue_key: str
    issue_id: int
    summary: str
    seconds: int = 0
    logged_seconds: int = 0
    running_seconds: int = 0
    is_running: bool = False
    from_timer: bool = False
    unconfirmed: bool = False
    submitted: bool = False
    has_pending: bool = False
    on_day: bool = False


def candidate_issues(assigned, recent):
    """The two Jira queries as one list, assigned first, no repeats.

    What you own is a better guess than what you merely touched, so it leads.
    """
    seen = set()
    combined = []
    for issue in list(assigned) + list(recent):
        key = issue["key"].upper()
        if key not in seen:
            seen.add(key)
            combined.append(issue)
    return combined


def _entry_for(record, issue_key, pending_only=False):
    """The row for an issue.

    `pending_only` skips rows already accepted by Tempo. An issue can hold two
    rows — one submitted, one still being worked on — and anything that writes
    must find the second, not the first.
    """
    for entry in record["entries"]:
        if entry["issue_key"].upper() != issue_key.upper():
            continue
        if pending_only and entry.get("submitted", False):
            continue
        return entry
    return None


def _row_from_entry(entry):
    from_timer = entry.get("source") == "timer"
    return Row(
        issue_key=entry["issue_key"],
        issue_id=entry.get("issue_id", 0),
        summary=entry.get("summary", ""),
        seconds=entry.get("seconds", 0),
        from_timer=from_timer,
        # Typed hours were confirmed by the act of typing them; only the
        # timer can produce time nobody vouched for.
        unconfirmed=from_timer and not entry.get("confirmed", True),
        submitted=entry.get("submitted", False),
        on_day=True,
    )


def tracked_rows(record, running=None):
    """Everything on today, one row per issue, in the order it was added.

    An issue can hold two entries — hours already in Tempo, and more hours
    still pending. They are one thing you worked on, so they share a row: the
    logged part shown as text, the pending part in a box that still takes
    input. Two rows for one issue reads like a bug.

    `running` is the live timer, if one is going. It appears as a row even
    when the issue is otherwise untouched, because time being counted right
    now is the most relevant thing on the screen — and a day total that
    contradicts the strip in the corner is worse than no total at all. Its
    seconds stay separate from the row's own: they are not in the record and
    cannot be submitted until the timer stops.
    """
    rows = {}
    order = []

    for entry in record["entries"]:
        key = entry["issue_key"].upper()
        if key not in rows:
            order.append(key)
            rows[key] = Row(
                issue_key=entry["issue_key"],
                issue_id=entry.get("issue_id", 0),
                summary=entry.get("summary", ""),
                on_day=True,
            )

        row = rows[key]
        seconds = entry.get("seconds", 0)
        submitted = entry.get("submitted", False)
        from_timer = entry.get("source") == "timer"

        rows[key] = replace(
            row,
            seconds=row.seconds + (0 if submitted else seconds),
            logged_seconds=row.logged_seconds + (seconds if submitted else 0),
            summary=row.summary or entry.get("summary", ""),
            from_timer=row.from_timer or from_timer,
            # Typed hours were confirmed by the act of typing them; only the
            # timer can produce time nobody vouched for.
            unconfirmed=row.unconfirmed or (
                from_timer and not entry.get("confirmed", True)
            ),
            submitted=row.submitted or submitted,
            has_pending=row.has_pending or not submitted,
        )

    if running:
        key = running["issue_key"].upper()
        if key in rows:
            rows[key] = replace(rows[key],
                                running_seconds=running["seconds"],
                                is_running=True)
        else:
            # Not otherwise on the day: put it at the top, since it is the one
            # thing on this list that is still happening.
            order.insert(0, key)
            rows[key] = Row(
                issue_key=running["issue_key"],
                issue_id=running.get("issue_id", 0),
                summary=running.get("summary", ""),
                running_seconds=running["seconds"],
                is_running=True,
                from_timer=True,
                on_day=True,
            )

    return [rows[key] for key in order]


def _offerable(record, issues, excluded_keys):
    """Issues worth offering: anything not already on today's list.

    Issues whose hours are already in Tempo stay off this list even though
    more time can still be added to them — their tracked row takes it
    directly, so offering them here too would show the same issue twice.
    """
    return [
        Row(issue_key=issue["key"], issue_id=issue["id"],
            summary=issue.get("summary", ""))
        for issue in issues
        if issue["key"].upper() not in excluded_keys
        and _entry_for(record, issue["key"]) is None
    ]


def _running_key(running):
    """The running issue is already shown in Tracked today, so it is never
    offered again — even though it has no entry in the record yet."""
    return {running["issue_key"].upper()} if running else set()


def project_rows(record, assigned, internal, running=None):
    """Work you own: every issue assigned to you, in any project.

    Internal issues are excluded because they have their own tab — the same
    issue in two places invites typing the same hour twice.
    """
    excluded = {issue["key"].upper() for issue in internal}
    return _offerable(record, assigned, excluded | _running_key(running))


def suggestion_rows(record, recent, assigned, internal, running=None):
    """Work you touched but do not own.

    Anything already under Projects is excluded, so the two sections never
    show the same issue and a removed row returns to exactly one of them.
    """
    excluded = {issue["key"].upper() for issue in internal}
    excluded |= {issue["key"].upper() for issue in assigned}
    return _offerable(record, recent, excluded | _running_key(running))


def internal_rows(record, internal):
    """Every internal issue, in project order, marked if already on the day."""
    rows = []
    for issue in internal:
        entry = _entry_for(record, issue["key"])
        if entry:
            rows.append(_row_from_entry(entry))
        else:
            rows.append(Row(issue_key=issue["key"], issue_id=issue["id"],
                            summary=issue.get("summary", "")))
    return rows


def set_hours(record, issue, seconds, source="manual", note=None):
    """Set the hours for an issue, adding the row if it is new.

    A row set to zero is kept rather than removed: deleting it mid-keystroke
    while someone clears a field to retype it would be hostile.
    """
    # Pending only: a row already accepted by Tempo cannot be edited, so more
    # hours on that issue become a new row that can actually be sent.
    entry = _entry_for(record, issue["key"], pending_only=True)
    if entry is None:
        record["entries"].append({
            "issue_key": issue["key"],
            "issue_id": issue.get("id", 0),
            "summary": issue.get("summary", ""),
            "seconds": int(seconds),
            "note": note or "",
            "source": source,
            "confirmed": True,
            "submitted": False,
            "tempo_worklog_id": None,
        })
        return record

    entry["seconds"] = int(seconds)
    if note is not None:
        entry["note"] = note
    return record


def remove_entry(record, issue_key):
    """Take a row off the day.

    A row already accepted by Tempo is left alone: its hours exist there, and
    removing the local row would hide real logged time while giving no way to
    unlog it. Those rows show no remove control in the window either.
    """
    entry = _entry_for(record, issue_key)
    if entry is not None and not entry.get("submitted", False):
        record["entries"].remove(entry)
    return record


def add_segment(record, piece):
    """Fold a finished timer run into the day.

    Time lands on the issue's pending row, or a new one if there isn't a
    pending row. That second case matters: if the issue's hours are already in
    Tempo, adding to that row would leave it marked submitted and the new time
    would never be sent anywhere.

    A row that holds any unvouched-for time stays flagged even when good time
    is added afterwards — the warning is about the part that needs checking.
    """
    entry = _entry_for(record, piece["issue_key"], pending_only=True)

    if entry is None:
        entry = {
            "issue_key": piece["issue_key"],
            "issue_id": piece.get("issue_id", 0),
            "summary": piece.get("summary", ""),
            "seconds": 0,
            "note": "",
            "source": "timer",
            "confirmed": True,
            "submitted": False,
            "tempo_worklog_id": None,
        }
        record["entries"].append(entry)

    entry["seconds"] += int(piece["seconds"])
    entry["source"] = "timer"
    entry["confirmed"] = entry.get("confirmed", True) and piece.get(
        "confirmed", True
    )

    record["segments"].append({
        "issue_key": piece["issue_key"],
        "start": piece["start"],
        "end": piece["end"],
        "confirmed": piece.get("confirmed", True),
    })
    return record


def total_seconds(record):
    return sum(entry.get("seconds", 0) for entry in record["entries"])


def unaccounted_seconds(record, target_seconds):
    return max(0, target_seconds - total_seconds(record))


LAST_MINUTE_OF_DAY = 24 * 3600 - 60


def fill_remaining(record, target_seconds):
    """Share the shortfall between the rows you added but left blank.

    Adding three issues and pressing Fill remaining is the fast path for a day
    spent across all three. Where nothing was left blank the remainder goes to
    the last row with hours, which covers "the rest was all that one thing".
    With no rows at all the day stays short: inventing an issue to hang the
    hours on would be worse than an honest gap.
    """
    shortfall = unaccounted_seconds(record, target_seconds)
    if not shortfall:
        return record

    blank = [
        entry for entry in record["entries"]
        if entry.get("seconds", 0) == 0 and not entry.get("submitted", False)
    ]
    if blank:
        _share_between(shortfall, blank)
        return record

    for entry in reversed(record["entries"]):
        # Never grow a row already in Tempo — that would log the extra twice.
        if entry.get("seconds", 0) > 0 and not entry.get("submitted", False):
            entry["seconds"] += shortfall
            break
    return record


def _share_between(seconds, entries):
    """Divide seconds as evenly as whole seconds allow, losing none.

    The remainder goes one second at a time to the earliest rows rather than
    being rounded away, so the shares always add back up to the total.
    """
    share, remainder = divmod(seconds, len(entries))
    for index, entry in enumerate(entries):
        entry["seconds"] = share + (1 if index < remainder else 0)


def schedule(record, day_start_seconds):
    """Lay the day's rows end to end from the start of the working day.

    Returns `{issue_key: seconds from midnight}` for every row with hours.
    Submitted rows keep their slot so a row added afterwards is not scheduled
    on top of time already in Tempo. A day long enough to run past midnight
    is clamped: Tempo rejects a start time of 25:00, and a wrong-but-valid
    time can be corrected later while a rejected worklog cannot.
    """
    starts = {}
    cursor = day_start_seconds

    for entry in record["entries"]:
        seconds = entry.get("seconds", 0)
        if seconds <= 0:
            continue
        starts[entry["issue_key"]] = min(cursor, LAST_MINUTE_OF_DAY)
        cursor += seconds

    return starts


def entries_to_submit(record):
    """Rows with hours that Tempo has not already accepted."""
    return [
        entry for entry in record["entries"]
        if entry.get("seconds", 0) > 0 and not entry.get("submitted", False)
    ]


def mark_submitted(record, issue_key, worklog_id):
    """Record that Tempo accepted a row, so it is never sent again."""
    entry = _entry_for(record, issue_key, pending_only=True)
    if entry is not None:
        entry["submitted"] = True
        entry["tempo_worklog_id"] = worklog_id
    return record
