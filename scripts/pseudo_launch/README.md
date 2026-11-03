# Pseudo-launch bootstrap bot

There is **no separate service** in this checkout named “pseudo-launch”.
What exists is Hermes’ own first-launch / launchd stack:

| Piece | Where | State on the cloud VM |
|---|---|---|
| First-launch desktop bootstrap | `apps/desktop/electron/bootstrap-runner.ts`, `scripts/install.sh` | Code only; no install ran here |
| Bootstrap-complete marker | `~/.hermes/.hermes-bootstrap-complete` | Not present (`~/.hermes` missing) |
| Gateway launchd unit | `~/Library/LaunchAgents/ai.hermes.gateway.plist` | Not present (this VM is Linux) |
| Running gateway | `hermes gateway` / `gateway.run` | None |

`bootstrap_bot.py` is inspect-only. It does not start, stop, or restart
anything.

```bash
python3 scripts/pseudo_launch/bootstrap_bot.py
python3 scripts/pseudo_launch/bootstrap_bot.py --json
python3 scripts/pseudo_launch/bootstrap_bot.py --write-template   # print a plist; does not load it
```

On a Mac, install a real supervised gateway with `hermes gateway install`
(that *will* talk to launchd). This bot will not do that for you.
