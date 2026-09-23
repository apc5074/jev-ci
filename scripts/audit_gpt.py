#!/usr/bin/env python3
"""Audit GPT-Nano shortlist score completeness (P7-06)."""

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
from src.gpt_ranker import (
    GPT_PROMPT_VERSION,
    primary_comparison_model,
    resolve_gpt_route,
)
from src.random_baseline import evaluation_example_ids
from src.semantic_cache import (
    build_gpt_question,
    build_jev_state,
    load_score_cache,
    semantic_cache_key,
)


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def audit_one(ex: ExampleId, *, gpt_route, gpt_model) -> dict[str, Any]:
    candidates = load_candidates(ex)
    ids = list(candidates["candidate_ids"])
    patch = load_patch_representation_text(ex)
    pairs = dict(load_test_representation_texts(ex))
    question = build_gpt_question()
    cache_model_id = gpt_model.canonical_model_id

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
            provider=gpt_route.provider,
            model_id=cache_model_id,
            prompt_version=GPT_PROMPT_VERSION,
            state=state,
            question=question,
        )
        entry = load_score_cache(key, kind="gpt")
        if entry is None:
            missing.append(test_class)
            continue
        try:
            val = float(entry.get("score"))
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
        "missing_count": len(missing),
        "invalid_count": len(invalid),
        "missing": missing[:20],
        "invalid": invalid[:20],
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
    gpt_model = primary_comparison_model()
    gpt_route = resolve_gpt_route()

    if args.split == "evaluation":
        lock = assert_evaluation_allowed()
        commit = lock.get("commit_sha")
        targets = evaluation_example_ids(manifest)
        out = WORKSPACE / "results" / "phase7" / "gpt_audit.json"
    else:
        commit = None
        targets = development_example_ids(manifest)
        out = WORKSPACE / "results" / "gpt_audit-development.json"

    rows = [
        audit_one(ex, gpt_route=gpt_route, gpt_model=gpt_model) for ex in targets
    ]
    failed = [r for r in rows if not r["ok"]]
    report: dict[str, Any] = {
        "schema_version": "jev-phase7-gpt-audit-v1",
        "audited_at": _utcnow(),
        "split": args.split,
        "experiment_commit": commit,
        "provider": gpt_route.provider,
        "model_key": gpt_model.key,
        "canonical_model_id": gpt_model.canonical_model_id,
        "openrouter_request_model": gpt_model.openrouter_request_model,
        "prompt_version": GPT_PROMPT_VERSION,
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
        "notes": (
            "GPT uses the same sealed shortlist_sha256 and patch/test state "
            "bytes as Jev (build_jev_state)."
        ),
    }
    atomic_write_json(out, report)
    c = report["counts"]
    print(
        f"gpt audit ({args.split}): "
        f"passed={c['passed']}/{c['targets']} "
        f"pairs={c['pairs_scored']}/{c['pairs_expected']} "
        f"failed={c['failed']} report={out}"
    )
    if failed:
        for r in failed[:15]:
            print(
                f"  FAIL {r['qualified_id']}: "
                f"missing={r.get('missing_count')} "
                f"invalid={r.get('invalid_count')}",
                file=sys.stderr,
            )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
