"""Unit tests for Grokbot helpers. No live network, no secret values."""

from __future__ import annotations

import io
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))

from grokbot.app import (  # noqa: E402
    Repo,
    Video,
    _parse_grok_notes,
    cross_reference,
    extract_github_repos,
    extract_youtube_ids,
    main,
    render_text,
    repo_activity_score,
)
from grokbot.keys import format_keys_status, load_dotenv, parse_dotenv  # noqa: E402


class ExtractTests(unittest.TestCase):
    def test_youtube_ids(self):
        text = "see https://youtu.be/abcdefghijk and https://www.youtube.com/watch?v=abcdefghijk"
        self.assertEqual(extract_youtube_ids(text), ["abcdefghijk"])

    def test_github_repos_strips_git_suffix(self):
        text = "clone https://github.com/foo/bar.git"
        self.assertEqual(extract_github_repos(text), ["foo/bar"])


class ScoreTests(unittest.TestCase):
    def test_more_stars_rank_higher(self):
        hot = Repo("a/b", "https://github.com/a/b", "", stars=500, forks=10, pushed_at="2026-11-01T00:00:00Z")
        cold = Repo("c/d", "https://github.com/c/d", "", stars=1, forks=0, pushed_at="2020-01-01T00:00:00Z")
        self.assertGreater(repo_activity_score(hot), repo_activity_score(cold))


class CrossRefTests(unittest.TestCase):
    def test_readme_video_links_the_repo(self):
        repo = Repo("nous/hermes", "https://github.com/nous/hermes", "agent", 10, 1, "2026-11-01T00:00:00Z")
        repo.youtube_ids = ["abcdefghijk"]
        repo.score = 10
        video = Video("abcdefghijk", "Hermes demo", "Nous", "https://www.youtube.com/watch?v=abcdefghijk")
        orphan = Repo("other/tool", "https://github.com/other/tool", "cli", 2, 0, "2026-10-01T00:00:00Z")
        orphan.score = 2
        hits = cross_reference([repo, orphan], [video])
        self.assertEqual(hits[0].repo.full_name, "nous/hermes")
        self.assertEqual(hits[0].videos[0].video_id, "abcdefghijk")
        self.assertEqual({h.repo.full_name for h in hits}, {"nous/hermes", "other/tool"})


class GrokParseTests(unittest.TestCase):
    def test_fenced_json(self):
        notes = _parse_grok_notes('```json\n[{"repo":"a/b","note":"ok","keep":true}]\n```')
        self.assertEqual(notes[0]["repo"], "a/b")


class DotenvTests(unittest.TestCase):
    def test_parse_skips_comments_and_export(self):
        parsed = parse_dotenv('export XAI_API_KEY="abc"\n# OPENAI_API_KEY=nope\nOPENAI_API_KEY=\n')
        self.assertEqual(parsed["XAI_API_KEY"], "abc")
        self.assertEqual(parsed["OPENAI_API_KEY"], "")
        self.assertNotIn("nope", parsed.values())

    def test_load_does_not_override_existing_env(self):
        env_file = Path(self.id().replace(".", "_") + ".env")
        self.addCleanup(lambda: env_file.unlink(missing_ok=True))
        env_file.write_text("XAI_API_KEY=from-file\n")
        with patch.dict(os.environ, {"XAI_API_KEY": "from-shell"}, clear=False):
            load_dotenv([env_file])
            self.assertEqual(os.environ["XAI_API_KEY"], "from-shell")

    def test_status_never_includes_secret(self):
        with patch.dict(os.environ, {"XAI_API_KEY": "sk-secret-should-not-appear"}, clear=False):
            text = format_keys_status()
            self.assertNotIn("sk-secret", text)
            self.assertIn("XAI_API_KEY", text)
            self.assertIn("set", text)


class CliTests(unittest.TestCase):
    def test_keys_flag_exits_zero(self):
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            code = main(["--keys"])
        self.assertEqual(code, 0)
        out = buf.getvalue()
        self.assertIn("XAI_API_KEY", out)
        self.assertIn("console.x.ai", out)

    def test_render_omits_key_values(self):
        text = render_text(
            {
                "query": "demo",
                "model": None,
                "youtube_api": False,
                "github_authenticated": False,
                "top_repos": [],
            }
        )
        self.assertNotIn("sk-", text)


if __name__ == "__main__":
    unittest.main()
