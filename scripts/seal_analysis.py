#!/usr/bin/env python3
"""Seal Phase 8 analyzed results and write the Phase 9 handoff (P8-09)."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.seal_analysis import main

if __name__ == "__main__":
    raise SystemExit(main())
