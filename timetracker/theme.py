"""Design tokens. The only place in the codebase that names a colour.

Two palettes with identical token names, so switching theme is a config
change rather than a rewrite. Numbers are set in a monospaced face on
purpose: proportional digits make a live timer visibly wobble as it counts,
and a wobbling counter reads as broken.
"""

DARK = {
    "bg": "#16181D",
    "surface": "#1E2127",
    "surface_hi": "#262A32",
    "border": "#2E333D",
    "text": "#EDEFF2",
    "text_muted": "#8D96A5",
    "accent": "#3FB950",
    "accent_text": "#0B1A0F",
    "warn": "#D29922",
    "danger": "#F85149",
    "field_bg": "#12141A",
}

LIGHT = {
    "bg": "#FAFBFC",
    "surface": "#FFFFFF",
    "surface_hi": "#F0F3F6",
    "border": "#D8DEE4",
    "text": "#1B1F24",
    "text_muted": "#656D76",
    "accent": "#1F883D",
    "accent_text": "#FFFFFF",
    "warn": "#9A6700",
    "danger": "#CF222E",
    "field_bg": "#FFFFFF",
}

PALETTES = {"dark": DARK, "light": LIGHT}

UI_FAMILY = "Segoe UI"
MONO_FAMILY = "Cascadia Mono"
MONO_FALLBACK = "Consolas"

FONTS = {
    "body": (UI_FAMILY, 10),
    "body_bold": (UI_FAMILY, 10, "bold"),
    "issue_key": (UI_FAMILY, 10, "bold"),
    "summary": (UI_FAMILY, 10),
    "heading": (UI_FAMILY, 14),
    "small": (UI_FAMILY, 9),
    # Every number the user reads uses these.
    "number": (MONO_FAMILY, 10),
    "number_large": (MONO_FAMILY, 12),
    "timer": (MONO_FAMILY, 11),
}

# 8px base unit throughout.
SPACE = {"xs": 4, "sm": 8, "md": 16, "lg": 20, "xl": 32}

METRICS = {
    "row_height": 44,
    "window_padding": SPACE["lg"],
    "day_window": (720, 700),
    "week_window": (760, 520),
    "strip_resting": (260, 36),
    "strip_hover": (300, 44),
    "strip_checkin": (320, 96),
    "strip_margin": 12,
    "hours_field_width": 7,
}


class Theme:
    """A resolved palette plus the fonts and metrics that go with it."""

    def __init__(self, name="dark"):
        self.name = name if name in PALETTES else "dark"
        self.colors = PALETTES[self.name]
        self.fonts = dict(FONTS)
        self.space = dict(SPACE)
        self.metrics = dict(METRICS)

    def __getitem__(self, token):
        return self.colors[token]

    def font(self, name):
        return self.fonts[name]

    def resolve_mono(self, available_families):
        """Fall back to Consolas where Cascadia Mono isn't installed.

        Older Windows images lack Cascadia Mono, and silently getting a
        proportional substitute would undo the point of using it at all.
        """
        if MONO_FAMILY in available_families:
            return self

        for key, spec in self.fonts.items():
            if spec[0] == MONO_FAMILY:
                self.fonts[key] = (MONO_FALLBACK,) + tuple(spec[1:])
        return self

    def status_color(self, *, missing=False, unconfirmed=False, complete=False):
        """One place decides what colour a number means."""
        if missing:
            return self.colors["danger"]
        if unconfirmed:
            return self.colors["warn"]
        if complete:
            return self.colors["accent"]
        return self.colors["text"]
