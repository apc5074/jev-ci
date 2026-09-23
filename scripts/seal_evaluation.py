#!/usr/bin/env python3
"""Audit and seal Phase 7 evaluation raw results (P7-09)."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.seal_evaluation import main

if __name__ == "__main__":
    raise SystemExit(main())
