#!/usr/bin/env python3
"""Prepare Phase 3 dataset examples for a locked manifest split.

Default / required for Phase 3:

    python scripts/prepare_dataset.py --split development

Evaluation IDs require ``--allow-evaluation`` (post-freeze only). The command
never walks the full 150-bug manifest accidentally.
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

from src.checkout import CheckoutError, checkout_example
from src.example_contract import (
    WORKSPACE,
    ExampleContractError,
    ExampleId,
    atomic_write_json,
    development_example_ids,
    example_is_current_complete,
    load_manifest,
    mark_example_complete,
    mark_example_error,
    read_json,
    require_manifest_membership,
    validate_example_artifacts,
)
from src.extract_patch import PatchExtractionError, extract_patch_for_example
from src.extract_tests import TestExtractionError, extract_tests_for_example
from src.representations import RepresentationError, build_representations_for_example

SUMMARY_DIR = WORKSPACE / "results"


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _evaluation_ids(manifest: Mapping[str, Any]) -> tuple[ExampleId, ...]:
    ids = manifest.get("evaluation_bug_ids")
    if not isinstance(ids, list) or not ids:
        raise ExampleContractError("manifest.evaluation_bug_ids missing or empty")
    return tuple(ExampleId.parse(str(raw)) for raw in ids)


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
        targets = _evaluation_ids(manifest)
    else:
        raise ExampleContractError(f"unknown split {split!r}")

    if only:
        wanted = [ExampleId.parse(x) for x in only]
        by_q = {ex.qualified: ex for ex in targets}
        resolved: list[ExampleId] = []
        for ex in wanted:
            if ex.qualified not in by_q:
                raise ExampleContractError(
                    f"{ex.qualified} is not in the {split} split "
                    f"(refusing to process IDs outside --split {split})"
                )
            # Confirm membership rules (evaluation gate, etc.).
            require_manifest_membership(
                ex, manifest=manifest, allow_evaluation=allow_evaluation
            )
            resolved.append(ex)
        return tuple(resolved)
    return targets


def process_example(
    example: ExampleId,
    *,
    manifest: Mapping[str, Any],
    allow_evaluation: bool,
    force: bool,
) -> dict[str, Any]:
    """Run checkout → patch → tests → representations → finalize for one bug."""
    if not force and example_is_current_complete(
        example,
        manifest=manifest,
        allow_evaluation=allow_evaluation,
    ):
        validated = validate_example_artifacts(
            example,
            manifest=manifest,
            allow_evaluation=allow_evaluation,
        )
        paths = validated["paths"]
        patch_meta = read_json(paths["patch_meta"])
        return {
            "qualified_id": example.qualified,
            "outcome": "skipped_complete",
            "status": "complete",
            "num_test_classes": len(validated["inventory"]["test_classes"]),
            "num_positive_classes": len(
                validated["labels"].get("positive_classes") or []
            ),
            "source_missing": (validated["inventory"].get("counts") or {}).get(
                "source_missing", 0
            ),
            "patch_truncated": bool(patch_meta.get("patch_truncated")),
            "representation_truncated": (
                validated["representations_index"].get("counts") or {}
            ).get("representation_truncated", 0),
        }

    # Retry path: stages mark errors themselves; never leave status=complete
    # until finalize succeeds.
    checkout_example(
        example,
        manifest=manifest,
        allow_evaluation=allow_evaluation,
        force=force,
    )
    extract_patch_for_example(
        example,
        manifest=manifest,
        allow_evaluation=allow_evaluation,
    )
    extract_tests_for_example(
        example,
        manifest=manifest,
        allow_evaluation=allow_evaluation,
    )
    build_representations_for_example(
        example,
        manifest=manifest,
        allow_evaluation=allow_evaluation,
    )
    finalized = mark_example_complete(
        example,
        manifest=manifest,
        allow_evaluation=allow_evaluation,
    )
    return {
        "qualified_id": example.qualified,
        "outcome": "completed",
        **finalized,
    }


def _summary_counts(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    completed = [r for r in rows if r.get("outcome") in ("completed", "skipped_complete")]
    failed = [r for r in rows if r.get("outcome") == "failed"]
    skipped = [r for r in rows if r.get("outcome") == "skipped_complete"]
    return {
        "targets": len(rows),
        "completed": len(completed),
        "failed": len(failed),
        "skipped_complete": len(skipped),
        "num_test_classes_total": sum(int(r.get("num_test_classes") or 0) for r in completed),
        "num_positive_classes_total": sum(
            int(r.get("num_positive_classes") or 0) for r in completed
        ),
        "source_missing_total": sum(int(r.get("source_missing") or 0) for r in completed),
        "patch_truncated_count": sum(
            1 for r in completed if r.get("patch_truncated")
        ),
        "representation_truncated_total": sum(
            int(r.get("representation_truncated") or 0) for r in completed
        ),
        "failed_ids": [r["qualified_id"] for r in failed],
    }


def prepare_dataset(
    *,
    split: str,
    allow_evaluation: bool = False,
    force: bool = False,
    only: Sequence[str] | None = None,
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    targets = resolve_target_ids(
        split=split,
        manifest=manifest,
        allow_evaluation=allow_evaluation,
        only=only,
    )
    rows: list[dict[str, Any]] = []
    for ex in targets:
        print(f"==> {ex.qualified}", flush=True)
        try:
            row = process_example(
                ex,
                manifest=manifest,
                allow_evaluation=allow_evaluation,
                force=force,
            )
            print(
                f"    {row['outcome']} tests={row.get('num_test_classes')} "
                f"positives={row.get('num_positive_classes')} "
                f"missing_src={row.get('source_missing')}",
                flush=True,
            )
        except (
            CheckoutError,
            PatchExtractionError,
            TestExtractionError,
            RepresentationError,
            ExampleContractError,
            OSError,
        ) as exc:
            mark_example_error(
                ex,
                stage="prepare_dataset",
                message=str(exc),
                detail={"qualified_id": ex.qualified},
                retryable=True,
            )
            row = {
                "qualified_id": ex.qualified,
                "outcome": "failed",
                "error": str(exc),
            }
            print(f"    FAILED: {exc}", flush=True)
            traceback.print_exc()
        rows.append(row)

    summary = {
        "split": split,
        "allow_evaluation": allow_evaluation,
        "force": force,
        "started_finish": _utcnow(),
        "defects4j_commit": manifest.get("defects4j_commit"),
        "selection_seed": manifest.get("selection_seed"),
        "counts": _summary_counts(rows),
        "examples": rows,
    }
    # Avoid putting trigger method IDs into the summary (counts only).
    SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
    out_path = SUMMARY_DIR / f"prepare_dataset-{split}.json"
    atomic_write_json(out_path, summary)
    summary["summary_path"] = str(out_path.relative_to(WORKSPACE))
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare Defects4J examples for a locked manifest split",
    )
    parser.add_argument(
        "--split",
        choices=("development", "evaluation"),
        required=True,
        help="Manifest split to process (development = 25 bugs for Phase 3)",
    )
    parser.add_argument(
        "--allow-evaluation",
        action="store_true",
        help="Required with --split evaluation (post Phase-6 freeze only)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild even when a complete example validates as current",
    )
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        help="Restrict to these split members (repeatable); still enforces --split",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        summary = prepare_dataset(
            split=args.split,
            allow_evaluation=args.allow_evaluation,
            force=args.force,
            only=args.only or None,
        )
    except ExampleContractError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    counts = summary["counts"]
    print(
        f"prepare_dataset {summary['split']}: "
        f"completed={counts['completed']} "
        f"failed={counts['failed']} "
        f"skipped={counts['skipped_complete']} "
        f"summary={summary['summary_path']}",
        flush=True,
    )
    if counts["failed"]:
        print(
            "failed ids: " + ", ".join(counts["failed_ids"]),
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
