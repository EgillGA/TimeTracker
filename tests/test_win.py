"""Windows shell integration: the taskbar identity and the title bar.

Both are cosmetic and both are best-effort, so the thing these tests mostly
guarantee is that neither can stop the program starting.
"""

import ctypes
import tkinter as tk
import unittest

from timetracker import win


def on_windows():
    return hasattr(ctypes, "windll")


def has_display():
    try:
        tk.Tk().destroy()
        return True
    except tk.TclError:
        return False


class ApplicationIdentity(unittest.TestCase):
    def test_it_reports_whether_it_worked(self):
        self.assertIsInstance(win.set_app_id(), bool)

    @unittest.skipUnless(on_windows(), "Windows only")
    def test_windows_accepts_it(self):
        self.assertTrue(win.set_app_id())

    @unittest.skipUnless(on_windows(), "Windows only")
    def test_the_shell_reports_back_the_id_we_set(self):
        # If this is not set, the taskbar button belongs to python.exe and
        # wears Python's icon whatever the window's own icon is.
        win.set_app_id("Aptoz.TimeTracker.Test")

        buffer = ctypes.c_wchar_p()
        ctypes.windll.shell32.GetCurrentProcessExplicitAppUserModelID(
            ctypes.byref(buffer)
        )
        self.assertEqual(buffer.value, "Aptoz.TimeTracker.Test")

        win.set_app_id()  # put the real one back


@unittest.skipUnless(has_display(), "no display available")
class TheTitleBar(unittest.TestCase):
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
        self.assertIsInstance(win.dark_titlebar(self.window), bool)

    @unittest.skipUnless(on_windows(), "Windows only")
    def test_windows_accepts_a_dark_title_bar(self):
        self.assertTrue(win.dark_titlebar(self.window))

    @unittest.skipUnless(on_windows(), "Windows only")
    def test_it_can_be_turned_back_off(self):
        self.assertTrue(win.dark_titlebar(self.window, dark=False))

    def test_a_destroyed_window_does_not_raise(self):
        self.window.destroy()
        self.assertFalse(win.dark_titlebar(self.window))

    def test_something_that_is_not_a_window_does_not_raise(self):
        self.assertFalse(win.dark_titlebar(object()))

    @unittest.skipUnless(on_windows(), "Windows only")
    def test_a_hidden_window_is_left_hidden(self):
        # The attribute needs a repaint to show, but forcing one must not
        # shove a window on screen that was deliberately put away.
        self.window.withdraw()
        win.dark_titlebar(self.window)
        self.assertEqual(self.window.state(), "withdrawn")


if __name__ == "__main__":
    unittest.main()
