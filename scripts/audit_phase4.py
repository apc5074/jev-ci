#!/usr/bin/env python3
"""CLI entry for Phase 4 retrieval audit. See ``src/audit_phase4.py``."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.audit_phase4 import main

if __name__ == "__main__":
    sys.exit(main())
