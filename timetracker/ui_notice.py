"""A themed message window for the few things that stop the day cold.

Not for routine feedback — errors about a row belong next to that row. This
is for the cases where there is nothing to show: no credentials, or a token
that has expired. It matches the rest rather than falling back to the stock
grey dialog, because this is the window someone sees on a bad morning.
"""

import subprocess
import tkinter as tk

from timetracker.theme import Theme


def show(title, message, open_path=None, theme=None):
    """Show a notice and block until it is closed."""
    theme = theme or Theme()
    root = tk.Tk()
    root.title(title)
    root.configure(bg=theme["bg"])
    root.geometry("560x300")
    root.minsize(420, 240)

    pad = theme.space["lg"]

    tk.Label(root, text=title, bg=theme["bg"], fg=theme["text"],
             font=theme.font("heading"), anchor="w").pack(
        fill="x", padx=pad, pady=(pad, theme.space["sm"]))

    tk.Label(root, text=message, bg=theme["bg"], fg=theme["text_muted"],
             font=theme.font("body"), anchor="w", justify="left",
             wraplength=500).pack(fill="both", expand=True, padx=pad)

    buttons = tk.Frame(root, bg=theme["bg"])
    buttons.pack(fill="x", padx=pad, pady=pad)

    def close():
        root.destroy()

    def open_file():
        try:
            subprocess.Popen(["notepad.exe", str(open_path)])
        except OSError:
            pass
        close()

    _button(buttons, "Close", close, theme, primary=not open_path).pack(
        side="right")

    if open_path:
        _button(buttons, "Open credentials.toml", open_file, theme,
                primary=True).pack(side="right", padx=theme.space["sm"])

    root.bind("<Escape>", lambda _e: close())
    root.mainloop()


def _button(parent, text, command, theme, primary):
    background = theme["accent"] if primary else theme["surface"]
    foreground = theme["accent_text"] if primary else theme["text"]

    button = tk.Label(parent, text=text, bg=background, fg=foreground,
                      font=theme.font("body_bold" if primary else "body"),
                      padx=theme.space["md"], pady=theme.space["sm"],
                      cursor="hand2")
    button.bind("<Button-1>", lambda _e: command())
    return button
