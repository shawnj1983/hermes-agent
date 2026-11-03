#!/usr/bin/env python3
"""Shawn's Mac vault sweep — names, paths, and providers only.

Copy this single file to a Mac and run it there. Do not commit the output
if a later edit ever starts printing values (this script never should).

Usage:
    python3 vault_sweep.py
    python3 vault_sweep.py --root ~/Projects --root ~/src
    python3 vault_sweep.py --json

Never prints secret values. Existing process env is reported as set/missing
only. File hits are classified empty / placeholder / present (length only).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

PROVIDERS: dict[str, str] = {
    "OPENAI_API_KEY": "OpenAI",
    "ANTHROPIC_API_KEY": "Anthropic",
    "ANTHROPIC_TOKEN": "Anthropic",
    "XAI_API_KEY": "xAI (Grok)",
    "GROK_API_KEY": "xAI (Grok)",
    "GEMINI_API_KEY": "Google Gemini",
    "GOOGLE_API_KEY": "Google Gemini / YouTube",
    "GOOGLE_GENERATIVE_AI_API_KEY": "Google Gemini",
    "MISTRAL_API_KEY": "Mistral",
    "GITHUB_TOKEN": "GitHub",
    "GH_TOKEN": "GitHub",
    "YOUTUBE_API_KEY": "YouTube Data API",
    "ZAPIER_API_KEY": "Zapier",
    "ZAPIER_API_TOKEN": "Zapier",
    "ZAPIER_TOKEN": "Zapier",
    "ZAPIER_KEY": "Zapier",
    "ZAPIER_MCP": "Zapier MCP",
    "ZAPIER_MCP_URL": "Zapier MCP",
    "ZAPIER_MCP_TOKEN": "Zapier MCP",
    "ZAPIER_NLA_API_KEY": "Zapier",
    "ZAPIER_CLIENT_ID": "Zapier",
    "ZAPIER_CLIENT_SECRET": "Zapier",
    "OPENROUTER_API_KEY": "OpenRouter",
    "OPENROUTER_KEY": "OpenRouter",
    "OPENROUTER_TOKEN": "OpenRouter",
}

KEY_RE = re.compile(r"\b(" + "|".join(re.escape(k) for k in PROVIDERS) + r")\b")
ASSIGN_RE = re.compile(
    r"^(?:export\s+)?(" + "|".join(re.escape(k) for k in PROVIDERS) + r")\s*=\s*(.*)$"
)
SKIP_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    ".cache",
    "Library/Caches",
    "Library/Logs",
    "site-packages",
    "dist",
    "build",
    ".npm",
    "iCloud Drive",
}
SHELL_NAMES = {
    ".bashrc",
    ".zshrc",
    ".zprofile",
    ".zshenv",
    ".bash_profile",
    ".profile",
    ".bash_env",
}
ENV_PREFIX = ".env"


def classify(value: str) -> str:
    text = value.strip().strip("\"'").strip()
    if not text:
        return "empty"
    upper = text.upper()
    if (
        text.startswith("${")
        or "YOUR_" in upper
        or text.endswith("_HERE")
        or text.lower() in {"xxx", "todo", "changeme", "<token>", "<key>", "<your-key>"}
    ):
        return "placeholder"
    return f"present (len={len(text)})"


def should_skip_dir(path: Path) -> bool:
    parts = set(path.parts)
    if parts & SKIP_DIRS:
        return True
    name = path.name
    return name in SKIP_DIRS or name.endswith(".app")


def iter_files(roots: list[Path], max_files: int = 8000):
    seen = 0
    for root in roots:
        if not root.exists():
            continue
        if root.is_file():
            yield root
            continue
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            current = Path(dirpath)
            if should_skip_dir(current):
                dirnames[:] = []
                continue
            dirnames[:] = [name for name in dirnames if not should_skip_dir(current / name)]
            for name in filenames:
                path = current / name
                seen += 1
                if seen > max_files:
                    return
                yield path


def interesting_file(path: Path) -> bool:
    name = path.name
    if name in SHELL_NAMES or name.startswith(ENV_PREFIX):
        return True
    if name in {"credentials", "credentials.yml", "secrets.yaml", "secrets.yml", "hosts.yml"}:
        return True
    if path.suffix in {".env", ".pem"}:
        return True
    return False


def read_text(path: Path, limit: int = 200_000) -> str | None:
    try:
        if not path.is_file():
            return None
        if path.stat().st_size > 2_000_000:
            return None
        data = path.read_bytes()[:limit]
    except OSError:
        return None
    if b"\x00" in data[:1024]:
        return None
    return data.decode("utf-8", errors="replace")


def default_roots(extra: list[Path]) -> list[Path]:
    home = Path.home()
    roots = [
        home / ".bashrc",
        home / ".zshrc",
        home / ".zprofile",
        home / ".zshenv",
        home / ".bash_profile",
        home / ".profile",
        home / ".env",
        home / ".hermes" / ".env",
        home / ".config",
        home / ".cursor",
        Path.cwd(),
    ]
    # Common Mac project homes — shallow walk via iter_files max cap.
    for name in ("Projects", "Developer", "src", "code", "dev", "Documents"):
        roots.append(home / name)
    roots.extend(extra)
    # Dedup while keeping order.
    out: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        try:
            key = root.expanduser().resolve()
        except OSError:
            key = root.expanduser()
        if key in seen:
            continue
        seen.add(key)
        out.append(root.expanduser())
    return out


def sweep_keys(roots: list[Path]) -> list[dict[str, str]]:
    hits: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    for key, provider in PROVIDERS.items():
        raw = os.environ.get(key)
        if raw:
            row = (key, provider, "process environment", classify(raw))
            if row not in seen:
                seen.add(row)
                hits.append(
                    {
                        "name": key,
                        "provider": provider,
                        "path": "process environment",
                        "status": classify(raw),
                    }
                )

    for path in iter_files(roots):
        if not interesting_file(path):
            continue
        text = read_text(path)
        if not text:
            continue
        for line in text.splitlines():
            match = ASSIGN_RE.match(line.strip())
            if not match:
                continue
            name, value = match.group(1), match.group(2)
            row = (name, PROVIDERS[name], str(path), classify(value))
            if row in seen:
                continue
            seen.add(row)
            hits.append(
                {
                    "name": name,
                    "provider": PROVIDERS[name],
                    "path": str(path),
                    "status": classify(value),
                }
            )
    return hits


def sweep_names(roots: list[Path], needles: tuple[str, ...] = ("jarvis", "alfred")) -> list[str]:
    found: list[str] = []
    extra = [
        Path.home() / "Library" / "LaunchAgents",
        Path.home() / "Library" / "LaunchDaemons",
        Path("/Library/LaunchAgents"),
        Path("/Library/LaunchDaemons"),
        Path("/Applications"),
        Path("/opt/homebrew"),
        Path("/usr/local"),
    ]
    for path in iter_files(roots + extra, max_files=12000):
        lower = path.name.lower()
        if any(needle in lower for needle in needles):
            found.append(str(path))
        if len(found) >= 200:
            break
    # Directories whose name matches even if we skipped walking inside .app
    for root in extra:
        if not root.is_dir():
            continue
        try:
            for child in root.iterdir():
                if any(needle in child.name.lower() for needle in needles):
                    found.append(str(child))
        except OSError:
            continue
    # Unique, stable order.
    return list(dict.fromkeys(found))


def render_text(keys: list[dict[str, str]], names: list[str]) -> str:
    lines = [
        "Vault sweep — names, paths, providers only. No secret values.",
        "",
        "API keys",
    ]
    if not keys:
        lines.append("  none found")
    else:
        for item in keys:
            lines.append(
                f"  {item['name']:<28} {item['status']:<20} {item['provider']:<22} {item['path']}"
            )
    lines.extend(["", "Jarvis / Alfred name hits"])
    if not names:
        lines.append("  none found")
    else:
        lines.extend(f"  {path}" for path in names)
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Find API key *names* and Jarvis/Alfred paths. Never prints secrets."
    )
    parser.add_argument(
        "--root",
        action="append",
        default=[],
        type=Path,
        help="Extra directory to search (repeatable)",
    )
    parser.add_argument("--json", action="store_true", help="Machine-readable output")
    args = parser.parse_args(argv)

    roots = default_roots(list(args.root))
    keys = sweep_keys(roots)
    names = sweep_names(roots)
    if args.json:
        sys.stdout.write(json.dumps({"keys": keys, "jarvis_alfred": names}, indent=2) + "\n")
    else:
        sys.stdout.write(render_text(keys, names))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
