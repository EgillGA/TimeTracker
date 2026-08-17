"""Local state: one JSON file per day, plus the running timer.

Everything here is deliberately plain text you can open in Notepad and fix by
hand. When a tool that logs your hours goes wrong, being able to see and
correct the data yourself matters more than efficiency.

Writes are atomic: serialise first, write to a temporary file, then replace.
A crash can therefore lose the newest change, but never truncate the file into
a day that reads as zero hours.
"""

import json
import os
from datetime import date, datetime
from pathlib import Path

TIMER_FILENAME = "timer.json"
DAYS_DIRNAME = "days"


def default_root():
    """%APPDATA%\\TimeTracker — state lives outside the source folder."""
    appdata = os.environ.get("APPDATA")
    base = Path(appdata) if appdata else Path.home() / ".config"
    return base / "TimeTracker"


def _empty_day(day):
    return {"date": day.isoformat(), "submitted_at": None, "entries": [], "segments": []}


def _parse(text):
    return datetime.fromisoformat(text) if text else None


def recoverable_seconds(state, now=None):
    """How much of an interrupted timer can honestly be claimed.

    Bounded by the last heartbeat, not by the current clock: after the
    heartbeat stops, there is no evidence anyone was working. A machine that
    slept through lunch must not bill for it.
    """
    started = _parse(state.get("started_at"))
    if started is None:
        return 0

    end = _parse(state.get("last_heartbeat")) or started
    if now is not None:
        end = min(end, now)

    elapsed = (end - started).total_seconds() - state.get("paused_total_seconds", 0)
    return max(0, int(elapsed))


class Store:
    """Reads and writes TimeTracker's local files.

    Corrupt files are moved aside rather than deleted, and the move is recorded
    in `warnings` so the window can tell the user where their data went.
    """

    def __init__(self, root=None):
        self.root = Path(root) if root else default_root()
        self.warnings = []

    # -- paths --------------------------------------------------------------

    def day_path(self, day):
        return self.root / DAYS_DIRNAME / f"{day.isoformat()}.json"

    def timer_path(self):
        return self.root / TIMER_FILENAME

    # -- days ---------------------------------------------------------------

    def load_day(self, day):
        """The day's record, or a fresh empty one. Never returns None."""
        loaded = self._read_json(self.day_path(day))
        if not isinstance(loaded, dict):
            return _empty_day(day)

        record = _empty_day(day)
        record.update(loaded)
        record["date"] = day.isoformat()
        return record

    def save_day(self, record):
        self._write_json(self.day_path(date.fromisoformat(record["date"])), record)

    # -- timer --------------------------------------------------------------

    def load_timer(self):
        loaded = self._read_json(self.timer_path())
        return loaded if isinstance(loaded, dict) else None

    def save_timer(self, state):
        self._write_json(self.timer_path(), state)

    def clear_timer(self):
        self.timer_path().unlink(missing_ok=True)

    # -- internal issue cache ----------------------------------------------

    def load_internal_cache(self):
        """The last internal issue list that loaded successfully.

        Keys and titles for admin work change about once a year, so a stale
        copy is far better than an empty tab when the network is down.
        """
        cached = self._read_json(self.root / "internal_cache.json")
        return cached if isinstance(cached, list) else []

    def save_internal_cache(self, issues):
        self._write_json(self.root / "internal_cache.json", issues)

    # -- file handling ------------------------------------------------------

    def _read_json(self, path):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            self._quarantine(path)
            return None

    def _quarantine(self, path):
        """Move an unreadable file aside. Never delete — it may be the only
        record of a day's work, and a human can often still read it."""
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        spoiled = path.with_name(f"{path.name}.corrupt-{stamp}")
        try:
            path.rename(spoiled)
            self.warnings.append(
                f"{path.name} could not be read and was moved to {spoiled.name}."
            )
        except OSError:
            self.warnings.append(f"{path.name} could not be read.")

    def _write_json(self, path, payload):
        # Serialise before touching disk: a payload that cannot be encoded
        # must fail without disturbing the file already there.
        text = json.dumps(payload, indent=2, ensure_ascii=False)

        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, path)
