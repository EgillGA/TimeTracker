"""Week arithmetic: targets, totals, and where the gaps are.

Pure functions over plain data. Tempo is authoritative for time that has been
submitted; local records supply time that has not been submitted yet. Keeping
those two numbers separate all the way through is what stops the same hour
from being counted twice.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta

WEEKDAYS_PER_WEEK = 5


def weekdays_of_week(reference):
    """Monday to Friday of the week containing `reference`.

    A weekend date belongs to the week that has just ended, not the one about
    to start — someone catching up on Saturday means the days behind them.
    """
    monday = reference - timedelta(days=reference.weekday())
    return [monday + timedelta(days=offset) for offset in range(WEEKDAYS_PER_WEEK)]


def pending_seconds(entries):
    """Sum the local entries that have not yet reached Tempo.

    An entry with no `submitted` key is treated as unsubmitted: a day file from
    an older version should reappear as work to do, never silently vanish.
    """
    return sum(
        int(entry.get("seconds", 0))
        for entry in entries
        if not entry.get("submitted", False)
    )


@dataclass(frozen=True)
class DaySummary:
    date: date
    submitted_seconds: int
    pending_seconds: int
    target_seconds: int

    @property
    def total_seconds(self):
        return self.submitted_seconds + self.pending_seconds

    @property
    def missing_seconds(self):
        """Never negative — a long day is not a credit against a short one."""
        return max(0, self.target_seconds - self.total_seconds)

    @property
    def is_complete(self):
        return self.missing_seconds == 0


@dataclass
class WeekData:
    """Everything the week window needs.

    `records` carries each day's local record so any day can be edited in
    place, not just looked at — the point of the view is fixing a short week,
    not admiring it.
    """

    days: list = field(default_factory=list)
    records: dict = field(default_factory=dict)
    assigned: list = field(default_factory=list)
    internal: list = field(default_factory=list)
    target_seconds: int = 8 * 3600
    banner: str = ""

    @property
    def total_seconds(self):
        return sum(day.total_seconds for day in self.days)

    @property
    def week_target_seconds(self):
        return sum(day.target_seconds for day in self.days)

    @property
    def short_days(self):
        return [day for day in self.days if not day.is_complete]


@dataclass(frozen=True)
class WeekSummary:
    days: list

    @property
    def total_seconds(self):
        return sum(day.total_seconds for day in self.days)

    @property
    def target_seconds(self):
        return sum(day.target_seconds for day in self.days)

    @property
    def missing_seconds(self):
        """The sum of per-day shortfalls, not target minus total.

        Twelve hours on Monday must not cancel out an empty Wednesday: the
        hours still have to be attributed to the day they happened on.
        """
        return sum(day.missing_seconds for day in self.days)

    @property
    def short_days(self):
        return [day for day in self.days if not day.is_complete]

    @property
    def is_complete(self):
        return not self.short_days


def summarise_week(reference, submitted_by_date, pending_by_date, hours_per_day=8.0):
    """Build the week view around `reference`.

    `submitted_by_date` and `pending_by_date` map a date to seconds. Dates
    outside the week are ignored rather than rejected, so a caller can hand
    over a wider range without filtering first.
    """
    target = int(hours_per_day * 3600)
    return WeekSummary(
        days=[
            DaySummary(
                date=day,
                submitted_seconds=int(submitted_by_date.get(day, 0)),
                pending_seconds=int(pending_by_date.get(day, 0)),
                target_seconds=target,
            )
            for day in weekdays_of_week(reference)
        ]
    )
