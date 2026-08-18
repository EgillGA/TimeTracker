"""The settings dialog's actual logic — validation and what Save does.

The dialog itself is a thin tkinter shell not worth driving in a test; what
matters is that a bad time is rejected before anything is written, and that a
good one both lands in config.toml and, only if the scheduled task already
exists, gets that task brought into line with it.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from timetracker.config import load_config
from timetracker.ui_settings import _valid, apply


class ValidatingTheTime(unittest.TestCase):
    def test_accepts_well_formed_times(self):
        for text in ("00:00", "23:59", "09:05", "15:30"):
            self.assertTrue(_valid(text), text)

    def test_rejects_malformed_times(self):
        for text in ("9:00", "24:00", "12:60", "15:3", "abc", "", "15:30:00"):
            self.assertFalse(_valid(text), text)

    def test_tolerates_surrounding_whitespace(self):
        self.assertTrue(_valid("  09:05  "))


class ApplyingANewTime(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        (self.root / "config.toml").write_text(
            '[schedule]\nprompt_time = "15:30"\n', encoding="utf-8")

    def test_writes_the_new_time(self):
        with patch("timetracker.ui_settings.subprocess.run") as run:
            run.return_value.returncode = 1  # no task installed
            apply(self.root, "09:00")

        self.assertEqual(load_config(self.root).prompt_time, "09:00")

    def test_does_not_touch_schtasks_when_no_task_is_installed(self):
        with patch("timetracker.ui_settings.subprocess.run") as run:
            run.return_value.returncode = 1
            apply(self.root, "09:00")

        # The only call is the /Query that found nothing to update.
        self.assertEqual(run.call_count, 1)
        self.assertIn("/Query", run.call_args.args[0])

    def test_reinstalls_the_task_when_one_already_exists(self):
        with patch("timetracker.ui_settings.subprocess.run") as run:
            run.return_value.returncode = 0  # /Query finds the task
            apply(self.root, "09:00")

        self.assertEqual(run.call_count, 2)
        second_call = run.call_args_list[1].args[0]
        self.assertEqual(second_call[0], sys.executable)
        self.assertEqual(Path(second_call[1]).name, "install.py")

    def test_a_missing_schtasks_binary_does_not_raise(self):
        with patch("timetracker.ui_settings.subprocess.run",
                   side_effect=OSError("not found")):
            apply(self.root, "09:00")  # must not raise

        self.assertEqual(load_config(self.root).prompt_time, "09:00")


if __name__ == "__main__":
    unittest.main()
