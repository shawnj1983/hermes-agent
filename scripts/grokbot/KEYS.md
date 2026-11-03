# Grokbot API keys — create your own

Do not paste or reuse anyone else's keys. Grokbot reads **your** keys from
the process environment or a local `.env` (see `.env.example`). It never
prints the values.

Copy `.env.example` to `.env` in this folder and fill in only the keys you own.

| Provider | Sign up | Create the key | Env var |
|---|---|---|---|
| xAI (Grok) | https://accounts.x.ai/sign-up | https://console.x.ai/ → **API Keys** | `XAI_API_KEY` |
| OpenAI | https://platform.openai.com/signup | https://platform.openai.com/api-keys | `OPENAI_API_KEY` |
| Anthropic | https://console.anthropic.com/ | https://console.anthropic.com/settings/keys | `ANTHROPIC_API_KEY` |
| Google Gemini | https://aistudio.google.com/ | https://aistudio.google.com/apikey | `GEMINI_API_KEY` or `GOOGLE_API_KEY` |
| Mistral | https://console.mistral.ai/ | https://console.mistral.ai/api-keys | `MISTRAL_API_KEY` |
| GitHub | https://github.com/signup | https://github.com/settings/tokens (or `gh auth login`) | `GITHUB_TOKEN` |
| YouTube Data API | https://console.cloud.google.com/ | Enable **YouTube Data API v3**, then **Credentials → API key** | `YOUTUBE_API_KEY` |

Grok ranking needs `XAI_API_KEY`. GitHub and YouTube are optional; without
them Grokbot uses anonymous GitHub search and official YouTube oEmbed/RSS.

Check what is loaded (names only):

```bash
python3 -m grokbot --keys
```

## Sweep a Mac (copy this file only)

`vault_sweep.py` is standalone. Copy it to the Mac, then:

```bash
python3 vault_sweep.py
python3 vault_sweep.py --root ~/Projects --root ~/src
```

It reports key **names**, **paths**, and **providers** only — never values — and lists anything named Jarvis or Alfred. Do not run it if you do not want those locations printed on that machine.
