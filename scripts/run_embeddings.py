#!/usr/bin/env python3
"""Generate Embedding baseline rankings for a locked manifest split.

Default / required for Phase 5 (pre-freeze):

    python scripts/run_embeddings.py --split development

Requires ``OPENAI_API_KEY`` or ``OPENROUTER_API_KEY`` (OpenRouter uses
``openai/text-embedding-3-small``). Evaluation requires ``--allow-evaluation``.
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

from src.embeddings import (
    EmbeddingError,
    SaveOutcome,
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
from src.random_baseline import evaluation_example_ids
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
        description="Generate Embedding baseline rankings for a manifest split."
    )
    parser.add_argument(
        "--split",
        choices=("development", "evaluation"),
        default="development",
    )
    parser.add_argument("--allow-evaluation", action="store_true")
    parser.add_argument("--only", nargs="+", default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--provider",
        choices=("auto", "openai", "openrouter"),
        default="auto",
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
        route = resolve_embedding_route(prefer=args.provider)
    except (ExampleContractError, ManifestError, EmbeddingError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    rows: list[dict[str, Any]] = []
    failures = 0
    for ex in targets:
        try:
            doc, outcome = generate_embedding_ranking(
                ex,
                split=args.split,
                manifest=manifest,
                route=route,
                force=args.force,
            )
            row = {
                "qualified_id": ex.qualified,
                "outcome": outcome.value,
                "N": doc["N"],
                "total_input_tokens": doc["total_input_tokens"],
                "top1": doc["ranking"][0]["test_class"] if doc["ranking"] else None,
            }
            rows.append(row)
            print(
                f"{ex.qualified}: {outcome.value} N={doc['N']} "
                f"tokens={doc['total_input_tokens']}"
            )
        except Exception as exc:  # noqa: BLE001
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
        "provider": route.provider,
        "model_id": route.canonical_model_id,
        "count": len(targets),
        "failures": failures,
        "outcomes": {
            "written": sum(
                1 for r in rows if r.get("outcome") == SaveOutcome.WRITTEN.value
            ),
            "reused": sum(
                1 for r in rows if r.get("outcome") == SaveOutcome.REUSED.value
            ),
            "regenerated": sum(
                1 for r in rows if r.get("outcome") == SaveOutcome.REGENERATED.value
            ),
            "failed": failures,
        },
        "bugs": rows,
    }
    SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
    summary_path = SUMMARY_DIR / "embeddings_summary.json"
    atomic_write_json(summary_path, summary)
    print(f"summary: {summary_path.relative_to(WORKSPACE)} failures={failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
