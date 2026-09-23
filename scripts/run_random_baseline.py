#!/usr/bin/env python3
"""Generate Random baseline seed contracts for a locked manifest split.

Default / required for Phase 5 (pre-freeze):

    python scripts/run_random_baseline.py --split development

Evaluation IDs require ``--allow-evaluation`` (post Phase-6 freeze only).
Contracts store seeds and permutation fingerprints; full lists regenerate
from ``src.random_baseline.generate_permutations``.
"""

from __future__ import annotations

import argparse
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.example_contract import (
    WORKSPACE,
    ExampleContractError,
    ExampleId,
    atomic_write_json,
    development_example_ids,
    load_manifest,
    require_manifest_membership,
)
from src.random_baseline import (
    RandomBaselineError,
    SaveOutcome,
    evaluation_example_ids,
    generate_and_save,
    load_contract,
    load_inventory_test_classes,
    regenerate_from_contract,
)
from src.select_bugs import ManifestError, verify_manifest_integrity

SUMMARY_DIR = WORKSPACE / "results"


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def resolve_target_ids(
    *,
    split: str,
    manifest: Mapping[str, Any],
    allow_evaluation: bool,
    only: Sequence[str] | None,
) -> tuple[ExampleId, ...]:
    if split == "development":
        targets = development_example_ids(manifest)
    elif split == "evaluation":
        if not allow_evaluation:
            raise ExampleContractError(
                "--split evaluation requires --allow-evaluation "
                "(reserved until the Phase 6 design freeze)"
            )
        targets = evaluation_example_ids(manifest)
    else:
        raise ExampleContractError(f"unknown split: {split!r}")

    if only:
        wanted = [ExampleId.parse(x) for x in only]
        by_q = {t.qualified: t for t in targets}
        resolved: list[ExampleId] = []
        for ex in wanted:
            require_manifest_membership(
                ex,
                manifest=manifest,
                allow_evaluation=(split == "evaluation"),
            )
            if ex.qualified not in by_q:
                raise ExampleContractError(
                    f"{ex.qualified} is not in the {split} split"
                )
            resolved.append(by_q[ex.qualified])
        return tuple(resolved)
    return targets


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate Random baseline contracts for a manifest split."
    )
    parser.add_argument(
        "--split",
        choices=("development", "evaluation"),
        default="development",
    )
    parser.add_argument(
        "--allow-evaluation",
        action="store_true",
        help="Required with --split evaluation (post Phase-6 freeze).",
    )
    parser.add_argument(
        "--only",
        nargs="+",
        default=None,
        help="Optional subset of qualified ids within the split.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite contracts even when hashes match.",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Only regenerate and verify existing contracts.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        manifest = load_manifest()
        verify_manifest_integrity(manifest)
        targets = resolve_target_ids(
            split=args.split,
            manifest=manifest,
            allow_evaluation=args.allow_evaluation,
            only=args.only,
        )
    except (ExampleContractError, ManifestError, RandomBaselineError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    rows: list[dict[str, Any]] = []
    failures = 0
    for ex in targets:
        try:
            if args.verify:
                contract = load_contract(ex)
                classes = load_inventory_test_classes(ex)
                regenerate_from_contract(contract, test_classes=classes)
                rows.append(
                    {
                        "qualified_id": ex.qualified,
                        "outcome": "verified",
                        "seed": contract["seed"],
                        "bug_index": contract["bug_index"],
                        "N": contract["N"],
                        "permutations_sha256": contract["permutations_sha256"],
                    }
                )
            else:
                contract, outcome = generate_and_save(
                    ex,
                    split=args.split,
                    manifest=manifest,
                    force=args.force,
                )
                rows.append(
                    {
                        "qualified_id": ex.qualified,
                        "outcome": outcome.value,
                        "seed": contract["seed"],
                        "bug_index": contract["bug_index"],
                        "N": contract["N"],
                        "permutations_sha256": contract["permutations_sha256"],
                    }
                )
            print(
                f"{ex.qualified}: {rows[-1]['outcome']} "
                f"seed={rows[-1]['seed']} N={rows[-1]['N']}"
            )
        except Exception as exc:  # noqa: BLE001 — batch must continue
            failures += 1
            print(f"{ex.qualified}: FAIL {exc}", file=sys.stderr)
            traceback.print_exc()
            rows.append(
                {
                    "qualified_id": ex.qualified,
                    "outcome": "failed",
                    "error": str(exc),
                }
            )

    summary = {
        "generated_at": _utcnow(),
        "split": args.split,
        "verify": args.verify,
        "count": len(targets),
        "failures": failures,
        "outcomes": {
            "written": sum(1 for r in rows if r.get("outcome") == SaveOutcome.WRITTEN.value),
            "reused": sum(1 for r in rows if r.get("outcome") == SaveOutcome.REUSED.value),
            "regenerated": sum(
                1 for r in rows if r.get("outcome") == SaveOutcome.REGENERATED.value
            ),
            "verified": sum(1 for r in rows if r.get("outcome") == "verified"),
            "failed": failures,
        },
        "bugs": rows,
    }
    SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
    summary_path = SUMMARY_DIR / (
        f"random_baseline_summary-{args.split}.json"
        if args.split == "evaluation"
        else "random_baseline_summary.json"
    )
    if args.split == "evaluation" and args.allow_evaluation:
        try:
            from src.evaluation_preflight import append_execution_log, load_preflight
            from src.freeze_guard import assert_evaluation_allowed

            lock = assert_evaluation_allowed()
            summary["experiment_commit"] = lock.get("commit_sha")
            pre = load_preflight()
            if pre:
                summary["run_id"] = pre.get("run_id")
                summary["experiment_commit"] = pre.get("experiment_commit") or summary[
                    "experiment_commit"
                ]
            append_execution_log(
                {
                    "event": "run_random_baseline",
                    "split": args.split,
                    "ok": failures == 0,
                    "count": len(targets),
                    "failures": failures,
                    "experiment_commit": summary.get("experiment_commit"),
                    "run_id": summary.get("run_id"),
                }
            )
        except Exception:  # noqa: BLE001
            pass
    atomic_write_json(summary_path, summary)
    print(f"summary: {summary_path.relative_to(WORKSPACE)} failures={failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
