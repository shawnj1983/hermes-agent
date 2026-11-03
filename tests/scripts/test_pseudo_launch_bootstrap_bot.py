"""Inspect-only contract for the pseudo-launch bootstrap bot."""

from __future__ import annotations

import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "pseudo_launch"))

import bootstrap_bot  # noqa: E402


class BootstrapBotTests(unittest.TestCase):
    def test_inspect_does_not_claim_to_mutate(self):
        status = bootstrap_bot.inspect()
        self.assertEqual(status["action"], "inspect-only")
        self.assertIsInstance(status["gateway_pids"], list)
        self.assertIn("what_this_is", status)

    def test_main_json_round_trip(self):
        with patch("sys.stdout", io.StringIO()):
            self.assertEqual(bootstrap_bot.main(["--json"]), 0)

    def test_write_template_is_plist_not_loaded(self):
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            self.assertEqual(bootstrap_bot.main(["--write-template"]), 0)
        out = buf.getvalue()
        self.assertIn("ai.hermes.gateway", out)
        self.assertNotIn("launchctl bootstrap", out)

    def test_render_mentions_no_restart(self):
        text = bootstrap_bot.render(bootstrap_bot.inspect())
        self.assertIn("Nothing was started, stopped, or restarted", text)


if __name__ == "__main__":
    unittest.main()
