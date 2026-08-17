"""The window icon.

Two formats, because Windows wants different things in different places: the
.ico gives the title bar and taskbar a crisp size at any DPI, and the .png is
the fallback for anything that will not take an .ico.

Never fatal. A missing or unreadable icon is a cosmetic problem, and a tool
that refuses to open because it could not find a picture would be a much
larger one.
"""

import tkinter as tk
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "assets"
ICO = ASSETS / "icon.ico"
PNG = ASSETS / "icon.png"

# Tk discards an image the moment nothing references it, and a garbage
# collected icon silently reverts to the default feather. Holding the
# PhotoImage here is what keeps it on screen.
_keep_alive = []


def apply(window, ico=ICO, png=PNG):
    """Give a window the TimeTracker icon. True if one was applied."""
    if _apply_ico(window, ico):
        return True
    return _apply_png(window, png)


def _looks_like_ico(path):
    """Check the header ourselves.

    Tk accepts a corrupt .ico without complaint and then shows nothing, so
    trusting it would mean silently losing the icon instead of falling back
    to the PNG. Six bytes: reserved 0, type 1, and at least one image.
    """
    try:
        header = Path(path).read_bytes()[:6]
    except OSError:
        return False

    if len(header) < 6:
        return False

    reserved = int.from_bytes(header[0:2], "little")
    kind = int.from_bytes(header[2:4], "little")
    count = int.from_bytes(header[4:6], "little")
    return reserved == 0 and kind == 1 and count > 0


def _apply_ico(window, path):
    if not Path(path).exists() or not _looks_like_ico(path):
        return False
    try:
        # `default` makes it the icon for every window this app opens, not
        # just this one.
        window.iconbitmap(default=str(path))
    except (tk.TclError, OSError):
        return False
    return True


def _apply_png(window, path):
    if not Path(path).exists():
        return False
    try:
        image = tk.PhotoImage(master=window, file=str(path))
        window.iconphoto(True, image)
    except (tk.TclError, OSError):
        return False

    _keep_alive.append(image)
    return True
