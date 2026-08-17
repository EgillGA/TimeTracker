"""The running timer's state.

Plain dicts rather than a class, because this state is written to disk every
thirty seconds and read back after a crash; keeping it as the same shape in
memory and on disk means there is no conversion step to get wrong.

Every function takes `now` rather than reading the clock, so the arithmetic
can be tested at any hour of any day without waiting for one.
"""

from datetime import datetime, timedelta

# How late an answer to the hourly check-in still counts. Answering a minute
# after the prompt should not taint an hour of honest work.
CONFIRMATION_GRACE_SECONDS = 5 * 60


def _read(text):
    return datetime.fromisoformat(text) if text else None


def start(issue, now):
    return {
        "issue_key": issue["key"],
        "issue_id": issue.get("id", 0),
        "summary": issue.get("summary", ""),
        "started_at": now.isoformat(),
        "last_heartbeat": now.isoformat(),
        # Starting a timer is itself a statement of what you are doing, so it
        # counts as the first confirmation.
        "last_confirmed_at": now.isoformat(),
        "paused_total_seconds": 0,
        "paused_at": None,
    }


def is_paused(state):
    return state.get("paused_at") is not None


def elapsed_seconds(state, now):
    """Seconds of work so far, excluding any time spent paused."""
    started = _read(state["started_at"])
    end = _read(state["paused_at"]) if is_paused(state) else now

    worked = (end - started).total_seconds() - state.get("paused_total_seconds", 0)
    # A clock that jumps backwards must not invent negative work.
    return max(0, int(worked))


def pause(state, now):
    if is_paused(state):
        return state

    paused = dict(state)
    paused["paused_at"] = now.isoformat()
    return paused


def resume(state, now):
    if not is_paused(state):
        return state

    resumed = dict(state)
    away = (now - _read(state["paused_at"])).total_seconds()
    resumed["paused_total_seconds"] = (
        state.get("paused_total_seconds", 0) + max(0, int(away))
    )
    resumed["paused_at"] = None
    return resumed


def heartbeat(state, now):
    """Record that the timer was demonstrably alive at this moment.

    Recovery after a crash is bounded by this, never by the wall clock, so a
    machine that slept through lunch cannot bill for it.
    """
    beating = dict(state)
    beating["last_heartbeat"] = now.isoformat()
    return beating


def confirm(state, now):
    confirmed = dict(state)
    confirmed["last_confirmed_at"] = now.isoformat()
    return confirmed


def needs_checkin(state, now, checkin_minutes):
    """Is it time to ask whether this is still what you are doing?

    A paused timer is never asked — you have already said you stopped.
    """
    if is_paused(state):
        return False

    since = now - _read(state.get("last_confirmed_at") or state["started_at"])
    return since >= timedelta(minutes=checkin_minutes)


def is_confirmed(state, now, checkin_minutes):
    """Has this run been vouched for recently enough to trust?"""
    since = now - _read(state.get("last_confirmed_at") or state["started_at"])
    allowed = timedelta(minutes=checkin_minutes,
                        seconds=CONFIRMATION_GRACE_SECONDS)
    return since <= allowed


def segment(state, now, checkin_minutes):
    """The finished piece of work, ready to be added to the day."""
    return {
        "issue_key": state["issue_key"],
        "issue_id": state.get("issue_id", 0),
        "summary": state.get("summary", ""),
        "seconds": elapsed_seconds(state, now),
        "start": state["started_at"],
        "end": now.isoformat(),
        "confirmed": is_confirmed(state, now, checkin_minutes),
    }
