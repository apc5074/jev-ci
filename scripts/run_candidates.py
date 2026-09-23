#!/usr/bin/env python3
"""Generate BM25 rankings and candidate shortlists for a locked manifest split.

Default / required for Phase 4 (pre-freeze):

    python scripts/run_candidates.py --split development

Evaluation IDs require ``--allow-evaluation`` (post Phase-6 freeze only). The
command never walks evaluation bugs by default and never emits trigger IDs in
summaries or candidate files.
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

from src.candidates import (
    CandidatesError,
    SaveOutcome,
    generate_and_save,
    load_candidates,
    load_ranking,
    verify_shortlist_is_ranking_prefix,
)
from src.example_contract import (
    WORKSPACE,
    ExampleContractError,
    ExampleId,
    ExampleIncompleteError,
    atomic_write_json,
    development_example_ids,
    load_manifest,
    require_manifest_membership,
    validate_example_artifacts,
)
from src.ranking import LexicalInputError
from src.select_bugs import ManifestError, verify_manifest_integrity

SUMMARY_DIR = WORKSPACE / "results"
DATA_ROOT = WORKSPACE / "data"
RESULTS_ROOT = WORKSPACE / "results"


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
    data_root: Path,
    results_root: Path,
) -> dict[str, Any]:
    """Validate Phase 3 example, then build/reuse BM25 ranking + shortlist."""
    # Fail clearly on incomplete/mismatched examples before any write.
    validate_example_artifacts(
        example,
        data_root=data_root,
        manifest=manifest,
        allow_evaluation=allow_evaluation,
    )

    result = generate_and_save(
        example,
        data_root=data_root,
        results_root=results_root,
        manifest=manifest,
        allow_evaluation=allow_evaluation,
        force=force,
    )

    # Refuse to treat a bug as done unless both artifacts agree.
    candidates = load_candidates(example, data_root=data_root)
    ranking = load_ranking(example, results_root=results_root)
    verify_shortlist_is_ranking_prefix(candidates=candidates, ranking=ranking)

    outcome = {
        SaveOutcome.REUSED: "skipped_reuse",
        SaveOutcome.WRITTEN: "written",
        SaveOutcome.REGENERATED: "regenerated",
    }[result.outcome]

    return {
        "qualified_id": example.qualified,
        "outcome": outcome,
        "N": result.n,
        "K": result.k,
        "source_missing": candidates.get("source_missing_count")
        if "source_missing_count" in candidates
        else ranking.get("source_missing_count", 0),
        "shortlist_sha256": result.shortlist_sha256,
        "detail": result.detail,
        # Counts only — never trigger / positive class IDs.
    }


def _summary_counts(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    ok_outcomes = {"written", "regenerated", "skipped_reuse"}
    completed = [r for r in rows if r.get("outcome") in ok_outcomes]
    failed = [r for r in rows if r.get("outcome") == "failed"]
    reused = [r for r in rows if r.get("outcome") == "skipped_reuse"]
    written = [r for r in rows if r.get("outcome") in ("written", "regenerated")]
    return {
        "targets": len(rows),
        "completed": len(completed),
        "failed": len(failed),
        "skipped_reuse": len(reused),
        "written_or_regenerated": len(written),
        "N_total": sum(int(r.get("N") or 0) for r in completed),
        "K_total": sum(int(r.get("K") or 0) for r in completed),
        "source_missing_total": sum(int(r.get("source_missing") or 0) for r in completed),
        "failed_ids": [r["qualified_id"] for r in failed],
    }


def run_candidates(
    *,
    split: str,
    allow_evaluation: bool = False,
    force: bool = False,
    only: Sequence[str] | None = None,
    manifest_path: Path | None = None,
    data_root: Path | None = None,
    results_root: Path | None = None,
) -> dict[str, Any]:
    """Build rankings/shortlists for every target ID in manifest order."""
    manifest = load_manifest(manifest_path)
    try:
        verify_manifest_integrity(manifest)
    except ManifestError as exc:
        raise ExampleContractError(f"manifest integrity failed: {exc}") from exc

    targets = resolve_target_ids(
        split=split,
        manifest=manifest,
        allow_evaluation=allow_evaluation,
        only=only,
    )
    data = data_root or DATA_ROOT
    results = results_root or RESULTS_ROOT

    rows: list[dict[str, Any]] = []
    for ex in targets:
        print(f"==> {ex.qualified}", flush=True)
        try:
            row = process_example(
                ex,
                manifest=manifest,
                allow_evaluation=allow_evaluation,
                force=force,
                data_root=data,
                results_root=results,
            )
            print(
                f"    {row['outcome']} N={row.get('N')} K={row.get('K')} "
                f"missing_src={row.get('source_missing')} "
                f"shortlist={str(row.get('shortlist_sha256', ''))[:12]}…",
                flush=True,
            )
        except (
            CandidatesError,
            LexicalInputError,
            ExampleContractError,
            ExampleIncompleteError,
            OSError,
        ) as exc:
            # Preserve already-complete artifacts for prior bugs; do not invent
            # a success row for this failure.
            row = {
                "qualified_id": ex.qualified,
                "outcome": "failed",
                "error": str(exc),
            }
            print(f"    FAILED: {exc}", flush=True)
            traceback.print_exc()
        rows.append(row)

    summary = {
        "command": "run_candidates",
        "split": split,
        "allow_evaluation": allow_evaluation,
        "force": force,
        "finished_at": _utcnow(),
        "defects4j_commit": manifest.get("defects4j_commit"),
        "selection_seed": manifest.get("selection_seed"),
        "counts": _summary_counts(rows),
        "examples": rows,
    }
    SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
    out_path = SUMMARY_DIR / f"run_candidates-{split}.json"
    atomic_write_json(out_path, summary)
    summary["summary_path"] = str(out_path.relative_to(WORKSPACE))
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate BM25 full rankings and top-K candidate shortlists "
            "for a locked manifest split"
        ),
    )
    parser.add_argument(
        "--split",
        choices=("development", "evaluation"),
        required=True,
        help="Manifest split to process (development = 25 bugs for Phase 4)",
    )
    parser.add_argument(
        "--allow-evaluation",
        action="store_true",
        help="Required with --split evaluation (post Phase-6 freeze only)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite even when a semantic lock is present",
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
        summary = run_candidates(
            split=args.split,
            allow_evaluation=args.allow_evaluation,
            force=args.force,
            only=args.only or None,
        )
    except (ExampleContractError, ManifestError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    counts = summary["counts"]
    print(
        f"run_candidates {summary['split']}: "
        f"completed={counts['completed']} "
        f"failed={counts['failed']} "
        f"reused={counts['skipped_reuse']} "
        f"written={counts['written_or_regenerated']} "
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
    raise SystemExit(main())
