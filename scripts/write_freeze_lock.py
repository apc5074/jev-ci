#!/usr/bin/env python3
"""Write results/phase6/freeze_lock.json after tagging experiment-v1.

Run this *after* the annotated freeze tag exists. Do not include freeze_lock.json
in the commit that the tag points at (no self-referential freeze SHA in that tree).

Usage:
    python scripts/write_freeze_lock.py
    python scripts/write_freeze_lock.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.freeze_guard import REQUIRED_TAG, evaluation_is_unlocked

LOCK_PATH = _REPO_ROOT / "results" / "phase6" / "freeze_lock.json"


def _git(*args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=_REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise SystemExit(
            f"git {' '.join(args)} failed: {proc.stderr.strip() or proc.stdout.strip()}"
        )
    return proc.stdout.strip()


def build_freeze_lock(*, tag: str = REQUIRED_TAG) -> dict:
    commit_sha = _git("rev-parse", tag)
    # Prefer the peeled commit object for annotated tags.
    peeled = _git("rev-parse", f"{tag}^{{commit}}")
    if peeled:
        commit_sha = peeled
    tag_message = _git("tag", "-l", "--format=%(contents:subject)", tag)
    return {
        "schema_version": "jev-phase6-freeze-lock-v1",
        "tag": tag,
        "commit_sha": commit_sha,
        "validated": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "tag_subject": tag_message or None,
        "notes": (
            "Written after experiment-v1. Unlock evaluation for Phase 7. "
            "Keep this file out of the tagged freeze commit."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the lock document without writing.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing freeze_lock.json.",
    )
    args = parser.parse_args(argv)

    tags = _git("tag", "-l", REQUIRED_TAG)
    if REQUIRED_TAG not in tags.splitlines():
        raise SystemExit(
            f"missing git tag {REQUIRED_TAG!r}; commit and tag first, then re-run"
        )

    doc = build_freeze_lock()
    text = json.dumps(doc, indent=2, sort_keys=False) + "\n"
    if args.dry_run:
        sys.stdout.write(text)
        return 0

    if LOCK_PATH.is_file() and not args.force:
        if evaluation_is_unlocked(path=LOCK_PATH):
            print(f"already unlocked: {LOCK_PATH}", file=sys.stderr)
            return 0
        raise SystemExit(
            f"{LOCK_PATH} exists but is not valid; pass --force to overwrite"
        )

    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOCK_PATH.write_text(text, encoding="utf-8")
    print(f"wrote {LOCK_PATH.relative_to(_REPO_ROOT)}")
    print(f"tag={doc['tag']} commit_sha={doc['commit_sha']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
