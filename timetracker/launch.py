"""Whether the window should appear, and which one.

One scheduled task fires twice: on weekday afternoons, and again at logon in
case the machine was off. Both firings ask this the same question, so the
rules live in one place rather than being split across two task definitions
that could drift apart.

The bias is deliberate: silence is the safe failure. A window that never
appears is a tool you stop relying on; a window that appears every time you
unlock your laptop is a tool you uninstall.
"""

from timetracker.duration import parse_clock

DAY = "day"
WEEK = "week"
NOTHING = "nothing"

DEFAULT_PROMPT_SECONDS = 15 * 3600 + 30 * 60
SATURDAY = 6

WEEKDAY_NUMBERS = {
    "monday": 1, "tuesday": 2, "wednesday": 3, "thursday": 4,
    "friday": 5, "saturday": 6, "sunday": 7,
}


def has_submitted(record):
    """Has any of today's work reached Tempo?

    Typed hours do not count — they are exactly what still needs dealing with.
    """
    return any(entry.get("submitted", False) for entry in record["entries"])


def is_settled(record):
    """Is there nothing left to do with today?

    Something reached Tempo and nothing is still waiting. A day where some
    rows failed, or where more work happened after submitting, is not settled
    and is exactly the case the prompt exists for.
    """
    if not has_submitted(record):
        return False

    return not any(
        entry.get("seconds", 0) > 0 and not entry.get("submitted", False)
        for entry in record["entries"]
    )


def decide(now, record, config):
    """Return DAY, WEEK or NOTHING for a firing at `now`."""
    if now.isoweekday() >= SATURDAY:
        return NOTHING

    # The week view is about the other four days, so it is still worth
    # showing on a Friday whose own hours are already in. It can also want
    # its own time — Friday afternoons empty out earlier than the rest of
    # the week — so it is checked against week_prompt_time, not prompt_time.
    is_week_day = now.isoweekday() == WEEKDAY_NUMBERS.get(
        str(config.week_view_day).lower()
    )
    prompt_time = config.week_prompt_time if is_week_day else config.prompt_time
    prompt = parse_clock(prompt_time, DEFAULT_PROMPT_SECONDS)

    seconds_into_day = now.hour * 3600 + now.minute * 60 + now.second
    if seconds_into_day < prompt:
        return NOTHING

    if is_week_day:
        return WEEK

    return NOTHING if is_settled(record) else DAY
