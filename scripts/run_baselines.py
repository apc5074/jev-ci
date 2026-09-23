#!/usr/bin/env python3
"""Verify / refresh Phase 5 baselines for a locked manifest split (P5-09).

Checks Random, BM25 rankings, Embedding rankings, and candidate shortlists.
Optionally regenerates Random / Embedding when missing.

    python scripts/run_baselines.py --split development
    python scripts/run_baselines.py --split development --refresh-missing
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.candidates import candidate_path, load_candidates, ranking_path
from src.embeddings import (
    EmbeddingError,
    generate_embedding_ranking,
    resolve_embedding_route,
)
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
    evaluation_example_ids,
    generate_and_save,
)
from src.select_bugs import ManifestError, verify_manifest_integrity

SUMMARY_DIR = WORKSPACE / "results"
EMBEDDINGS_ROOT = WORKSPACE / "results" / "embeddings"
RANDOM_ROOT = WORKSPACE / "results" / "random"


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
        description="Verify Phase 5 baseline artifacts (Random/BM25/Embedding)."
    )
    parser.add_argument(
        "--split",
        choices=("development", "evaluation"),
        default="development",
    )
    parser.add_argument("--allow-evaluation", action="store_true")
    parser.add_argument("--only", nargs="+", default=None)
    parser.add_argument(
        "--refresh-missing",
        action="store_true",
        help="Regenerate missing Random / Embedding artifacts",
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
    except (ExampleContractError, ManifestError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    rows: list[dict[str, Any]] = []
    missing = 0
    for ex in targets:
        status = {
            "qualified_id": ex.qualified,
            "bm25_ranking": ranking_path(ex).is_file(),
            "candidates": candidate_path(ex).is_file(),
            "random": (RANDOM_ROOT / f"{ex.slug}.json").is_file(),
            "embedding": (EMBEDDINGS_ROOT / f"{ex.slug}.json").is_file(),
        }
        if status["candidates"]:
            try:
                load_candidates(ex)
                status["candidates_ok"] = True
            except Exception as exc:  # noqa: BLE001
                status["candidates_ok"] = False
                status["candidates_error"] = str(exc)

        if args.refresh_missing:
            if not status["random"]:
                try:
                    generate_and_save(ex, split=args.split, manifest=manifest)
                    status["random"] = True
                    status["random_refreshed"] = True
                except (RandomBaselineError, ExampleContractError) as exc:
                    status["random_error"] = str(exc)
            if not status["embedding"]:
                try:
                    route = resolve_embedding_route()
                    generate_embedding_ranking(
                        ex,
                        split=args.split,
                        manifest=manifest,
                        route=route,
                    )
                    status["embedding"] = True
                    status["embedding_refreshed"] = True
                except (EmbeddingError, ExampleContractError) as exc:
                    status["embedding_error"] = str(exc)

        ok = all(
            [
                status["bm25_ranking"],
                status.get("candidates_ok", status["candidates"]),
                status["random"],
                status["embedding"],
            ]
        )
        status["ok"] = ok
        if not ok:
            missing += 1
        rows.append(status)
        print(
            f"{ex.qualified}: "
            f"bm25={'Y' if status['bm25_ranking'] else 'N'} "
            f"cand={'Y' if status.get('candidates_ok', status['candidates']) else 'N'} "
            f"rand={'Y' if status['random'] else 'N'} "
            f"emb={'Y' if status['embedding'] else 'N'} "
            f"{'ok' if ok else 'MISSING'}"
        )

    summary = {
        "generated_at": _utcnow(),
        "split": args.split,
        "count": len(targets),
        "missing": missing,
        "bugs": rows,
    }
    SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
    path = SUMMARY_DIR / "baselines_summary.json"
    atomic_write_json(path, summary)
    print(f"summary: {path.relative_to(WORKSPACE)} missing={missing}")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
