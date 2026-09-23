#!/usr/bin/env python3
"""Audit Embedding rankings for a manifest split (P7-04 evaluation)."""

from __future__ import annotations

import argparse
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.embeddings import (
    EMBEDDING_MODEL_ID,
    EmbeddingError,
    load_embedding_ranking,
    load_test_representation_texts,
)
from src.example_contract import (
    WORKSPACE,
    ExampleContractError,
    ExampleId,
    atomic_write_json,
    development_example_ids,
    load_manifest,
    validate_example_artifacts,
)
from src.freeze_guard import assert_evaluation_allowed
from src.random_baseline import evaluation_example_ids


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def audit_one(
    ex: ExampleId,
    *,
    allow_evaluation: bool,
    require_commit: str | None,
) -> dict[str, Any]:
    validate_example_artifacts(ex, allow_evaluation=allow_evaluation)
    doc = load_embedding_ranking(ex)
    problems: list[str] = []
    if doc.get("model_id") != EMBEDDING_MODEL_ID:
        problems.append(f"model_id={doc.get('model_id')!r}")
    if doc.get("settings", {}).get("uses_bm25") is not False:
        problems.append("uses_bm25 must be false")
    if allow_evaluation and doc.get("split") != "evaluation":
        problems.append(f"split={doc.get('split')!r}")
    if require_commit and doc.get("experiment_commit") != require_commit:
        problems.append(
            f"experiment_commit={doc.get('experiment_commit')!r} != {require_commit!r}"
        )

    pairs = load_test_representation_texts(ex)
    classes = [c for c, _ in pairs]
    ranked = doc.get("ranking") or []
    ranked_ids = [r.get("test_class") for r in ranked]
    if len(ranked_ids) != len(classes):
        problems.append(f"N ranking={len(ranked_ids)} != inventory={len(classes)}")
    if len(ranked_ids) != len(set(ranked_ids)):
        problems.append("duplicate ranked IDs")
    if set(ranked_ids) != set(classes):
        problems.append("ranking is not a permutation of inventory")
    for r in ranked:
        score = r.get("score")
        if score is None or not math.isfinite(float(score)):
            problems.append(f"non-finite score for {r.get('test_class')}")
            break
    # Cosine desc, FQCN asc tie-break
    for i in range(len(ranked) - 1):
        a, b = ranked[i], ranked[i + 1]
        sa, sb = float(a["score"]), float(b["score"])
        if sa < sb - 1e-12:
            problems.append("ranking not sorted by cosine desc")
            break
        if abs(sa - sb) <= 1e-12 and a["test_class"] > b["test_class"]:
            problems.append("FQCN tie-break violated")
            break

    return {
        "qualified_id": ex.qualified,
        "ok": not problems,
        "problems": problems,
        "N": doc.get("N"),
        "total_input_tokens": doc.get("total_input_tokens"),
        "experiment_commit": doc.get("experiment_commit"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--split", choices=("development", "evaluation"), default="evaluation"
    )
    args = parser.parse_args(argv)
    manifest = load_manifest()
    if args.split == "evaluation":
        lock = assert_evaluation_allowed()
        commit = lock.get("commit_sha")
        targets = evaluation_example_ids(manifest)
        allow = True
        out = WORKSPACE / "results" / "phase7" / "embeddings_audit.json"
    else:
        commit = None
        targets = development_example_ids(manifest)
        allow = False
        out = WORKSPACE / "results" / "embeddings_audit-development.json"

    rows = []
    for ex in targets:
        try:
            rows.append(
                audit_one(ex, allow_evaluation=allow, require_commit=commit)
            )
        except (ExampleContractError, EmbeddingError, OSError) as exc:
            rows.append(
                {
                    "qualified_id": ex.qualified,
                    "ok": False,
                    "problems": [str(exc)],
                }
            )

    failed = [r for r in rows if not r["ok"]]
    report: dict[str, Any] = {
        "schema_version": "jev-phase7-embeddings-audit-v1",
        "audited_at": _utcnow(),
        "split": args.split,
        "experiment_commit": commit,
        "model_id": EMBEDDING_MODEL_ID,
        "counts": {
            "targets": len(rows),
            "passed": len(rows) - len(failed),
            "failed": len(failed),
            "N_total": sum(int(r.get("N") or 0) for r in rows if r.get("ok")),
            "tokens_total": sum(
                int(r.get("total_input_tokens") or 0) for r in rows if r.get("ok")
            ),
        },
        "failed_ids": [r["qualified_id"] for r in failed],
        "examples": rows,
        "ok": not failed
        and len(rows) == (125 if args.split == "evaluation" else 25),
    }
    atomic_write_json(out, report)
    print(
        f"embeddings audit ({args.split}): "
        f"passed={report['counts']['passed']}/{report['counts']['targets']} "
        f"failed={report['counts']['failed']} report={out}"
    )
    if failed:
        for r in failed[:10]:
            print(f"  FAIL {r['qualified_id']}: {r.get('problems')}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
