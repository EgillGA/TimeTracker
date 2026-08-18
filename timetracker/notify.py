"""An actual Windows notification: banner, sound, Action Center — the works.

The hourly check-in used to be visual only, which is easy to miss entirely
when the strip is a small thing parked in a corner and the screen belongs to
something else. Shell_NotifyIcon is the classic tray-balloon API, but Windows
10 onward renders an NIF_INFO balloon as a real toast — banner, default
notification sound, and a line in Action Center — without needing the newer
WinRT toast APIs, which are a much larger surface to reach through ctypes.

Best-effort, like everything else that pokes the Windows shell here: a
notification that fails to show is not a reason the check-in itself should
not happen.
"""

import ctypes
import tkinter as tk
from ctypes import wintypes

NIM_ADD = 0x0
NIM_MODIFY = 0x1
NIM_DELETE = 0x2

NIF_ICON = 0x2
NIF_TIP = 0x4
NIF_INFO = 0x10

NIIF_INFO = 0x1

LR_LOADFROMFILE = 0x10
IMAGE_ICON = 1

# Shared across calls so a second toast while one is still showing modifies
# the same icon rather than fighting it for the uID/hWnd pair.
_ICON_ID = 1


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", ctypes.c_wchar * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", ctypes.c_wchar * 256),
        ("uTimeoutOrVersion", wintypes.UINT),
        ("szInfoTitle", ctypes.c_wchar * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", ctypes.c_byte * 16),
        ("hBalloonIcon", wintypes.HICON),
    ]


def _load_icon(path):
    try:
        handle = ctypes.windll.user32.LoadImageW(
            None, str(path), IMAGE_ICON, 0, 0, LR_LOADFROMFILE)
    except OSError:
        return None
    return handle or None


def toast(window, title, message, icon_path=None, hold_ms=8000):
    """Pop a real Windows notification anchored to a Tk window.

    True if it was handed to the shell. `window` only needs a real HWND —
    Shell_NotifyIcon uses it to route clicks on the tray icon back, which
    nothing here listens for — and an `after()` to schedule the icon's
    removal. The toast itself, once handed to the shell, is not tied to that
    icon's lifetime, so removing it does not cut the notification short.
    """
    if not hasattr(ctypes, "windll"):
        return False

    try:
        hwnd = window.winfo_id()
    except (AttributeError, tk.TclError):
        return False
    if not hwnd:
        return False

    data = NOTIFYICONDATAW()
    data.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
    data.hWnd = hwnd
    data.uID = _ICON_ID
    data.uFlags = NIF_ICON | NIF_TIP | NIF_INFO
    data.hIcon = _load_icon(icon_path) or 0
    data.szTip = "TimeTracker"
    data.szInfo = message[:255]
    data.szInfoTitle = title[:63]
    data.dwInfoFlags = NIIF_INFO

    shell32 = ctypes.windll.shell32
    if not shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(data)):
        # Already there from a previous call this session — update it instead.
        if not shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(data)):
            return False

    def cleanup():
        remove = NOTIFYICONDATAW()
        remove.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        remove.hWnd = hwnd
        remove.uID = _ICON_ID
        shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(remove))

    window.after(hold_ms, cleanup)
    return True
