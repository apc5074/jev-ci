"""Freeze lock for evaluation-mode work (P6-06 / P6-07).

Evaluation extraction, ranking, and scoring must not run until
``results/phase6/freeze_lock.json`` records a validated ``experiment-v1``
tag (written by P6-07 after commit/tag). The pre-eval gate may run without
unlocking evaluation.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Mapping

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.example_contract import WORKSPACE, ExampleContractError, read_json

FREEZE_LOCK_PATH = WORKSPACE / "results" / "phase6" / "freeze_lock.json"
REQUIRED_TAG = "experiment-v1"


class FreezeGuardError(ExampleContractError):
    """Evaluation requested before the experiment freeze lock is present."""


def load_freeze_lock(*, path: Path | None = None) -> dict[str, Any] | None:
    target = path or FREEZE_LOCK_PATH
    if not target.is_file():
        return None
    return read_json(target)


def evaluation_is_unlocked(*, path: Path | None = None) -> bool:
    doc = load_freeze_lock(path=path)
    if not doc:
        return False
    return bool(
        doc.get("tag") == REQUIRED_TAG
        and doc.get("validated") is True
        and doc.get("commit_sha")
    )


def assert_evaluation_allowed(*, path: Path | None = None) -> dict[str, Any]:
    """Raise if evaluation-mode work is attempted before freeze."""
    doc = load_freeze_lock(path=path)
    if doc is None:
        raise FreezeGuardError(
            "evaluation blocked: missing results/phase6/freeze_lock.json "
            f"(create after tagging {REQUIRED_TAG} in P6-07)"
        )
    if doc.get("tag") != REQUIRED_TAG:
        raise FreezeGuardError(
            f"evaluation blocked: freeze tag is {doc.get('tag')!r}, "
            f"expected {REQUIRED_TAG!r}"
        )
    if doc.get("validated") is not True:
        raise FreezeGuardError(
            "evaluation blocked: freeze_lock.validated is not true"
        )
    if not doc.get("commit_sha"):
        raise FreezeGuardError(
            "evaluation blocked: freeze_lock.commit_sha is required"
        )
    return doc


def freeze_lock_summary(*, path: Path | None = None) -> dict[str, Any]:
    doc = load_freeze_lock(path=path)
    return {
        "path": str((path or FREEZE_LOCK_PATH).relative_to(WORKSPACE)),
        "present": doc is not None,
        "unlocked": evaluation_is_unlocked(path=path),
        "tag": (doc or {}).get("tag"),
        "commit_sha": (doc or {}).get("commit_sha"),
        "validated": (doc or {}).get("validated"),
    }
