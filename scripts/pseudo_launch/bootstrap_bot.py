#!/usr/bin/env python3
"""Inspect-only bot for Shawn's Hermes launch / first-launch bootstrap stack.

There is no separate product in this repo named "pseudo-launch". The closest
live system is:

* Desktop first-launch bootstrap (``apps/desktop`` + ``scripts/install.sh``)
* The ``.hermes-bootstrap-complete`` marker a finished install writes
* macOS ``launchd`` gateway supervision (``ai.hermes.gateway*.plist``)

Default mode is **status only**. It never bootstraps, bootouts, or restarts
a running gateway. Pass ``--write-template`` to print a launchd plist to
stdout without loading it.

Usage:
    python3 scripts/pseudo_launch/bootstrap_bot.py
    python3 scripts/pseudo_launch/bootstrap_bot.py --json
    python3 scripts/pseudo_launch/bootstrap_bot.py --write-template
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

MARKER_NAME = ".hermes-bootstrap-complete"
GATEWAY_PLIST = "ai.hermes.gateway.plist"


def hermes_home() -> Path:
    env = os.environ.get("HERMES_HOME")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".hermes"


def launchd_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / GATEWAY_PLIST


def _run(cmd: list[str], timeout: int = 8) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def running_gateway_pids() -> list[int]:
    """Read-only process list. Does not signal anything."""
    pids: list[int] = []
    if shutil.which("pgrep"):
        code, out = _run(["pgrep", "-f", "gateway.run|hermes gateway"])
        if code == 0:
            for line in out.splitlines():
                line = line.strip()
                if line.isdigit():
                    pids.append(int(line))
    return pids


def inspect() -> dict[str, Any]:
    home = hermes_home()
    marker = home / MARKER_NAME
    # install.sh also writes the marker next to a managed checkout
    checkout_marker = Path.home() / "hermes-agent" / MARKER_NAME
    plist = launchd_plist_path()
    pids = running_gateway_pids()
    launchctl = shutil.which("launchctl")
    launchctl_print = None
    if launchctl and sys.platform == "darwin":
        uid = os.getuid()
        code, out = _run([launchctl, "print", f"gui/{uid}/{GATEWAY_PLIST.removesuffix('.plist')}"])
        # Do not dump the full print (can be huge). Only say loaded or not.
        launchctl_print = "loaded" if code == 0 else "not-loaded"

    return {
        "what_this_is": (
            "Hermes first-launch bootstrap + optional macOS launchd gateway. "
            "No separate pseudo-launch service exists in the workspace."
        ),
        "hermes_home": str(home),
        "hermes_home_exists": home.is_dir(),
        "bootstrap_marker": str(marker),
        "bootstrap_complete": marker.is_file() or checkout_marker.is_file(),
        "launchd_plist": str(plist),
        "launchd_plist_present": plist.is_file(),
        "launchctl": launchctl_print or ("unavailable" if not launchctl else "not-macos"),
        "gateway_pids": pids,
        "gateway_running": bool(pids),
        "action": "inspect-only",
    }


def launchd_template() -> str:
    program = shutil.which("hermes") or "/usr/local/bin/hermes"
    label = GATEWAY_PLIST.removesuffix(".plist")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>{label}</string>
  <key>ProgramArguments</key>
  <array>
    <string>{program}</string>
    <string>gateway</string>
    <string>run</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>{Path.home() / ".hermes" / "logs" / "gateway.launchd.out.log"}</string>
  <key>StandardErrorPath</key>
  <string>{Path.home() / ".hermes" / "logs" / "gateway.launchd.err.log"}</string>
</dict>
</plist>
"""


def render(status: dict[str, Any]) -> str:
    lines = [
        "Pseudo-launch bootstrap bot — inspect only",
        status["what_this_is"],
        "",
        f"HERMES_HOME:          {status['hermes_home']} ({'yes' if status['hermes_home_exists'] else 'missing'})",
        f"Bootstrap marker:     {'complete' if status['bootstrap_complete'] else 'not written'}",
        f"launchd plist:        {'present' if status['launchd_plist_present'] else 'absent'} ({status['launchd_plist']})",
        f"launchctl:            {status['launchctl']}",
        f"Gateway processes:    {status['gateway_pids'] or 'none'}",
        "",
        "Nothing was started, stopped, or restarted.",
        "To print a launchd plist without loading it:  --write-template",
        "To actually supervise a gateway, use `hermes gateway install` on that Mac.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect Hermes first-launch / launchd bootstrap. No restarts.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--write-template",
        action="store_true",
        help="Print a launchd plist to stdout. Does not load or replace a running service.",
    )
    args = parser.parse_args(argv)
    status = inspect()
    if args.write_template:
        sys.stdout.write(launchd_template())
        return 0
    sys.stdout.write(json.dumps(status, indent=2) + "\n" if args.json else render(status))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
