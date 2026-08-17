"""The Start Menu shortcut that makes the taskbar button pinnable.

Cosmetic infrastructure, same rule as win.py: the interesting failure mode is
"raises and stops the install", not "the icon looks slightly wrong" - so most
of this is proving it never raises, plus a round trip on Windows proving the
file it writes actually says what we asked it to.
"""

import ctypes
import tempfile
import unittest
from pathlib import Path

from timetracker import shortcut


def on_windows():
    return hasattr(ctypes, "windll")


class BuildingAShortcut(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = str(Path(self._tmp.name) / "TimeTracker.lnk")

    def _open_for_reading(self):
        """Load self.path back for verification, on this test's own COM
        apartment - separate from the one shortcut.create() owns and tears
        down internally each time it's called."""
        ctypes.windll.ole32.CoInitialize(None)
        self.addCleanup(ctypes.windll.ole32.CoUninitialize)

        link = shortcut._create_instance(shortcut.CLSID_SHELL_LINK, shortcut.IID_SHELL_LINK_W)
        self.addCleanup(shortcut._release, link)
        persist = shortcut._query_interface(link, shortcut.IID_PERSIST_FILE)
        self.addCleanup(shortcut._release, persist)
        self.assertEqual(
            shortcut._vtable(persist, shortcut.IPersistFileVtbl).Load(persist, self.path, 0), 0)
        return link

    def test_it_reports_whether_it_worked(self):
        result = shortcut.create(self.path, target="wscript.exe")
        self.assertIsInstance(result, bool)

    def test_a_bogus_target_does_not_raise(self):
        # SetPath doesn't validate the target exists; this just proves the
        # whole call chain survives whatever garbage is handed to it.
        self.assertIsInstance(
            shortcut.create(self.path, target=""), bool
        )

    @unittest.skipUnless(on_windows(), "Windows only")
    def test_windows_writes_the_file(self):
        self.assertTrue(shortcut.create(self.path, target="wscript.exe"))
        self.assertTrue(Path(self.path).exists())

    @unittest.skipUnless(on_windows(), "Windows only")
    def test_the_arguments_round_trip(self):
        ok = shortcut.create(
            self.path,
            target="wscript.exe",
            arguments='"C:\\TimeTracker\\run_timetracker.vbs"',
            working_dir="C:\\TimeTracker",
            description="Open TimeTracker",
            app_id="Aptoz.TimeTracker.Test",
        )
        self.assertTrue(ok)

        link = self._open_for_reading()
        shell = shortcut._vtable(link, shortcut.IShellLinkWVtbl)
        buffer = ctypes.create_unicode_buffer(260)
        shell.GetArguments(link, buffer, 260)
        self.assertEqual(buffer.value, '"C:\\TimeTracker\\run_timetracker.vbs"')

        shell.GetWorkingDirectory(link, buffer, 260)
        self.assertEqual(buffer.value, "C:\\TimeTracker")

        shell.GetDescription(link, buffer, 260)
        self.assertEqual(buffer.value, "Open TimeTracker")

    @unittest.skipUnless(on_windows(), "Windows only")
    def test_the_application_id_round_trips(self):
        self.assertTrue(shortcut.create(
            self.path, target="wscript.exe", app_id="Aptoz.TimeTracker.Test"
        ))

        link = self._open_for_reading()
        store = shortcut._query_interface(link, shortcut.IID_PROPERTY_STORE)
        self.addCleanup(shortcut._release, store)
        variant = shortcut.PROPVARIANT()
        hr = shortcut._vtable(store, shortcut.IPropertyStoreVtbl).GetValue(
            store, ctypes.byref(shortcut.PKEY_APPUSERMODEL_ID), ctypes.byref(variant))
        self.addCleanup(ctypes.windll.ole32.PropVariantClear, ctypes.byref(variant))

        self.assertEqual(hr, 0)
        value = ctypes.cast(variant.data1, ctypes.c_wchar_p).value
        self.assertEqual(value, "Aptoz.TimeTracker.Test")

    @unittest.skipUnless(on_windows(), "Windows only")
    def test_an_unwritable_path_fails_without_raising(self):
        bogus = str(Path(self._tmp.name) / "nowhere" / "nested" / "TimeTracker.lnk")
        self.assertFalse(shortcut.create(bogus, target="wscript.exe"))


if __name__ == "__main__":
    unittest.main()
