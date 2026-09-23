"""Offline Phase 8 evaluation orchestrator (P8-08).

``python scripts/evaluate.py`` verifies the Phase 7 seal, regenerates all Phase 8
metrics/statistics/tables/figures from frozen raw inputs, and writes a
regeneration record. No provider credentials or network calls.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.cohort_summaries import run_cohort_summaries
from src.cost_metrics import run_cost_latency
from src.evaluate_checks import run_evaluate_checks
from src.evaluation_inputs import (
    InputValidationError,
    load_and_verify_sealed_inputs,
    write_validation_report,
)
from src.example_contract import WORKSPACE, atomic_write_json, read_json, sha256_file
from src.metrics import run_per_bug_metrics
from src.random_metrics import run_random_metrics
from src.report_outputs import run_report_outputs
from src.statistics import run_statistics

REGEN_RECORD = WORKSPACE / "results" / "phase8" / "evaluate_regeneration.json"
API_ENV_KEYS = (
    "OPENROUTER_API_KEY",
    "OPENAI_API_KEY",
    "TYPESAFE_API_KEY",
    "ANTHROPIC_API_KEY",
)


class EvaluateError(Exception):
    """Offline evaluation regeneration failed."""


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _rel(path: Path, *, workspace: Path) -> str:
    try:
        return str(path.resolve().relative_to(workspace.resolve()))
    except ValueError:
        return str(path)


def assert_offline_environment(*, allow_credentials: bool = False) -> dict[str, Any]:
    present = [k for k in API_ENV_KEYS if os.environ.get(k)]
    cleared = {}
    for key in API_ENV_KEYS:
        cleared[key] = key in os.environ
        os.environ.pop(key, None)
    if present and not allow_credentials:
        # Credentials were present but are now cleared; record and continue offline.
        pass
    return {
        "credentials_were_present": present,
        "credentials_cleared": cleared,
        "offline": True,
    }


def _set_created_at(path: Path, frozen_at: str) -> None:
    """Normalize generation timestamp fields so reruns are byte-identical."""
    if not path.is_file() or path.suffix != ".json":
        return
    if path.name == "raw_evaluation_seal.json":
        return
    doc = read_json(path)
    changed = False
    for key in ("created_at", "validated_at", "audited_at"):
        if key in doc and doc[key] != frozen_at:
            doc[key] = frozen_at
            changed = True
    if changed:
        atomic_write_json(path, doc)


def _hash_if_exists(path: Path) -> str | None:
    if not path.is_file():
        return None
    return sha256_file(path)


def regenerate_all(
    *,
    workspace: Path | None = None,
    freeze_timestamps: bool = True,
) -> dict[str, Any]:
    root = workspace or WORKSPACE
    env = assert_offline_environment()

    # P8-01 — fail closed before publishing any regenerated outputs.
    try:
        bundle = load_and_verify_sealed_inputs(
            workspace=root,
            clear_credentials=True,
        )
    except InputValidationError as exc:
        raise EvaluateError(f"sealed input validation failed: {exc}") from exc

    write_validation_report(bundle)
    frozen_at = str(bundle.seal.get("sealed_at") or bundle.seal.get("created_at") or _utcnow())

    steps: list[dict[str, Any]] = []

    def step(name: str, fn) -> Any:
        result = fn()
        steps.append({"step": name, "ok": True})
        return result

    step("per_bug_metrics", lambda: run_per_bug_metrics(workspace=root))
    step("random_metrics", lambda: run_random_metrics(workspace=root))
    step("cost_latency", lambda: run_cost_latency(workspace=root))
    if freeze_timestamps:
        for rel in (
            "results/phase8/input_validation.json",
            "results/phase8/per_bug_metrics.json",
            "results/phase8/random_metrics.json",
            "results/phase8/cost_latency.json",
        ):
            _set_created_at(root / rel, frozen_at)

    step("cohort_summaries", lambda: run_cohort_summaries(workspace=root))
    if freeze_timestamps:
        _set_created_at(root / "results" / "phase8" / "cohort_summaries.json", frozen_at)

    step("statistics", lambda: run_statistics(workspace=root))
    if freeze_timestamps:
        _set_created_at(root / "results" / "statistics.json", frozen_at)

    sidecar = step("report_outputs", lambda: run_report_outputs(workspace=root))
    if freeze_timestamps:
        for rel in (
            "results/phase8/figure_data.json",
            "results/phase8/metrics_csv_sidecar.json",
        ):
            _set_created_at(root / rel, frozen_at)

    checks = run_evaluate_checks(workspace=root)

    artifacts = {
        "metrics_csv": {
            "path": "results/metrics.csv",
            "sha256": _hash_if_exists(root / "results" / "metrics.csv"),
        },
        "statistics_json": {
            "path": "results/statistics.json",
            "sha256": _hash_if_exists(root / "results" / "statistics.json"),
        },
        "headline_table": {
            "path": "results/phase8/headline_table.md",
            "sha256": _hash_if_exists(
                root / "results" / "phase8" / "headline_table.md"
            ),
        },
        "figure_data": {
            "path": "results/phase8/figure_data.json",
            "sha256": _hash_if_exists(
                root / "results" / "phase8" / "figure_data.json"
            ),
        },
        "figures": {
            name: {
                "path": f"results/phase8/figures/{name}",
                "sha256": _hash_if_exists(
                    root / "results" / "phase8" / "figures" / name
                ),
            }
            for name in (
                "figure1_budget_curve.svg",
                "figure2_nftr_cdf.svg",
                "figure3_project_fdr10.svg",
                "figure4_quality_vs_cost.svg",
            )
        },
    }

    record = {
        "schema_version": "jev-phase8-evaluate-regeneration-v1",
        "ok": bool(checks.get("ok")),
        "created_at": frozen_at,
        "regenerated_at_source": "phase7_seal.sealed_at",
        "experiment_commit": bundle.experiment_commit,
        "run_id": bundle.run_id,
        "freeze_tag": bundle.freeze_tag,
        "environment": env,
        "steps": steps,
        "checks": checks,
        "artifacts": artifacts,
        "notes": [
            "Zero provider calls; API credentials cleared",
            "Timestamps normalized to Phase 7 sealed_at for byte-stable JSON",
            "SVG figures and metrics.csv are timestamp-free and hash-stable",
        ],
    }
    if not record["ok"]:
        raise EvaluateError(f"evaluate checks failed: {checks.get('failures')}")
    out = root / "results" / "phase8" / "evaluate_regeneration.json"
    atomic_write_json(out, record)
    record["_write_path"] = str(out)
    record["_sidecar"] = sidecar
    return record


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Regenerate Phase 8 metrics, statistics, tables, and figures "
            "offline from the sealed Phase 7 snapshot."
        )
    )
    parser.add_argument("--workspace", type=Path, default=None)
    parser.add_argument(
        "--allow-live-timestamps",
        action="store_true",
        help="Do not rewrite created_at fields to the Phase 7 sealed_at value",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        record = regenerate_all(
            workspace=args.workspace,
            freeze_timestamps=not args.allow_live_timestamps,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        f"OK evaluate commit={record['experiment_commit'][:12]}… "
        f"metrics={record['artifacts']['metrics_csv']['sha256'][:16]}… "
        f"checks={record['checks']['n_passed']}/{record['checks']['n_checks']} "
        f"path={record.get('_write_path')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
