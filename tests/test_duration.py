"""Duration parsing must be forgiving about how a human types 90 minutes.

Spec section 9, rule 2: `1,5` `1.5` `1:30` `90m` `1h30` all mean 90 minutes.
Icelandic keyboards and habits produce commas; Jira produces `1h 30m`; clocks
produce `1:30`. All of them arrive in the same box.
"""

import unittest

from timelogger.duration import InvalidDuration, format_hhmmss, format_hours, parse_hours

HOUR = 3600
MINUTE = 60


class ParseTheFiveEquivalentForms(unittest.TestCase):
    """The five forms named in the spec must all mean 90 minutes."""

    def test_decimal_comma(self):
        self.assertEqual(parse_hours("1,5"), 90 * MINUTE)

    def test_decimal_point(self):
        self.assertEqual(parse_hours("1.5"), 90 * MINUTE)

    def test_clock_style(self):
        self.assertEqual(parse_hours("1:30"), 90 * MINUTE)

    def test_bare_minutes(self):
        self.assertEqual(parse_hours("90m"), 90 * MINUTE)

    def test_jira_style_without_minute_suffix(self):
        self.assertEqual(parse_hours("1h30"), 90 * MINUTE)


class ParseOtherShapesPeopleActuallyType(unittest.TestCase):
    def test_jira_style_with_minute_suffix(self):
        self.assertEqual(parse_hours("1h30m"), 90 * MINUTE)

    def test_jira_style_with_space(self):
        self.assertEqual(parse_hours("1h 30m"), 90 * MINUTE)

    def test_bare_number_means_hours(self):
        self.assertEqual(parse_hours("2"), 2 * HOUR)

    def test_hours_suffix_alone(self):
        self.assertEqual(parse_hours("2h"), 2 * HOUR)

    def test_minutes_alone(self):
        self.assertEqual(parse_hours("45m"), 45 * MINUTE)

    def test_zero_is_valid(self):
        self.assertEqual(parse_hours("0"), 0)

    def test_quarter_hour_clock_style(self):
        self.assertEqual(parse_hours("0:15"), 15 * MINUTE)

    def test_surrounding_whitespace_ignored(self):
        self.assertEqual(parse_hours("  1.5  "), 90 * MINUTE)

    def test_uppercase_suffix_accepted(self):
        self.assertEqual(parse_hours("1H30M"), 90 * MINUTE)

    def test_fractional_hours_round_to_whole_seconds(self):
        # A third of an hour is not representable exactly; Tempo wants an int.
        self.assertEqual(parse_hours("0.333"), 1199)


class RejectInputThatWouldSilentlyLogTheWrongTime(unittest.TestCase):
    """Every one of these, if accepted, produces a plausible-looking but wrong
    worklog. Rejecting loudly is the whole point."""

    def test_empty_string(self):
        with self.assertRaises(InvalidDuration):
            parse_hours("")

    def test_whitespace_only(self):
        with self.assertRaises(InvalidDuration):
            parse_hours("   ")

    def test_words(self):
        with self.assertRaises(InvalidDuration):
            parse_hours("all morning")

    def test_negative(self):
        with self.assertRaises(InvalidDuration):
            parse_hours("-1")

    def test_minutes_past_fifty_nine_in_clock_form(self):
        with self.assertRaises(InvalidDuration):
            parse_hours("1:75")

    def test_more_hours_than_exist_in_a_day(self):
        with self.assertRaises(InvalidDuration):
            parse_hours("25")

    def test_two_decimal_separators(self):
        with self.assertRaises(InvalidDuration):
            parse_hours("1.5.5")

    def test_error_message_names_the_offending_text(self):
        # The UI puts this straight in front of the user, so it has to be
        # about their input, not about the parser's internals.
        with self.assertRaises(InvalidDuration) as caught:
            parse_hours("all morning")
        self.assertIn("all morning", str(caught.exception))


class FormatForDisplay(unittest.TestCase):
    def test_hhmmss_for_the_running_timer(self):
        self.assertEqual(format_hhmmss(3767), "1:02:47")

    def test_hhmmss_pads_minutes_and_seconds(self):
        self.assertEqual(format_hhmmss(605), "0:10:05")

    def test_hhmmss_of_zero(self):
        self.assertEqual(format_hhmmss(0), "0:00:00")

    def test_hhmmss_past_ten_hours(self):
        self.assertEqual(format_hhmmss(36000), "10:00:00")

    def test_decimal_hours_for_entry_boxes(self):
        self.assertEqual(format_hours(5400), "1.5")

    def test_decimal_hours_drops_trailing_zero(self):
        self.assertEqual(format_hours(7200), "2")

    def test_decimal_hours_rounds_to_two_places(self):
        self.assertEqual(format_hours(1199), "0.33")

    def test_decimal_hours_of_zero(self):
        self.assertEqual(format_hours(0), "0")


class RoundTrip(unittest.TestCase):
    def test_formatted_hours_parse_back_to_the_same_seconds(self):
        for seconds in (0, 1800, 3600, 5400, 27000, 28800):
            with self.subTest(seconds=seconds):
                self.assertEqual(parse_hours(format_hours(seconds)), seconds)


if __name__ == "__main__":
    unittest.main()
