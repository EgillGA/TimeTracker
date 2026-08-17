"""Local storage: the only thing standing between a typed day and losing it.

Two failure modes drive these tests. A crash mid-write must not leave a
half-written day file that reads as zero hours. And a machine that slept for
four hours must not wake up and award itself four hours of work.
"""

import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from timelogger.store import Store, recoverable_seconds

HOUR = 3600


class StoreTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "Timelogger"
        self.store = Store(self.root)
        self.addCleanup(self._tmp.cleanup)


class DayRecords(StoreTestCase):
    def test_missing_day_returns_an_empty_record_not_none(self):
        record = self.store.load_day(date(2026, 8, 17))
        self.assertEqual(record["date"], "2026-08-17")
        self.assertEqual(record["entries"], [])
        self.assertEqual(record["segments"], [])
        self.assertIsNone(record["submitted_at"])

    def test_saved_entries_survive_a_reload(self):
        record = self.store.load_day(date(2026, 8, 17))
        record["entries"].append(
            {"issue_key": "AV-412", "seconds": 3 * HOUR, "submitted": False}
        )
        self.store.save_day(record)

        reloaded = Store(self.root).load_day(date(2026, 8, 17))
        self.assertEqual(reloaded["entries"][0]["issue_key"], "AV-412")
        self.assertEqual(reloaded["entries"][0]["seconds"], 3 * HOUR)

    def test_submission_bookkeeping_survives_a_reload(self):
        # Losing the worklog id would mean resubmitting time already in Tempo.
        record = self.store.load_day(date(2026, 8, 17))
        record["entries"].append(
            {"issue_key": "AV-412", "seconds": HOUR,
             "submitted": True, "tempo_worklog_id": 99123}
        )
        self.store.save_day(record)

        entry = self.store.load_day(date(2026, 8, 17))["entries"][0]
        self.assertTrue(entry["submitted"])
        self.assertEqual(entry["tempo_worklog_id"], 99123)

    def test_each_day_is_its_own_file(self):
        for day in (date(2026, 8, 17), date(2026, 8, 18)):
            record = self.store.load_day(day)
            record["entries"].append({"issue_key": "AV-1", "seconds": HOUR})
            self.store.save_day(record)

        self.assertEqual(self.store.load_day(date(2026, 8, 17))["date"], "2026-08-17")
        self.assertEqual(
            sorted(p.name for p in (self.root / "days").glob("*.json")),
            ["2026-08-17.json", "2026-08-18.json"],
        )

    def test_root_directory_is_created_on_demand(self):
        self.assertFalse(self.root.exists())
        self.store.save_day(self.store.load_day(date(2026, 8, 17)))
        self.assertTrue((self.root / "days").is_dir())

    def test_write_leaves_no_temporary_file_behind(self):
        self.store.save_day(self.store.load_day(date(2026, 8, 17)))
        self.assertEqual(list((self.root / "days").glob("*.tmp")), [])


