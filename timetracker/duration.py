"""Turning what a human typed into a number of seconds, and back again.

Pure functions, no I/O. Every wrong answer here becomes a wrong worklog in
Tempo, so the rule is: understand the common forms, and refuse everything else
loudly rather than guess.
"""

import re

MAX_SECONDS_PER_ENTRY = 24 * 3600

_CLOCK = re.compile(r"^(\d+):(\d{1,2})$")
_BARE = re.compile(r"^(\d+(?:\.\d+)?)$")
_SUFFIXED = re.compile(
    r"^(?:(\d+(?:\.\d+)?)\s*h)?\s*(?:(\d+(?:\.\d+)?)\s*m?)?$"
)


class InvalidDuration(ValueError):
    """Raised when input cannot be read as a duration.

    The message is shown directly to the user, so it names their text.
    """

    def __init__(self, text):
        super().__init__(
            f"Can't read {text.strip()!r} as an amount of time. "
            f"Try 1.5, 1:30, 90m or 1h30."
        )
        self.text = text


def parse_hours(text):
    """Read a typed duration and return whole seconds.

    Accepts `1,5`, `1.5`, `1:30`, `90m`, `1h30`, `1h 30m`, `2h`, `45m` and a
    bare number meaning hours. Raises InvalidDuration for anything else.
    """
    cleaned = text.strip().lower().replace(",", ".")
    if not cleaned:
        raise InvalidDuration(text)

    seconds = _parse_cleaned(cleaned, text)

    if seconds > MAX_SECONDS_PER_ENTRY:
        raise InvalidDuration(text)
    return seconds


def _parse_cleaned(cleaned, original):
    clock = _CLOCK.match(cleaned)
    if clock:
        hours, minutes = int(clock.group(1)), int(clock.group(2))
        if minutes >= 60:
            raise InvalidDuration(original)
        return hours * 3600 + minutes * 60

    # Only treat digits as minutes when a unit suffix says so; a bare "45"
    # means 45 hours (and is then rejected as impossible), never 45 minutes.
    if "h" in cleaned or "m" in cleaned:
        suffixed = _SUFFIXED.match(cleaned)
        if suffixed and any(suffixed.groups()):
            hours = float(suffixed.group(1) or 0)
            minutes = float(suffixed.group(2) or 0)
            return round(hours * 3600 + minutes * 60)
        raise InvalidDuration(original)

    bare = _BARE.match(cleaned)
    if bare:
        return round(float(bare.group(1)) * 3600)

    raise InvalidDuration(original)


def format_hhmmss(seconds):
    """Format elapsed time for the running timer, as h:mm:ss."""
    hours, remainder = divmod(int(seconds), 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}"


def format_hm(seconds):
    """Format a duration as H:MM — the way people actually say it.

    Rounds to the nearest minute, carrying into the hour so that 59.98
    minutes reads "1:00" and never "0:60".
    """
    minutes = round(int(seconds) / 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}"


def format_hours(seconds):
    """Format seconds as decimal hours for entry boxes and totals.

    Trailing zeros are dropped so a full day reads "8", not "8.00".
    """
    hours = round(int(seconds) / 3600, 2)
    text = f"{hours:.2f}".rstrip("0").rstrip(".")
    return text or "0"
