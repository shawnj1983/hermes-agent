"""Guards against accidental host-path and transcript injections in source files.

Three commits on this fork pasted a local checkout path into the scheduler
import and .dockerignore, and a voice transcript over the batch runner
shebang. Those files must stay valid Python and must not embed absolute
user-home paths.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_scheduler_module_parses_and_imports_concurrent_futures():
    source = _source("cron/scheduler.py")
    compile(source, "cron/scheduler.py", "exec")
    assert "import concurrent.futures\n" in source
    assert "/Users/" not in source


def test_batch_runner_parses_and_starts_with_shebang():
    source = _source("batch_runner.py")
    compile(source, "batch_runner.py", "exec")
    assert source.startswith("#!/usr/bin/env python3\n")
    assert "/Users/" not in source


def test_dockerignore_has_no_absolute_user_home_paths():
    text = _source(".dockerignore")
    offenders = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("/Users/") or stripped.startswith("/home/"):
            offenders.append(stripped)
    assert offenders == []
