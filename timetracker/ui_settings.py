"""The one setting worth a dialog: what time TimeTracker opens on its own.

Everything else in config.toml is a fair thing to hand-edit once during setup.
The prompt time is the exception — it is the thing a person reasonably wants
to nudge after living with it for a week, and asking them to find the file,
find the key, and remember the scheduled task needs telling too is a lot to
ask for a one-line change.
"""

import re
import subprocess
import sys
import tkinter as tk
from pathlib import Path

from timetracker import config as config_module
from timetracker import icon, win
from timetracker.theme import Theme

TASK_NAME = "TimeTracker"

_TIME = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def _valid(text):
    return bool(_TIME.match(text.strip()))


def _task_installed():
    try:
        result = subprocess.run(
            ["schtasks", "/Query", "/TN", TASK_NAME],
            capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError:
        return False
    return result.returncode == 0


def apply(root, prompt_time):
    """Write the new time and, if the scheduled task already exists, bring
    its trigger into line with it.

    Silent either way: a settings dialog is not the place to explain
    schtasks failures, and the worst case — the task firing at the old time
    until the next successful install — is not a broken program.
    """
    config_module.write_schedule(root, prompt_time)

    if not _task_installed():
        return

    try:
        subprocess.run(
            [sys.executable, str(Path(root) / "install.py")],
            capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError:
        pass


def show(parent, root, prompt_time, theme=None, on_saved=None):
    """A small modal over `parent` to change when TimeTracker opens itself."""
    theme = theme or Theme()
    on_saved = on_saved or (lambda new_time: None)

    dialog = tk.Toplevel(parent)
    dialog.title("Settings")
    dialog.configure(bg=theme["bg"])
    icon.apply(dialog)
    win.dark_titlebar(dialog, dark=theme.name == "dark")
    dialog.transient(parent)
    dialog.resizable(False, False)
    dialog.geometry("360x200")

    pad = theme.space["lg"]

    tk.Label(dialog, text="Settings", bg=theme["bg"], fg=theme["text"],
             font=theme.font("heading"), anchor="w").pack(
        fill="x", padx=pad, pady=(pad, theme.space["sm"]))

    tk.Label(dialog, text="Open on its own at", bg=theme["bg"],
             fg=theme["text_muted"], font=theme.font("body"),
             anchor="w").pack(fill="x", padx=pad)

    field_row = tk.Frame(dialog, bg=theme["bg"])
    field_row.pack(fill="x", padx=pad, pady=theme.space["sm"])

    entry = tk.Entry(
        field_row, bg=theme["field_bg"], fg=theme["text"],
        insertbackground=theme["text"], font=theme.font("number"),
        relief="flat", justify="left", highlightthickness=1,
        highlightbackground=theme["border"], highlightcolor=theme["accent"],
    )
    entry.insert(0, prompt_time)
    entry.pack(side="left", ipady=4, ipadx=6)

    error = tk.Label(dialog, text="", bg=theme["bg"], fg=theme["warn"],
                      font=theme.font("small"), anchor="w")
    error.pack(fill="x", padx=pad)

    buttons = tk.Frame(dialog, bg=theme["bg"])
    buttons.pack(side="bottom", fill="x", padx=pad, pady=pad)

    def cancel():
        dialog.destroy()

    def save():
        text = entry.get().strip()
        if not _valid(text):
            error.configure(text='Use 24-hour HH:MM, e.g. "15:30".')
            return
        apply(root, text)
        on_saved(text)
        dialog.destroy()

    _button(buttons, "Cancel", cancel, theme, primary=False).pack(side="right")
    _button(buttons, "Save", save, theme, primary=True).pack(
        side="right", padx=(0, theme.space["sm"]))

    dialog.bind("<Escape>", lambda _e: cancel())
    dialog.bind("<Return>", lambda _e: save())
    entry.focus_set()
    entry.icursor("end")

    dialog.grab_set()
    dialog.wait_window()


def _button(parent, text, command, theme, primary):
    background = theme["accent"] if primary else theme["surface"]
    foreground = theme["accent_text"] if primary else theme["text"]

    button = tk.Label(parent, text=text, bg=background, fg=foreground,
                       font=theme.font("body_bold" if primary else "body"),
                       padx=theme.space["md"], pady=theme.space["sm"],
                       cursor="hand2")
    button.bind("<Button-1>", lambda _e: command())
    return button
