#!/usr/bin/env python3
"""Audit Jev shortlist score completeness for a manifest split (P7-05)."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.candidates import load_candidates
from src.embeddings import load_patch_representation_text, load_test_representation_texts
from src.example_contract import (
    WORKSPACE,
    ExampleId,
    atomic_write_json,
    development_example_ids,
    load_manifest,
)
from src.freeze_guard import assert_evaluation_allowed
from src.jev_ranker import JEV_PROMPT_VERSION, load_selected_route
from src.random_baseline import evaluation_example_ids
from src.semantic_cache import (
    build_jev_state,
    load_score_cache,
    semantic_cache_key,
)
from src.jev_ranker import build_jev_question


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def audit_one(ex: ExampleId, *, route) -> dict[str, Any]:
    candidates = load_candidates(ex)
    ids = list(candidates["candidate_ids"])
    patch = load_patch_representation_text(ex)
    pairs = dict(load_test_representation_texts(ex))
    question = build_jev_question()
    missing: list[str] = []
    invalid: list[str] = []
    ok_count = 0
    for test_class in ids:
        if test_class not in pairs:
            missing.append(test_class)
            continue
        state = build_jev_state(
            code_change=patch, candidate_test=pairs[test_class]
        )
        key = semantic_cache_key(
            provider=route.provider,
            model_id=route.request_model,
            prompt_version=JEV_PROMPT_VERSION,
            state=state,
            question=question,
        )
        entry = load_score_cache(key, kind="jev")
        if entry is None:
            missing.append(test_class)
            continue
        score = entry.get("score")
        try:
            val = float(score)
        except (TypeError, ValueError):
            invalid.append(test_class)
            continue
        if not (0.0 <= val <= 1.0):
            invalid.append(test_class)
            continue
        ok_count += 1
    return {
        "qualified_id": ex.qualified,
        "ok": not missing and not invalid,
        "K": len(ids),
        "scored": ok_count,
        "missing": missing,
        "invalid": invalid,
        "shortlist_sha256": candidates.get("shortlist_sha256"),
        "experiment_commit": candidates.get("experiment_commit"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--split", choices=("development", "evaluation"), default="evaluation"
    )
    args = parser.parse_args(argv)
    manifest = load_manifest()
    route = load_selected_route()
    if args.split == "evaluation":
        lock = assert_evaluation_allowed()
        commit = lock.get("commit_sha")
        targets = evaluation_example_ids(manifest)
        out = WORKSPACE / "results" / "phase7" / "jev_audit.json"
    else:
        commit = None
        targets = development_example_ids(manifest)
        out = WORKSPACE / "results" / "jev_audit-development.json"

    rows = [audit_one(ex, route=route) for ex in targets]
    failed = [r for r in rows if not r["ok"]]
    report: dict[str, Any] = {
        "schema_version": "jev-phase7-jev-audit-v1",
        "audited_at": _utcnow(),
        "split": args.split,
        "experiment_commit": commit,
        "provider": route.provider,
        "model_id": route.request_model,
        "prompt_version": JEV_PROMPT_VERSION,
        "counts": {
            "targets": len(rows),
            "passed": len(rows) - len(failed),
            "failed": len(failed),
            "pairs_scored": sum(int(r.get("scored") or 0) for r in rows),
            "pairs_expected": sum(int(r.get("K") or 0) for r in rows),
        },
        "failed_ids": [r["qualified_id"] for r in failed],
        "examples": rows,
        "ok": not failed
        and len(rows) == (125 if args.split == "evaluation" else 25),
    }
    atomic_write_json(out, report)
    c = report["counts"]
    print(
        f"jev audit ({args.split}): "
        f"passed={c['passed']}/{c['targets']} "
        f"pairs={c['pairs_scored']}/{c['pairs_expected']} "
        f"failed={c['failed']} report={out}"
    )
    if failed:
        for r in failed[:15]:
            print(
                f"  FAIL {r['qualified_id']}: "
                f"missing={len(r.get('missing') or [])} "
                f"invalid={len(r.get('invalid') or [])}",
                file=sys.stderr,
            )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
