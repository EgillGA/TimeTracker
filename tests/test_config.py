"""Settings and credentials.

The credential path matters more than it looks: an empty token and a missing
file must both produce the same clear instruction, because at 15:30 nobody
wants to debug a config loader.
"""

import tempfile
import unittest
from pathlib import Path

from timelogger.config import MissingCredentials, load_config, load_credentials

CONFIG = """
[jira]
site  = "https://apt-oz.atlassian.net"
email = "egill@aptoz.is"

[schedule]
hours_per_day = 7.5
prompt_time   = "16:00"

[ui]
theme = "light"

[internal]
project = "AI"

[jql]
assigned = "assignee = currentUser()"
recent   = "updated >= -7d"
internal = "project = AI"
"""


class ConfigTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def write(self, name, text):
        (self.root / name).write_text(text, encoding="utf-8")


class LoadingSettings(ConfigTestCase):
    def test_reads_the_values_from_the_file(self):
        self.write("config.toml", CONFIG)
        config = load_config(self.root)

        self.assertEqual(config.jira_site, "https://apt-oz.atlassian.net")
        self.assertEqual(config.jira_email, "egill@aptoz.is")
        self.assertEqual(config.hours_per_day, 7.5)
        self.assertEqual(config.prompt_time, "16:00")
        self.assertEqual(config.theme, "light")
        self.assertEqual(config.internal_project, "AI")

    def test_trailing_slash_on_the_site_is_trimmed(self):
        # Otherwise every URL ends up with a double slash and 404s.
        self.write("config.toml", '[jira]\nsite = "https://apt-oz.atlassian.net/"\n')
        self.assertEqual(load_config(self.root).jira_site,
                         "https://apt-oz.atlassian.net")

    def test_missing_file_falls_back_to_defaults(self):
        config = load_config(self.root)
        self.assertEqual(config.hours_per_day, 8.0)
        self.assertEqual(config.prompt_time, "15:30")
        self.assertEqual(config.theme, "dark")

    def test_a_partial_file_keeps_defaults_for_what_it_omits(self):
        self.write("config.toml", '[schedule]\nhours_per_day = 6.0\n')
        config = load_config(self.root)

        self.assertEqual(config.hours_per_day, 6.0)
        self.assertEqual(config.theme, "dark")

    def test_jql_defaults_are_present_when_unspecified(self):
        config = load_config(self.root)
        self.assertIn("currentUser()", config.jql["assigned"])
        self.assertIn("statusCategory != Done", config.jql["internal"])

    def test_internal_jql_default_follows_the_configured_project(self):
        self.write("config.toml", '[internal]\nproject = "ADM"\n')
        self.assertIn("project = ADM", load_config(self.root).jql["internal"])

    def test_explicit_internal_jql_wins_over_the_generated_one(self):
        self.write("config.toml",
                   '[internal]\nproject = "AI"\n\n[jql]\ninternal = "project in (AI, ADM)"\n')
        self.assertEqual(load_config(self.root).jql["internal"], "project in (AI, ADM)")

    def test_unreadable_config_falls_back_to_defaults_rather_than_crashing(self):
        # A stray character in a hand-edited file must not stop the prompt.
        self.write("config.toml", "this is not [valid toml")
        self.assertEqual(load_config(self.root).hours_per_day, 8.0)


class LoadingCredentials(ConfigTestCase):
    def test_returns_both_tokens(self):
        self.write("credentials.toml",
                   'jira_api_token = "abc"\ntempo_api_token = "xyz"\n')
        jira_token, tempo_token = load_credentials(self.root)

        self.assertEqual(jira_token, "abc")
        self.assertEqual(tempo_token, "xyz")

    def test_missing_file_explains_what_to_create(self):
        with self.assertRaises(MissingCredentials) as caught:
            load_credentials(self.root)
        self.assertIn("credentials.toml", str(caught.exception))

    def test_blank_jira_token_is_reported_by_name(self):
        self.write("credentials.toml",
                   'jira_api_token = ""\ntempo_api_token = "xyz"\n')
        with self.assertRaises(MissingCredentials) as caught:
            load_credentials(self.root)
        self.assertIn("jira_api_token", str(caught.exception))

    def test_blank_tempo_token_is_reported_by_name(self):
        self.write("credentials.toml",
                   'jira_api_token = "abc"\ntempo_api_token = "   "\n')
        with self.assertRaises(MissingCredentials) as caught:
            load_credentials(self.root)
        self.assertIn("tempo_api_token", str(caught.exception))

    def test_the_message_says_where_to_get_a_token(self):
        with self.assertRaises(MissingCredentials) as caught:
            load_credentials(self.root)
        self.assertIn("id.atlassian.com", str(caught.exception))

    def test_tokens_are_stripped_of_stray_whitespace(self):
        # Copy-paste from a browser routinely brings a trailing newline, which
        # otherwise produces a baffling 401.
        self.write("credentials.toml",
                   'jira_api_token = " abc\\n"\ntempo_api_token = "xyz "\n')
        self.assertEqual(load_credentials(self.root), ("abc", "xyz"))

    def test_the_exception_never_contains_a_token_value(self):
        self.write("credentials.toml",
                   'jira_api_token = "SECRET-VALUE"\ntempo_api_token = ""\n')
        with self.assertRaises(MissingCredentials) as caught:
            load_credentials(self.root)
        self.assertNotIn("SECRET-VALUE", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
