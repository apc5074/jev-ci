#!/usr/bin/env python3
"""Score BM25 shortlists with GPT comparison models (P5-09).

Default / required for Phase 5 (pre-freeze):

    python scripts/run_gpt.py --split development --model primary

``--model all`` scores every registered comparison model. Requires
``OPENROUTER_API_KEY`` or ``OPENAI_API_KEY``. Evaluation requires
``--allow-evaluation``.
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
from src.gpt_ranker import (
    COMPARISON_MODELS,
    GptRankerError,
    ComparisonModel,
    get_comparison_model,
    primary_comparison_model,
    resolve_gpt_route,
    score_shortlist,
    write_comparison_models_registry,
)
from src.random_baseline import evaluation_example_ids
from src.select_bugs import ManifestError, verify_manifest_integrity
from src.semantic_scheduler import MAX_CONCURRENCY

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


def resolve_models(spec: str) -> list[ComparisonModel]:
    if spec == "all":
        return list(COMPARISON_MODELS)
    if spec == "primary":
        return [primary_comparison_model()]
    return [get_comparison_model(spec)]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Score development BM25 shortlists with GPT models (cache-first)."
    )
    parser.add_argument(
        "--split",
        choices=("development", "evaluation"),
        default="development",
    )
    parser.add_argument("--allow-evaluation", action="store_true")
    parser.add_argument("--only", nargs="+", default=None)
    parser.add_argument(
        "--model",
        default="primary",
        help="Comparison key, 'primary', or 'all'",
    )
    parser.add_argument(
        "--provider",
        choices=("auto", "openai", "openrouter"),
        default="auto",
    )
    parser.add_argument("--max-concurrency", type=int, default=MAX_CONCURRENCY)
    parser.add_argument("--max-rpm", type=int, default=None)
    parser.add_argument("--spend-ceiling-usd", type=float, default=None)
    parser.add_argument("--capture-first", action="store_true")
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
        models = resolve_models(args.model)
        route = resolve_gpt_route(prefer=args.provider)
        write_comparison_models_registry()
    except (ExampleContractError, ManifestError, GptRankerError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.max_concurrency > MAX_CONCURRENCY:
        print(
            f"error: max-concurrency {args.max_concurrency} > cap {MAX_CONCURRENCY}",
            file=sys.stderr,
        )
        return 2

    rows: list[dict[str, Any]] = []
    failures = 0
    first_capture_done = False
    for ex in targets:
        bug_row: dict[str, Any] = {"qualified_id": ex.qualified, "models": {}}
        bug_failed = False
        for model in models:
            try:
                capture = bool(args.capture_first and not first_capture_done)
                scored = score_shortlist(
                    ex,
                    model=model,
                    split=args.split,
                    manifest=manifest,
                    route=route,
                    max_concurrency=args.max_concurrency,
                    max_rpm=args.max_rpm,
                    spend_ceiling_usd=args.spend_ceiling_usd,
                    capture_first=capture,
                )
                if capture:
                    first_capture_done = True
                cached = sum(
                    1
                    for r in scored
                    if r.get("from_cache") and r.get("score") is not None
                )
                paid = sum(
                    1
                    for r in scored
                    if not r.get("from_cache") and r.get("score") is not None
                )
                failed = sum(1 for r in scored if r.get("score") is None)
                if failed:
                    bug_failed = True
                bug_row["models"][model.key] = {
                    "ranking_name": model.ranking_name,
                    "count": len(scored),
                    "cached": cached,
                    "paid": paid,
                    "failed": failed,
                    "ok": failed == 0,
                }
                print(
                    f"{ex.qualified} [{model.key}]: shortlist={len(scored)} "
                    f"cached={cached} paid={paid} failed={failed}"
                )
            except Exception as exc:  # noqa: BLE001
                bug_failed = True
                print(
                    f"{ex.qualified} [{model.key}]: FAIL {exc}",
                    file=sys.stderr,
                )
                traceback.print_exc()
                bug_row["models"][model.key] = {
                    "ok": False,
                    "error": str(exc),
                }
        if bug_failed:
            failures += 1
        bug_row["ok"] = not bug_failed
        rows.append(bug_row)

    summary = {
        "generated_at": _utcnow(),
        "split": args.split,
        "provider": route.provider,
        "models": [m.key for m in models],
        "max_concurrency": args.max_concurrency,
        "max_rpm": args.max_rpm,
        "spend_ceiling_usd": args.spend_ceiling_usd,
        "count": len(targets),
        "failures": failures,
        "bugs": rows,
    }
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
                    "event": "run_gpt",
                    "split": args.split,
                    "models": [m.key for m in models],
                    "ok": failures == 0,
                    "count": len(targets),
                    "failures": failures,
                    "experiment_commit": summary.get("experiment_commit"),
                    "run_id": summary.get("run_id"),
                }
            )
        except Exception:  # noqa: BLE001
            pass
    SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
    summary_path = SUMMARY_DIR / (
        f"gpt_scoring_summary-{args.split}.json"
        if args.split == "evaluation"
        else "gpt_scoring_summary.json"
    )
    atomic_write_json(summary_path, summary)
    print(f"summary: {summary_path.relative_to(WORKSPACE)} failures={failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
