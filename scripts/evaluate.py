#!/usr/bin/env python3
"""Regenerate Phase 8 results offline from the sealed Phase 7 snapshot.

Requires no API credentials and makes zero provider calls.

Example (network disabled):

  docker run --rm --platform linux/amd64 --network=none \\
    -v "$(pwd):/workspace" -w /workspace \\
    jev-ci:phase1 python -u scripts/evaluate.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.evaluate import main

if __name__ == "__main__":
    raise SystemExit(main())
