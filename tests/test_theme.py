"""Theme tokens.

Mostly constants, which are not worth testing. Two things are: that the two
palettes stay in step, and that the monospaced-number rule survives a machine
without Cascadia Mono. Both fail silently and only show up as an ugly window
months later.
"""

import unittest

from timelogger.theme import DARK, LIGHT, MONO_FALLBACK, Theme


class PalettesStayInStep(unittest.TestCase):
    def test_both_palettes_define_exactly_the_same_tokens(self):
        # A token added to one palette and forgotten in the other raises
        # KeyError in a window, at 15:30, in front of the user.
        self.assertEqual(set(DARK), set(LIGHT))

    def test_every_token_is_a_hex_colour(self):
        for name, palette in (("dark", DARK), ("light", LIGHT)):
            for token, value in palette.items():
                with self.subTest(palette=name, token=token):
                    self.assertRegex(value, r"^#[0-9A-Fa-f]{6}$")

    def test_dark_and_light_are_actually_different(self):
        self.assertNotEqual(DARK["bg"], LIGHT["bg"])
        self.assertNotEqual(DARK["text"], LIGHT["text"])


class ThemeSelection(unittest.TestCase):
    def test_named_theme_is_used(self):
        self.assertEqual(Theme("light").colors, LIGHT)

    def test_unknown_theme_falls_back_to_dark_rather_than_crashing(self):
        # A typo in config.toml must not stop the prompt appearing.
        self.assertEqual(Theme("purple").name, "dark")

    def test_tokens_are_readable_by_subscript(self):
        self.assertEqual(Theme("dark")["accent"], DARK["accent"])


class MonospacedNumbers(unittest.TestCase):
    def test_numbers_use_a_monospaced_face_by_default(self):
        theme = Theme()
        for key in ("number", "number_large", "timer"):
            with self.subTest(font=key):
                self.assertIn("Mono", theme.font(key)[0])

    def test_falls_back_to_consolas_when_cascadia_is_missing(self):
        theme = Theme().resolve_mono(available_families=["Segoe UI", "Consolas"])
        self.assertEqual(theme.font("timer")[0], MONO_FALLBACK)

    def test_fallback_keeps_the_size_and_style(self):
        theme = Theme().resolve_mono(available_families=["Consolas"])
        self.assertEqual(theme.font("timer")[1], 11)

    def test_ui_fonts_are_untouched_by_the_fallback(self):
        theme = Theme().resolve_mono(available_families=["Consolas"])
        self.assertEqual(theme.font("body")[0], "Segoe UI")

    def test_cascadia_is_kept_when_available(self):
        theme = Theme().resolve_mono(available_families=["Cascadia Mono", "Segoe UI"])
        self.assertEqual(theme.font("timer")[0], "Cascadia Mono")


class StatusColors(unittest.TestCase):
    def test_missing_time_is_danger(self):
        theme = Theme()
        self.assertEqual(theme.status_color(missing=True), theme["danger"])

    def test_unconfirmed_time_is_warn(self):
        theme = Theme()
        self.assertEqual(theme.status_color(unconfirmed=True), theme["warn"])

    def test_complete_is_accent(self):
        theme = Theme()
        self.assertEqual(theme.status_color(complete=True), theme["accent"])

    def test_missing_wins_over_unconfirmed(self):
        theme = Theme()
        self.assertEqual(
            theme.status_color(missing=True, unconfirmed=True), theme["danger"]
        )

    def test_plain_time_is_ordinary_text(self):
        theme = Theme()
        self.assertEqual(theme.status_color(), theme["text"])


if __name__ == "__main__":
    unittest.main()
