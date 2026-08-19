"""Settings from config.toml, tokens from credentials.toml.

A broken or missing config must never stop the 15:30 prompt appearing — it
falls back to defaults and carries on. Missing credentials are different:
nothing can be read or written without them, so they raise, with an
explanation aimed at someone who has not thought about this tool in months.
"""

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

JIRA_TOKEN_URL = "https://id.atlassian.com/manage-profile/security/api-tokens"
TEMPO_TOKEN_PATH = "Jira → Apps → Tempo → Settings → API integration"

DEFAULTS = {
    "jira_site": "https://apt-oz.atlassian.net",
    "jira_email": "",
    "hours_per_day": 8.0,
    "prompt_time": "15:30",
    # Falls back to prompt_time itself when unset, so a week_view_day with no
    # time of its own configured behaves exactly as it always has.
    "week_prompt_time": "15:30",
    "week_view_day": "friday",
    "day_starts_at": "08:00",
    "suggestion_count": 5,
    "suggestion_days": 30,
    "checkin_minutes": 60,
    "heartbeat_seconds": 30,
    "theme": "dark",
    "internal_project": "AI",
}


class MissingCredentials(Exception):
    """Raised when a token is absent or blank. Never contains a token value."""


@dataclass(frozen=True)
class Config:
    jira_site: str
    jira_email: str
    hours_per_day: float
    prompt_time: str
    week_view_day: str
    day_starts_at: str
    checkin_minutes: int
    heartbeat_seconds: int
    theme: str
    internal_project: str
    # Defaulted so that adding a setting does not break every caller that
    # builds a Config, which is most of the test suite.
    suggestion_count: int = DEFAULTS["suggestion_count"]
    suggestion_days: int = DEFAULTS["suggestion_days"]
    week_prompt_time: str = DEFAULTS["week_prompt_time"]
    jql: dict = field(default_factory=dict)


def _read_toml(path):
    try:
        with open(path, "rb") as handle:
            return tomllib.load(handle)
    except (FileNotFoundError, tomllib.TOMLDecodeError, OSError):
        return {}


def default_jql(internal_project):
    return {
        "assigned": (
            "assignee = currentUser() AND statusCategory != Done "
            "ORDER BY updated DESC"
        ),
        "recent": (
            "(assignee WAS currentUser() OR worklogAuthor = currentUser()) "
            "AND updated >= -7d ORDER BY updated DESC"
        ),
        "internal": (
            f"project = {internal_project} AND statusCategory != Done "
            f"ORDER BY key ASC"
        ),
    }


def load_config(root=None):
    root = Path(root) if root else Path.cwd()
    data = _read_toml(root / "config.toml")

    jira = data.get("jira") or {}
    schedule = data.get("schedule") or {}
    timer = data.get("timer") or {}
    ui = data.get("ui") or {}
    internal = data.get("internal") or {}

    internal_project = internal.get("project", DEFAULTS["internal_project"])

    jql = default_jql(internal_project)
    jql.update(data.get("jql") or {})

    return Config(
        jira_site=str(jira.get("site", DEFAULTS["jira_site"])).rstrip("/"),
        jira_email=jira.get("email", DEFAULTS["jira_email"]),
        hours_per_day=float(schedule.get("hours_per_day", DEFAULTS["hours_per_day"])),
        prompt_time=schedule.get("prompt_time", DEFAULTS["prompt_time"]),
        # Absent week_prompt_time means "same as prompt_time" — not a
        # separately hardcoded default, so changing prompt_time alone still
        # moves the week day's time along with it, as it always did.
        week_prompt_time=schedule.get(
            "week_prompt_time",
            schedule.get("prompt_time", DEFAULTS["prompt_time"]),
        ),
        week_view_day=schedule.get("week_view_day", DEFAULTS["week_view_day"]),
        day_starts_at=schedule.get("day_starts_at", DEFAULTS["day_starts_at"]),
        suggestion_count=int(
            data.get("suggestions", {}).get("count", DEFAULTS["suggestion_count"])
        ),
        suggestion_days=int(
            data.get("suggestions", {}).get("days", DEFAULTS["suggestion_days"])
        ),
        checkin_minutes=int(timer.get("checkin_minutes", DEFAULTS["checkin_minutes"])),
        heartbeat_seconds=int(
            timer.get("heartbeat_seconds", DEFAULTS["heartbeat_seconds"])
        ),
        theme=ui.get("theme", DEFAULTS["theme"]),
        internal_project=internal_project,
        jql=jql,
    )


def _set_schedule_key(lines, key, value):
    """Set one key's value inside [schedule], adding the key or the whole
    table if either is missing. Returns the edited lines."""
    section_at = None
    key_at = None
    in_schedule = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_schedule = stripped.lower() == "[schedule]"
            if in_schedule:
                section_at = index
            continue
        if in_schedule and re.match(rf"^\s*{re.escape(key)}\s*=", line):
            key_at = index

    new_line = f'{key}   = "{value}"\n'

    if key_at is not None:
        lines[key_at] = new_line
    elif section_at is not None:
        lines.insert(section_at + 1, new_line)
    else:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines.append("\n[schedule]\n")
        lines.append(new_line)

    return lines


def write_schedule(root, prompt_time, week_prompt_time=None):
    """Persist prompt_time — and week_prompt_time, if given — into
    config.toml, in place.

    Edited line by line rather than re-serialised from load_config's parsed
    result, so the comments and layout the user sees on opening the file
    survive a change made from inside the app.
    """
    path = Path(root) / "config.toml" if root else Path("config.toml")
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True) if path.exists() else []

    lines = _set_schedule_key(lines, "prompt_time", prompt_time)
    if week_prompt_time is not None:
        lines = _set_schedule_key(lines, "week_prompt_time", week_prompt_time)

    path.write_text("".join(lines), encoding="utf-8")


def load_credentials(root=None):
    """Return `(jira_token, tempo_token)`, or explain what is missing."""
    root = Path(root) if root else Path.cwd()
    path = root / "credentials.toml"

    if not path.exists():
        raise MissingCredentials(_setup_message(path, "the file does not exist yet"))

    try:
        with open(path, "rb") as handle:
            data = tomllib.load(handle)
    except tomllib.TOMLDecodeError:
        # Almost always a token pasted without quotes. Say so — reporting this
        # as "empty" sends the user looking for the wrong problem, and the
        # error text from tomllib may echo the token itself.
        raise MissingCredentials(
            f"{path} has a syntax error.\n\n"
            f"Both values must be wrapped in quotes:\n\n"
            f'  jira_api_token  = "paste-the-token-here"\n'
            f'  tempo_api_token = "paste-the-token-here"\n\n'
            f"A token pasted without quotes is the usual cause."
        ) from None
    except OSError:
        raise MissingCredentials(
            _setup_message(path, "the file could not be read")
        ) from None
    jira_token = str(data.get("jira_api_token", "")).strip()
    tempo_token = str(data.get("tempo_api_token", "")).strip()

    blank = [
        name
        for name, value in (("jira_api_token", jira_token),
                            ("tempo_api_token", tempo_token))
        if not value
    ]
    if blank:
        raise MissingCredentials(
            _setup_message(path, f"{' and '.join(blank)} is empty")
        )

    return jira_token, tempo_token


def _setup_message(path, reason):
    return (
        f"TimeTracker needs its API tokens, but {reason}.\n\n"
        f"Open {path} and fill in both values:\n\n"
        f"  jira_api_token  — create one at {JIRA_TOKEN_URL}\n"
        f"  tempo_api_token — create one at {TEMPO_TOKEN_PATH}\n\n"
        f"Paste each token between the quotes and save the file."
    )
