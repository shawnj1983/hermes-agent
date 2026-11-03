"""Load Shawn's own API keys and print a short create-your-own guide.

Never prints or returns secret values — only names and present/missing.
Existing process environment wins over a local ``.env`` file.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parent.parent


@dataclass(frozen=True)
class KeySpec:
    name: str
    aliases: tuple[str, ...]
    provider: str
    signup_url: str
    key_url: str
    how: str


KEY_SPECS: tuple[KeySpec, ...] = (
    KeySpec(
        name="XAI_API_KEY",
        aliases=("GROK_API_KEY",),
        provider="xAI (Grok)",
        signup_url="https://accounts.x.ai/sign-up",
        key_url="https://console.x.ai/",
        how="Open console.x.ai → API Keys → Create API key. Grokbot ranking uses this.",
    ),
    KeySpec(
        name="OPENAI_API_KEY",
        aliases=(),
        provider="OpenAI",
        signup_url="https://platform.openai.com/signup",
        key_url="https://platform.openai.com/api-keys",
        how="platform.openai.com → API keys → Create new secret key.",
    ),
    KeySpec(
        name="ANTHROPIC_API_KEY",
        aliases=("ANTHROPIC_TOKEN",),
        provider="Anthropic",
        signup_url="https://console.anthropic.com/",
        key_url="https://console.anthropic.com/settings/keys",
        how="console.anthropic.com → Settings → API keys → Create key.",
    ),
    KeySpec(
        name="GEMINI_API_KEY",
        aliases=("GOOGLE_API_KEY", "GOOGLE_GENERATIVE_AI_API_KEY"),
        provider="Google Gemini",
        signup_url="https://aistudio.google.com/",
        key_url="https://aistudio.google.com/apikey",
        how="aistudio.google.com → Get API key. Same Google key can also unlock YouTube Data API.",
    ),
    KeySpec(
        name="MISTRAL_API_KEY",
        aliases=(),
        provider="Mistral",
        signup_url="https://console.mistral.ai/",
        key_url="https://console.mistral.ai/api-keys",
        how="console.mistral.ai → API keys → Create new key.",
    ),
    KeySpec(
        name="GITHUB_TOKEN",
        aliases=("GH_TOKEN",),
        provider="GitHub",
        signup_url="https://github.com/signup",
        key_url="https://github.com/settings/tokens",
        how="Settings → Developer settings → Personal access tokens. Fine-grained: public repo read. Or use `gh auth login`.",
    ),
    KeySpec(
        name="YOUTUBE_API_KEY",
        aliases=("GOOGLE_API_KEY",),
        provider="YouTube Data API",
        signup_url="https://console.cloud.google.com/",
        key_url="https://console.cloud.google.com/apis/credentials",
        how="Enable YouTube Data API v3, then Credentials → Create credentials → API key.",
    ),
)


def parse_dotenv(text: str) -> dict[str, str]:
    """Parse KEY=VALUE lines. Values are never logged."""
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        key, _, value = line.partition("=")
        key = key.strip()
        if not key or key.startswith("#"):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        out[key] = value
    return out


def dotenv_search_paths() -> list[Path]:
    paths: list[Path] = []
    override = os.environ.get("GROKBOT_ENV")
    if override:
        paths.append(Path(override).expanduser())
    paths.extend(
        [
            PACKAGE_DIR / ".env",
            REPO_ROOT / ".env",
            Path.home() / ".hermes" / ".env",
        ]
    )
    # Preserve order, drop dupes.
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in paths:
        resolved = path.resolve() if path.exists() else path
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(path)
    return unique


def load_dotenv(paths: list[Path] | None = None) -> list[str]:
    """Fill missing os.environ keys from the first readable .env files.

    Does not override variables already set in the process environment.
    Returns the file names that contributed at least one key (not the values).
    """
    loaded_from: list[str] = []
    for path in paths or dotenv_search_paths():
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        added = False
        for key, value in parse_dotenv(text).items():
            if not value:
                continue
            if key in os.environ and os.environ[key]:
                continue
            os.environ[key] = value
            added = True
        if added:
            loaded_from.append(str(path))
    _promote_aliases()
    return loaded_from


def _promote_aliases() -> None:
    """If a canonical name is empty, copy from a known alias already in env."""
    for spec in KEY_SPECS:
        if os.environ.get(spec.name):
            continue
        for alias in spec.aliases:
            value = os.environ.get(alias)
            if value:
                os.environ[spec.name] = value
                break


def key_is_set(spec: KeySpec) -> bool:
    if os.environ.get(spec.name):
        return True
    return any(bool(os.environ.get(alias)) for alias in spec.aliases)


def keys_status() -> list[tuple[str, str, bool]]:
    """Return (provider, env_name, present) — never the secret."""
    return [(spec.provider, spec.name, key_is_set(spec)) for spec in KEY_SPECS]


def format_keys_guide() -> str:
    lines = [
        "Create your own API keys (do not paste anyone else's).",
        "Put them in scripts/grokbot/.env or export them in the shell.",
        "",
    ]
    for spec in KEY_SPECS:
        alias = f" (or {', '.join(spec.aliases)})" if spec.aliases else ""
        lines.append(f"{spec.provider}")
        lines.append(f"  env: {spec.name}{alias}")
        lines.append(f"  sign up: {spec.signup_url}")
        lines.append(f"  create key: {spec.key_url}")
        lines.append(f"  {spec.how}")
        lines.append("")
    lines.append("Grokbot ranking needs XAI_API_KEY. GitHub and YouTube keys are optional.")
    lines.append("Missing keys fall back: anonymous GitHub, YouTube oEmbed/RSS, heuristic rank.")
    return "\n".join(lines).rstrip() + "\n"


def format_keys_status() -> str:
    lines = ["Loaded keys (names only):"]
    for provider, name, present in keys_status():
        flag = "set" if present else "missing"
        lines.append(f"  {name:<18} {flag:<7}  {provider}")
    return "\n".join(lines) + "\n"
