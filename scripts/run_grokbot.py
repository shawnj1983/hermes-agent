#!/usr/bin/env python3
"""Run Grokbot from the repo root: python3 scripts/run_grokbot.py --keys"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from grokbot.app import main

if __name__ == "__main__":
    raise SystemExit(main())
