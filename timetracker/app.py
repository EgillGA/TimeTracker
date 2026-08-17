"""The service that joins the window to Jira, Tempo and the disk.

Everything that can fail across a network lives behind this boundary, so the
window never has to know whether the VPN is up. When Jira cannot be reached
the day still opens with whatever is on disk and a banner explaining why the
suggestions are missing — a tool that refuses to start because a server is
down is worse than no tool, because it also costs you the habit.
"""

from datetime import date

from timetracker import dayview
from timetracker.config import load_config, load_credentials
from timetracker.dayview import DayData
from timetracker.http import ApiError
from timetracker.jira import JiraClient
from timetracker.store import Store
from timetracker.tempo import TempoClient


class AppService:
    def __init__(self, config, store, jira, tempo):
        self.config = config
        self.store = store
        self.jira = jira
        self.tempo = tempo
        self._account_id = None

    # -- loading ------------------------------------------------------------

    def load_day(self, day=None):
        day = day or date.today()
        record = self.store.load_day(day)
        notes = list(self.store.warnings)

        (assigned, recent), problem = self._candidates()
        if problem:
            notes.append(problem)

        internal, problem = self._internal()
        if problem and problem not in notes:
            notes.append(problem)

        return DayData(
            day=day,
            record=record,
            assigned=assigned,
            recent=recent,
            internal=internal,
            target_seconds=int(self.config.hours_per_day * 3600),
            banner=" ".join(notes),
        )

    def _candidates(self):
        """Assigned and recent are fetched separately and stay separate.

        They drive two different sections of the window, and merging them
        would lose the only thing that tells Projects from Suggestions.
        """
        try:
            assigned = self.jira.search(self.config.jql["assigned"])
            recent = self.jira.search(self.config.jql["recent"])
        except ApiError as error:
            return ([], []), f"{error} Showing what is saved locally."
        return (assigned, recent), ""

    def _internal(self):
        try:
            internal = self.jira.search(self.config.jql["internal"])
        except ApiError as error:
            cached = self.store.load_internal_cache()
            if cached:
                return cached, "Internal list may be out of date."
            return [], f"{error} Showing what is saved locally."

        self.store.save_internal_cache(internal)
        return internal, ""

    # -- submitting ---------------------------------------------------------

    def submit(self, record, day=None):
        """Send every unsubmitted row to Tempo.

        Rows are independent. Each success is written to disk immediately, so
        a crash or a failure part-way through can never cause the rows already
        accepted to be sent a second time.

        Returns `[{issue_key, ok, message}]`, one per row attempted.
        """
        day = day or date.fromisoformat(record["date"])

        try:
            account_id = self.account_id()
        except ApiError as error:
            return [
                {"issue_key": entry["issue_key"], "ok": False,
                 "message": str(error)}
                for entry in dayview.entries_to_submit(record)
            ]

        results = []
        for entry in dayview.entries_to_submit(record):
            results.append(self._submit_one(record, entry, day, account_id))

        self.store.save_day(record)
        return results

    def _submit_one(self, record, entry, day, account_id):
        key = entry["issue_key"]
        try:
            issue_id = entry.get("issue_id") or self.jira.issue_id(key)
            worklog_id = self.tempo.create_worklog(
                account_id=account_id,
                issue_id=issue_id,
                seconds=entry["seconds"],
                day=day,
                description=entry.get("note", ""),
            )
        except ApiError as error:
            return {"issue_key": key, "ok": False, "message": str(error)}

        dayview.mark_submitted(record, key, worklog_id)
        # Write before moving on: the id is the only thing preventing a
        # duplicate if the next row kills the process.
        self.store.save_day(record)
        return {"issue_key": key, "ok": True, "message": ""}

    # -- helpers ------------------------------------------------------------

    def account_id(self):
        if self._account_id is None:
            self._account_id = self.jira.account_id()
        return self._account_id

    def save(self, record):
        self.store.save_day(record)

    def lookup(self, key):
        """Resolve a hand-typed issue key, or None if it is not a real issue."""
        try:
            return {"key": key.upper(), "id": self.jira.issue_id(key),
                    "summary": ""}
        except ApiError:
            return None

    def week_totals(self, start, end):
        """Submitted seconds per date, straight from Tempo."""
        try:
            return self.tempo.seconds_by_date(self.account_id(), start, end)
        except ApiError:
            return {}


def build(root):
    """Assemble the service from config.toml and credentials.toml."""
    config = load_config(root)
    jira_token, tempo_token = load_credentials(root)

    return AppService(
        config=config,
        store=Store(),
        jira=JiraClient(config.jira_site, config.jira_email, jira_token),
        tempo=TempoClient(tempo_token),
    )
