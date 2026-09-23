#!/usr/bin/env python3
"""Validate sealed Phase 7 inputs for offline Phase 8 evaluation (P8-01)."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.evaluation_inputs import main

if __name__ == "__main__":
    raise SystemExit(main())
