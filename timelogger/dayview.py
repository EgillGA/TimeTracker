"""What the day window shows and what it sends.

Pure functions over the day record. The window itself only lays these out and
wires up events, which is what keeps the untested tkinter surface thin.

Day records are treated as mutable and returned for chaining; the window holds
exactly one and writes it to disk after every change.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Row:
    issue_key: str
    issue_id: int
    summary: str
    seconds: int = 0
    from_timer: bool = False
    unconfirmed: bool = False
    submitted: bool = False
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


def _entry_for(record, issue_key):
    for entry in record["entries"]:
        if entry["issue_key"].upper() == issue_key.upper():
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


def tracked_rows(record):
    """Everything already on today, in the order it was added."""
    return [_row_from_entry(entry) for entry in record["entries"]]


def suggestion_rows(record, candidates, internal):
    """Issues worth offering that are not already on the day.

    Internal issues are excluded here because they have their own tab — the
    same issue in both places invites typing the same hour twice.
    """
    internal_keys = {issue["key"].upper() for issue in internal}
    return [
        Row(issue_key=issue["key"], issue_id=issue["id"],
            summary=issue.get("summary", ""))
        for issue in candidates
        if issue["key"].upper() not in internal_keys
        and _entry_for(record, issue["key"]) is None
    ]


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
    entry = _entry_for(record, issue["key"])
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


def total_seconds(record):
    return sum(entry.get("seconds", 0) for entry in record["entries"])


def unaccounted_seconds(record, target_seconds):
    return max(0, target_seconds - total_seconds(record))


def fill_remaining(record, target_seconds):
    """Give the shortfall to the last issue that has hours.

    The common case is "the rest of the day was all that one thing". When
    there is no such row the day is left short: inventing an issue to hang
    the hours on would be worse than an honest gap.
    """
    shortfall = unaccounted_seconds(record, target_seconds)
    if not shortfall:
        return record

    for entry in reversed(record["entries"]):
        # Never grow a row already in Tempo — that would log the extra twice.
        if entry.get("seconds", 0) > 0 and not entry.get("submitted", False):
            entry["seconds"] += shortfall
            break
    return record


def entries_to_submit(record):
    """Rows with hours that Tempo has not already accepted."""
    return [
        entry for entry in record["entries"]
        if entry.get("seconds", 0) > 0 and not entry.get("submitted", False)
    ]


def mark_submitted(record, issue_key, worklog_id):
    """Record that Tempo accepted a row, so it is never sent again."""
    entry = _entry_for(record, issue_key)
    if entry is not None:
        entry["submitted"] = True
        entry["tempo_worklog_id"] = worklog_id
    return record
