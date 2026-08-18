"""The hourly check-in's Windows notification.

Cosmetic and best-effort, same rule as win.py: nothing here may be able to
stop the check-in itself, so most of this is proving it never raises, plus
a round trip on Windows that the shell actually accepted the icon.
"""

import ctypes
import tkinter as tk
import unittest

from timetracker import icon, notify


def on_windows():
    return hasattr(ctypes, "windll")


def has_display():
    try:
        tk.Tk().destroy()
        return True
    except tk.TclError:
        return False


@unittest.skipUnless(has_display(), "no display available")
class ShowingAToast(unittest.TestCase):
    def setUp(self):
        self.window = tk.Tk()
        self.window.attributes("-alpha", 0.0)
        self.addCleanup(self._teardown)

    def _teardown(self):
        try:
            self.window.destroy()
        except tk.TclError:
            pass

    def test_it_reports_whether_it_worked(self):
        result = notify.toast(self.window, "Still tracking?", "AP-7500 — running 1:00:00")
        self.assertIsInstance(result, bool)

    @unittest.skipUnless(on_windows(), "Windows only")
    def test_windows_accepts_it(self):
        self.assertTrue(
            notify.toast(self.window, "Still tracking?", "AP-7500 — running 1:00:00")
        )

    @unittest.skipUnless(on_windows(), "Windows only")
    def test_a_missing_icon_file_still_shows_the_toast(self):
        # A cosmetic detail, not a reason to lose the notification itself.
        self.assertTrue(
            notify.toast(self.window, "Still tracking?", "AP-7500", icon_path="nowhere.ico")
        )

    @unittest.skipUnless(on_windows(), "Windows only")
    def test_the_real_icon_works_too(self):
        self.assertTrue(
            notify.toast(self.window, "Still tracking?", "AP-7500", icon_path=icon.ICO)
        )

    @unittest.skipUnless(on_windows(), "Windows only")
    def test_calling_it_twice_updates_rather_than_fails(self):
        self.assertTrue(notify.toast(self.window, "First", "one"))
        self.assertTrue(notify.toast(self.window, "Second", "two"))

    def test_a_destroyed_window_does_not_raise(self):
        self.window.destroy()
        self.assertFalse(notify.toast(self.window, "Still tracking?", "AP-7500"))

    def test_something_that_is_not_a_window_does_not_raise(self):
        self.assertFalse(notify.toast(object(), "Still tracking?", "AP-7500"))


if __name__ == "__main__":
    unittest.main()
