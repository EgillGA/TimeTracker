"""The two bits of Windows that Tk does not do for you.

A Tk window launched through pythonw is, as far as Windows is concerned, just
Python running — so the taskbar groups it under Python and shows Python's
icon. Claiming an application id of our own fixes that.

And Tk asks for a light title bar regardless of anything else, which leaves a
white strip above a dark window. The compositor will honour a dark one, but
only if asked.

Both are best-effort. Neither is worth failing to start over, and neither
exists off Windows.
"""

import ctypes
import tkinter as tk

#: Identifies this program to the shell: taskbar grouping, pinning, and which
#: icon is shown. The convention is Company.Product.
APP_ID = "Aptoz.TimeTracker"

# DwmSetWindowAttribute. 20 since Windows 10 20H1; 19 on the builds before it,
# which is why both are tried.
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_USE_IMMERSIVE_DARK_MODE_LEGACY = 19


def set_app_id(app_id=APP_ID):
    """Tell Windows this process is its own application.

    Without it the taskbar button belongs to python.exe and wears Python's
    icon no matter what the window's own icon is. Must be called before any
    window exists.
    """
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            ctypes.c_wchar_p(app_id)
        )
    except (AttributeError, OSError):
        return False
    return True


def dark_titlebar(window, dark=True):
    """Ask the compositor for a dark title bar on this window.

    Tk always requests a light one, which on a dark window leaves a white
    strip along the top that belongs to no theme at all.
    """
    hwnd = _handle(window)
    if hwnd is None:
        return False

    value = ctypes.c_int(1 if dark else 0)
    for attribute in (DWMWA_USE_IMMERSIVE_DARK_MODE,
                      DWMWA_USE_IMMERSIVE_DARK_MODE_LEGACY):
        try:
            result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)
            )
        except (AttributeError, OSError):
            return False
        if result == 0:
            _repaint(window)
            return True

    return False


def _handle(window):
    """The HWND of the frame Windows draws, not the client area inside it.

    winfo_id() gives the widget; the title bar belongs to the frame around it,
    which is what wm_frame reports.
    """
    try:
        window.update_idletasks()
        return int(window.wm_frame(), 16)
    except (AttributeError, ValueError, tk.TclError):
        return None


def _repaint(window):
    """Nudge the frame to redraw.

    The attribute takes effect on the next non-client paint, which for a
    window already on screen may not come for some time — hiding and showing
    it forces one immediately.
    """
    try:
        if window.state() == "withdrawn":
            return
        window.withdraw()
        window.deiconify()
    except tk.TclError:
        pass