class CorruptFiles(StoreTestCase):
    def _write_garbage(self, day):
        path = self.store.day_path(day)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{ this is not json", encoding="utf-8")
        return path

    def test_corrupt_day_file_yields_a_fresh_record_instead_of_crashing(self):
        self._write_garbage(date(2026, 8, 17))
        record = self.store.load_day(date(2026, 8, 17))
        self.assertEqual(record["entries"], [])
        self.assertEqual(record["date"], "2026-08-17")

    def test_corrupt_day_file_is_quarantined_never_deleted(self):
        self._write_garbage(date(2026, 8, 17))
        self.store.load_day(date(2026, 8, 17))

        quarantined = list((self.root / "days").glob("2026-08-17.json.corrupt-*"))
        self.assertEqual(len(quarantined), 1)
        self.assertEqual(quarantined[0].read_text(encoding="utf-8"),
                         "{ this is not json")

    def test_quarantine_reports_where_the_old_file_went(self):
        # The window shows this path to the user, so it has to come back out.
        self._write_garbage(date(2026, 8, 17))
        self.store.load_day(date(2026, 8, 17))
        self.assertEqual(len(self.store.warnings), 1)
        self.assertIn("corrupt-", self.store.warnings[0])

    def test_two_corruptions_do_not_overwrite_each_other(self):
        self._write_garbage(date(2026, 8, 17))
        self.store.load_day(date(2026, 8, 17))
        self._write_garbage(date(2026, 8, 17))
        self.store.load_day(date(2026, 8, 17))
        self.assertEqual(
            len(list((self.root / "days").glob("2026-08-17.json.corrupt-*"))), 2
        )


class TimerState(StoreTestCase):
    STATE = {
        "issue_key": "AV-412",
        "issue_id": 10412,
        "summary": "Fix altimeter calculation",
        "started_at": "2026-08-17T09:15:03",
        "last_heartbeat": "2026-08-17T10:44:33",
        "paused_total_seconds": 0,
    }

    def test_no_timer_means_none(self):
        self.assertIsNone(self.store.load_timer())

    def test_running_timer_survives_a_restart(self):
        self.store.save_timer(self.STATE)
        self.assertEqual(Store(self.root).load_timer()["issue_key"], "AV-412")

    def test_clearing_removes_the_timer(self):
        self.store.save_timer(self.STATE)
        self.store.clear_timer()
        self.assertIsNone(self.store.load_timer())

    def test_clearing_a_timer_that_is_not_running_is_harmless(self):
        self.store.clear_timer()
        self.assertIsNone(self.store.load_timer())

    def test_corrupt_timer_state_is_quarantined_and_reads_as_no_timer(self):
        path = self.store.timer_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not json at all", encoding="utf-8")

        self.assertIsNone(self.store.load_timer())
        self.assertEqual(len(list(self.root.glob("timer.json.corrupt-*"))), 1)


class TimerRecovery(unittest.TestCase):
    """Recovery is bounded by the last heartbeat, never by the current clock.

    The timer writes a heartbeat every 30 seconds. If the process died or the
    machine slept, the heartbeat is the last moment work was demonstrably
    happening; anything after that is a guess, and guessing high is how a
    lunch break becomes billable."""

    def test_elapsed_is_measured_to_the_last_heartbeat(self):
        state = {
            "started_at": "2026-08-17T09:00:00",
            "last_heartbeat": "2026-08-17T10:30:00",
            "paused_total_seconds": 0,
        }
        self.assertEqual(recoverable_seconds(state), 90 * 60)

    def test_a_long_sleep_after_the_last_heartbeat_is_not_counted(self):
        state = {
            "started_at": "2026-08-17T09:00:00",
            "last_heartbeat": "2026-08-17T09:30:00",
            "paused_total_seconds": 0,
        }
        # Four hours of wall clock have passed, but only 30 minutes are real.
        now = datetime(2026, 8, 17, 13, 30, 0)
        self.assertEqual(recoverable_seconds(state, now=now), 30 * 60)

    def test_paused_time_is_subtracted(self):
        state = {
            "started_at": "2026-08-17T09:00:00",
            "last_heartbeat": "2026-08-17T11:00:00",
            "paused_total_seconds": 30 * 60,
        }
        self.assertEqual(recoverable_seconds(state), 90 * 60)

    def test_heartbeat_before_start_yields_zero_not_negative(self):
        # Clock changes and daylight saving can produce this.
        state = {
            "started_at": "2026-08-17T09:00:00",
            "last_heartbeat": "2026-08-17T08:00:00",
            "paused_total_seconds": 0,
        }
        self.assertEqual(recoverable_seconds(state), 0)

    def test_pauses_longer_than_the_run_yield_zero(self):
        state = {
            "started_at": "2026-08-17T09:00:00",
            "last_heartbeat": "2026-08-17T09:30:00",
            "paused_total_seconds": 99 * 60,
        }
        self.assertEqual(recoverable_seconds(state), 0)

    def test_missing_heartbeat_falls_back_to_the_start_time(self):
        # A timer that never got to write one has zero demonstrable work.
        state = {"started_at": "2026-08-17T09:00:00"}
        self.assertEqual(recoverable_seconds(state), 0)


class AtomicWrites(StoreTestCase):
    def test_a_failed_write_leaves_the_previous_day_intact(self):
        record = self.store.load_day(date(2026, 8, 17))
        record["entries"].append({"issue_key": "AV-412", "seconds": 3 * HOUR})
        self.store.save_day(record)

        broken = dict(record)
        broken["entries"] = [{"seconds": object()}]  # not JSON-serialisable
        with self.assertRaises(TypeError):
            self.store.save_day(broken)

        survivor = json.loads(
            self.store.day_path(date(2026, 8, 17)).read_text(encoding="utf-8")
        )
        self.assertEqual(survivor["entries"][0]["seconds"], 3 * HOUR)


if __name__ == "__main__":
    unittest.main()
