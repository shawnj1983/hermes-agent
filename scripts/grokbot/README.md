# Grokbot

Ranks public GitHub repos against official YouTube listings using Grok.

```bash
python3 scripts/run_grokbot.py --keys
python3 scripts/run_grokbot.py "open source ai agent" --limit 10
python3 scripts/run_grokbot.py "yt-dlp" --no-grok --json
```

Keys load from the process environment, then `scripts/grokbot/.env`,
repo-root `.env`, and `~/.hermes/.env`. Existing env vars win. Values
are never printed. See `KEYS.md` and `.env.example`.

Missing keys fall back: anonymous GitHub, YouTube oEmbed/RSS, heuristic rank.
