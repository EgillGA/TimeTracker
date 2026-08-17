"""The service that joins the window to Jira, Tempo and the disk.

Everything that can fail across a network lives behind this boundary, so the
window never has to know whether the VPN is up. When Jira cannot be reached
the day still opens with whatever is on disk and a banner explaining why the
suggestions are missing — a tool that refuses to start because a server is
down is worse than no tool, because it also costs you the habit.
"""

from datetime import date, datetime, timedelta

from timetracker import dayview, timer, week
from timetracker.cache import TimedCache
from timetracker.week import weekdays_of_week
from timetracker.config import load_config, load_credentials
from timetracker.dayview import DayData
from timetracker.duration import format_clock
from timetracker.http import ApiError
from timetracker.jira import JiraClient
from timetracker.store import Store, recoverable_seconds
from timetracker.tempo import TempoClient


#: How long a fetched issue list is trusted. Long enough that navigating
#: between the day and the week is instant, short enough that an issue created
#: this morning turns up this afternoon.
LOOKUP_TTL_SECONDS = 300


class AppService:
    def __init__(self, config, store, jira, tempo, cache=None):
        self.config = config
        self.store = store
        self.jira = jira
        self.tempo = tempo
        self.cache = cache or TimedCache(LOOKUP_TTL_SECONDS)
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

        lookups = self._lookups()
        assigned, problem = self._unpack(lookups["assigned"], [])
        if problem:
            notes.append(f"{problem} Showing what is saved locally.")

        internal, problem = self._internal_from(lookups["internal"])
        if problem and problem not in notes:
            notes.append(problem)

        return DayData(
            day=day,
            record=record,
            assigned=assigned,
            # Suggestions are collapsed, so the two round trips behind them
            # are not paid until the section is opened. They are already in
            # flight by then, so opening it is normally instant anyway.
            recent_provider=self.recent_issues,
            internal=internal,
            target_seconds=int(self.config.hours_per_day * 3600),
            suggestion_count=self.config.suggestion_count,
            running=running,
            banner=" ".join(notes),
        )

    def _lookups(self):
        """The lookups a page cannot paint without, run at once and remembered.

        Sequentially these cost over a second, and were paid again every time
        the window moved between the day and the week. They do not depend on
        each other, so they go together; the answers hold for minutes, so they
        are cached; and everything not on screen yet is started in the
        background rather than waited for.
        """
        days = weekdays_of_week(date.today())
        self.cache.prefetch({
            "touched": lambda: self.jira.search(self.config.jql["recent"]),
            "logged": self._recently_logged,
            self._week_key(days[0], days[-1]):
                lambda: self.tempo.seconds_by_date(self.account_id(),
                                                   days[0], days[-1]),
        })

        # The account id goes in with the searches rather than ahead of them.
        # Resolving it first cost a whole round trip that nothing on the day
        # page was waiting for. The background lookups that do need it resolve
        # it themselves; the worst case is fetching it twice, in parallel.
        found = self.cache.gather({
            "account": self.account_id,
            "assigned": lambda: self.jira.search(self.config.jql["assigned"]),
            "internal": lambda: self.jira.search(self.config.jql["internal"]),
        })
        if not isinstance(found["account"], Exception):
            self._account_id = found["account"]
        return found

    def recent_issues(self):
        """Suggestions: what you last logged to, then what you touched.

        Resolved when the section is opened rather than at load, and normally
        already in flight by then.
        """
        found = self.cache.gather({
            "logged": self._recently_logged,
            "touched": lambda: self.jira.search(self.config.jql["recent"]),
        })
        logged, _ = self._unpack(found["logged"], [])
        touched, _ = self._unpack(found["touched"], [])
        return dayview.candidate_issues(logged, touched)

    @staticmethod
    def _week_key(start, end):
        return f"week-totals:{start}:{end}"

    @staticmethod
    def _unpack(value, fallback):
        """gather() hands back either a value or the exception that stopped it."""
        if isinstance(value, Exception):
            return fallback, str(value)
        return value, ""

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

    def _internal_from(self, result):
        """The internal list, or the last good copy of it.

        Keys for admin work change about once a year, so a stale list is far
        better than an empty tab when the network is down.
        """
        if isinstance(result, Exception):
            cached = self.store.load_internal_cache()
            if cached:
                return cached, "Internal list may be out of date."
            return [], f"{result} Showing what is saved locally."

        self.store.save_internal_cache(result)
        return result, ""

    def load_week(self, reference=None):
        """The week around `reference`, with every day editable.

        Tempo is authoritative for hours it already holds; local records
        supply what has not been sent yet. They are kept apart all the way
        through, because counting a submitted local row as pending as well is
        how a week comes to claim sixteen hours on an eight hour day.
        """
        days = weekdays_of_week(reference or date.today())
        records = {day: self.store.load_day(day) for day in days}
        notes = list(self.store.warnings)

        submitted = self.week_totals(days[0], days[-1])
        pending = {
            day: week.pending_seconds(record["entries"])
            for day, record in records.items()
        }

        lookups = self._lookups()
        assigned, problem = self._unpack(lookups["assigned"], [])
        if problem:
            notes.append(f"{problem} Showing what is saved locally.")

        internal, problem = self._internal_from(lookups["internal"])
        if problem and problem not in notes:
            notes.append(problem)

        summary = week.summarise_week(
            reference or date.today(), submitted, pending,
            self.config.hours_per_day,
        )

        return week.WeekData(
            days=summary.days,
            records=records,
            assigned=assigned,
            internal=internal,
            target_seconds=int(self.config.hours_per_day * 3600),
            banner=" ".join(notes),
        )

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

        # Tempo's totals have just changed; a cached week would still show
        # the figures from before the submission.
        if any(result["ok"] for result in results):
            self.forget_cached_lookups()

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
        """Submitted seconds per date, straight from Tempo.

        Cached by range: moving between the day and the week asks for the same
        one repeatedly, and it costs a round trip every time.
        """
        try:
            return self.cache.get(
                self._week_key(start, end),
                lambda: self.tempo.seconds_by_date(self.account_id(),
                                                   start, end),
            )
        except ApiError:
            return {}

    def forget_cached_lookups(self):
        """Drop remembered lookups so the next load fetches fresh.

        Called after submitting: Tempo's totals have just changed, and showing
        the pre-submission figures back to someone who has just pressed Submit
        would look like it had not worked.
        """
        self.cache.invalidate()


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
