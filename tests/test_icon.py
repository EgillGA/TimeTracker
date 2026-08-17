"""The window icon.

Cosmetic, so the tests are mostly about it never being able to stop the
program opening — and about the one non-obvious trap: Tk throws away an image
nothing holds a reference to, and the icon silently reverts.
"""

import tkinter as tk
import unittest
from pathlib import Path

from timetracker import icon

ASSETS = Path(__file__).resolve().parent.parent / "assets"


def has_display():
    try:
        tk.Tk().destroy()
        return True
    except tk.TclError:
        return False


class TheAssetsAreThere(unittest.TestCase):
    def test_the_ico_exists(self):
        self.assertTrue(icon.ICO.exists(),
                        "run scripts/make_icon.ps1 then scripts/build_icon.py")

    def test_the_png_exists(self):
        self.assertTrue(icon.PNG.exists())

    def test_the_ico_holds_several_sizes(self):
        # One 16px image would look terrible on a high-DPI taskbar.
        data = icon.ICO.read_bytes()
        count = int.from_bytes(data[4:6], "little")
        self.assertGreaterEqual(count, 4)

    def test_the_ico_says_it_is_an_icon(self):
        data = icon.ICO.read_bytes()
        self.assertEqual(int.from_bytes(data[2:4], "little"), 1)


@unittest.skipUnless(has_display(), "no display available")
class ApplyingIt(unittest.TestCase):
    def setUp(self):
        self.window = tk.Tk()
        self.window.attributes("-alpha", 0.0)
        self.addCleanup(self._teardown)

    def _teardown(self):
        try:
            self.window.destroy()
        except tk.TclError:
            pass

    def test_it_applies(self):
        self.assertTrue(icon.apply(self.window))

    def test_a_missing_ico_falls_back_to_the_png(self):
        self.assertTrue(
            icon.apply(self.window, ico=ASSETS / "nope.ico", png=icon.PNG)
        )

    def test_the_image_is_kept_alive(self):
        # Without a reference Tk collects it and the icon reverts to the
        # default feather, which looks like the icon simply not working.
        before = len(icon._keep_alive)
        icon.apply(self.window, ico=ASSETS / "nope.ico", png=icon.PNG)
        self.assertGreater(len(icon._keep_alive), before)

    def test_missing_files_are_not_fatal(self):
        applied = icon.apply(self.window, ico=ASSETS / "nope.ico",
                             png=ASSETS / "nope.png")
        self.assertFalse(applied)

    def test_an_unreadable_file_is_not_fatal(self):
        # A truncated or corrupt icon must not stop the window opening.
        broken = ASSETS / "broken-for-test.ico"
        broken.write_bytes(b"not an icon")
        self.addCleanup(broken.unlink)

        applied = icon.apply(self.window, ico=broken,
                             png=ASSETS / "nope.png")
        self.assertFalse(applied)


if __name__ == "__main__":
    unittest.main()
