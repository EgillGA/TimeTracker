"""The service that joins the window to Jira, Tempo and the disk.

Everything that can fail across a network lives behind this boundary, so the
window never has to know whether the VPN is up. When Jira cannot be reached
the day still opens with whatever is on disk and a banner explaining why the
suggestions are missing — a tool that refuses to start because a server is
down is worse than no tool, because it also costs you the habit.
"""

from datetime import date, datetime, timedelta

from timetracker import dayview, timer
from timetracker.config import load_config, load_credentials
from timetracker.dayview import DayData
from timetracker.duration import format_clock
from timetracker.http import ApiError
from timetracker.jira import JiraClient
from timetracker.store import Store, recoverable_seconds
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

        # A timer with a fresh heartbeat is being driven by a live strip and
        # should be shown. A stale one was left by a crash and is recovered.
        running = self.running_timer()
        recovered = ""
        if running and not timer.is_live(running, datetime.now(),
                                        self.config.heartbeat_seconds):
            running = None
            recovered = self.recover_interrupted_timer()
        record = self.store.load_day(day)
        notes = list(self.store.warnings)
        if recovered:
            notes.append(recovered)

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
            suggestion_count=self.config.suggestion_count,
            running=running,
            banner=" ".join(notes),
        )

    def _candidates(self):
        """Projects is what you own. Suggestions is what you have been near.

        Two signals feed Suggestions: the issues you last logged hours to, and
        the issues you have touched in Jira. Time logged leads, because having
        put hours against something is the stronger hint that you are about to
        again — but Jira activity catches the work that has not been logged
        yet, which is exactly the work most at risk of being forgotten.
        """
        try:
            assigned = self.jira.search(self.config.jql["assigned"])
            touched = self.jira.search(self.config.jql["recent"])
        except ApiError as error:
            return ([], []), f"{error} Showing what is saved locally."

        recent = dayview.candidate_issues(self._recently_logged(), touched)
        return (assigned, recent), ""

    def _recently_logged(self):
        """The issues you last logged time to, most recent first.

        Failing here costs only the Suggestions section — the day still opens
        and Projects still works.
        """
        try:
            history = self.tempo.worklogs(
                self.account_id(),
                date.today() - timedelta(days=self.config.suggestion_days),
                date.today(),
            )
        except ApiError:
            return []

        wanted = self.config.suggestion_count
        issue_ids = []
        for worklog in sorted(history, key=lambda w: w["date"], reverse=True):
            issue_id = worklog.get("issue_id")
            if issue_id and issue_id not in issue_ids:
                issue_ids.append(issue_id)
            if len(issue_ids) >= wanted:
                break

        if not issue_ids:
            return []

        try:
            found = self.jira.search(
                f"id in ({', '.join(str(i) for i in issue_ids)})",
                max_results=wanted,
            )
        except ApiError:
            return []

        # Jira returns them in its own order; restore most-recently-logged.
        by_id = {issue["id"]: issue for issue in found}
        return [by_id[i] for i in issue_ids if i in by_id]

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

        # Lay the whole day out first, including rows already in Tempo, so
        # each worklog gets a start time that follows the one before it.
        starts = dayview.schedule(record, self._day_start_seconds())

        results = []
        for entry in dayview.entries_to_submit(record):
            results.append(
                self._submit_one(record, entry, day, account_id, starts)
            )

        self.store.save_day(record)
        return results

    def _day_start_seconds(self):
        try:
            hours, minutes = self.config.day_starts_at.split(":")[:2]
            return int(hours) * 3600 + int(minutes) * 60
        except (AttributeError, ValueError):
            return 8 * 3600

    def _submit_one(self, record, entry, day, account_id, starts):
        key = entry["issue_key"]
        try:
            issue_id = entry.get("issue_id") or self.jira.issue_id(key)
            worklog_id = self.tempo.create_worklog(
                account_id=account_id,
                issue_id=issue_id,
                seconds=entry["seconds"],
                day=day,
                description=entry.get("note", ""),
                start_time=format_clock(starts.get(key, 8 * 3600)),
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
            return self.jira.issue(key)
        except ApiError:
            return None

    def running_timer(self):
        """The live timer's raw state, or None.

        Read from disk rather than passed in, so the day window shows the
        running issue however it was opened — from the strip, or by the 15:30
        prompt firing while a timer happens to be going.
        """
        return self.store.load_timer()

    def recover_interrupted_timer(self):
        """Fold a timer that was running when we last closed into the day.

        The recovered time is bounded by the last heartbeat, never the wall
        clock, and is flagged unconfirmed so it shows amber in the window. It
        is added rather than offered in a dialog because nothing reaches Tempo
        without pressing Submit — the row is right there to correct or remove.
        """
        state = self.store.load_timer()
        if not state:
            return ""

        seconds = recoverable_seconds(state)
        self.store.clear_timer()
        if seconds < 60:
            return ""

        record = self.store.load_day(date.today())
        dayview.add_segment(record, {
            "issue_key": state["issue_key"],
            "issue_id": state.get("issue_id", 0),
            "summary": state.get("summary", ""),
            "seconds": seconds,
            "start": state["started_at"],
            "end": state.get("last_heartbeat", state["started_at"]),
            "confirmed": False,
        })
        self.store.save_day(record)

        return (f"A timer for {state['issue_key']} was still running when "
                f"TimeTracker last closed. Its time has been added — check it.")

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
