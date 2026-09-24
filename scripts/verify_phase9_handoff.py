#!/usr/bin/env python3
"""Verify Phase 8 handoff and write the Phase 9 headline table (P9-01)."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.phase9_handoff import main

if __name__ == "__main__":
    raise SystemExit(main())
