#!/usr/bin/env python3
"""CLI for P5-01 Jev provider verification. See ``src/jev_providers.py``."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.jev_providers import main

if __name__ == "__main__":
    sys.exit(main())
