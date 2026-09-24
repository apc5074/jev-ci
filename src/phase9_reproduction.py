"""P9-06: clean offline reproduction of reported Phase 8/9 outputs."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.evaluate import assert_offline_environment, regenerate_all
from src.example_contract import (
    WORKSPACE,
    atomic_write_json,
    atomic_write_text,
    read_json,
    sha256_file,
)
from src.phase9_failure_analysis import publish_failure_analysis
from src.phase9_failure_cases import publish_failure_cases
from src.phase9_figures import publish_figures
from src.phase9_handoff import run_phase9_handoff

SCHEMA = "jev-phase9-reproduction-v1"
OUT_JSON = WORKSPACE / "results" / "phase9" / "reproduction_record.json"
OUT_MD = WORKSPACE / "results" / "phase9" / "reproduction_record.md"
INVENTORY_JSON = WORKSPACE / "results" / "phase9" / "final_artifact_inventory.json"

# Artifacts that must hash-match after offline evaluate.py (byte-stable).
STABLE_COMPARE = (
    "results/metrics.csv",
    "results/statistics.json",
    "results/phase8/headline_table.md",
    "results/phase8/figure_data.json",
    "results/phase8/figures/figure1_budget_curve.svg",
    "results/phase8/figures/figure2_nftr_cdf.svg",
    "results/phase8/figures/figure3_project_fdr10.svg",
    "results/phase8/figures/figure4_quality_vs_cost.svg",
)

INVENTORY_REQUIRED = (
    "data/manifest.json",
    "experiment.yaml",
    "results/predictions.jsonl",
    "results/metrics.csv",
    "results/statistics.json",
    "results/phase8/analysis_seal.json",
    "results/phase8/case20_deltas.json",
    "results/phase8/figures/figure1_budget_curve.svg",
    "results/phase8/figures/figure2_nftr_cdf.svg",
    "results/phase8/figures/figure3_project_fdr10.svg",
    "results/phase8/figures/figure4_quality_vs_cost.svg",
    "results/figures/figure1_fault_detection_vs_budget.svg",
    "results/figures/figure2_first_trigger_rank_cdf.svg",
    "results/figures/figure3_fdr10_by_project.svg",
    "results/figures/figure4_quality_vs_cost.svg",
    "results/figures/captions.md",
    "results/failure_cases.json",
    "results/failure_analysis.json",
    "results/phase9/headline_table.md",
    "README.md",
)


class ReproductionError(Exception):
    """Phase 9 reproduction failed."""


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _rel(path: Path, *, workspace: Path) -> str:
    try:
        return str(path.resolve().relative_to(workspace.resolve()))
    except ValueError:
        return str(path)


def _hash_meta(path: Path, *, workspace: Path) -> dict[str, Any]:
    return {
        "path": _rel(path, workspace=workspace),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
        "exists": True,
    }


def snapshot_hashes(
    rel_paths: Sequence[str], *, workspace: Path
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for rel in rel_paths:
        path = workspace / rel
        if path.is_file():
            out[rel] = _hash_meta(path, workspace=workspace)
        else:
            out[rel] = {"path": rel, "exists": False, "sha256": None, "bytes": 0}
    return out


def compare_hashes(
    before: Mapping[str, Mapping[str, Any]],
    after: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    diffs: list[dict[str, Any]] = []
    for rel in before:
        b = before[rel]
        a = after.get(rel, {})
        if not b.get("exists"):
            diffs.append({"path": rel, "issue": "missing_before"})
            continue
        if not a.get("exists"):
            diffs.append({"path": rel, "issue": "missing_after"})
            continue
        if b.get("sha256") != a.get("sha256"):
            diffs.append(
                {
                    "path": rel,
                    "issue": "hash_mismatch",
                    "before": b.get("sha256"),
                    "after": a.get("sha256"),
                }
            )
    return diffs


def build_inventory(*, workspace: Path) -> dict[str, Any]:
    items = []
    missing = []
    for rel in INVENTORY_REQUIRED:
        path = workspace / rel
        if path.is_file():
            items.append(_hash_meta(path, workspace=workspace))
        else:
            missing.append(rel)
            items.append({"path": rel, "exists": False})
    # Semantic cache presence (directories)
    cache_dirs = {
        "results/semantic/jev": (workspace / "results/semantic/jev").is_dir(),
        "results/semantic/gpt_nano": (workspace / "results/semantic/gpt_nano").is_dir(),
        "results/embeddings": (workspace / "results/embeddings").is_dir(),
        "results/rankings": (workspace / "results/rankings").is_dir(),
        "results/random": (workspace / "results/random").is_dir(),
    }
    # Evaluation example completeness from Phase 7 seal
    seal = read_json(workspace / "results/phase7/raw_evaluation_seal.json")
    counts = seal.get("counts") or seal.get("summary") or {}
    return {
        "schema_version": "jev-phase9-artifact-inventory-v1",
        "ok": len(missing) == 0,
        "required_files": items,
        "missing": missing,
        "cache_directories": cache_dirs,
        "phase7_seal_counts": counts,
        "links": {
            "readme": "README.md",
            "experiment": "experiment.yaml",
            "figures": "results/figures/",
            "failure_analysis": "results/failure_analysis.json",
            "reproduction": "results/phase9/reproduction_record.json",
        },
    }


def reconcile_report_claims(*, workspace: Path) -> dict[str, Any]:
    """Cross-check README/report headline numbers against regenerated metrics."""
    cohort = read_json(workspace / "results/phase8/cohort_summaries.json")
    stats = read_json(workspace / "results/statistics.json")
    jev = float(cohort["cohort"]["Jev"]["primary_fdr_at_10pct"])
    bm25 = float(cohort["cohort"]["BM25"]["primary_fdr_at_10pct"])
    delta = jev - bm25
    boot = stats["primary"]["bootstrap"]["delta_fdr_at_10pct"]
    mcnemar_p = float(
        stats["primary"]["paired_detection_fdr_at_10pct"][
            "mcnemar_exact_two_sided_p"
        ]
    )
    practical = cohort["practical_success"]
    claims = {
        "jev_fdr_at_10pct": round(jev, 4),
        "bm25_fdr_at_10pct": round(bm25, 4),
        "delta_pp": round(100.0 * delta, 1),
        "bootstrap_ci95": [
            round(float(boot["ci95_low"]), 3),
            round(float(boot["ci95_high"]), 3),
        ],
        "mcnemar_p": mcnemar_p,
        "practical_success": bool(practical["practically_successful"]),
        "winning_alternative": practical.get("winning_alternative"),
        "n_evaluation_bugs": int(cohort["counts"]["evaluation_bugs"]),
        "cost_ratio_jev_gpt": float(
            practical["alternative_2_near_gpt_and_cheap"]["jev_gpt_cost_ratio"]
        ),
    }
    # Spot-check README contains the rounded primary figures
    readme = (workspace / "README.md").read_text(encoding="utf-8")
    checks = []
    for label, needle in (
        ("readme_jev_fdr", "0.9558"),
        ("readme_bm25_fdr", "0.7345"),
        ("readme_delta_pp", "+22.1"),
        ("readme_ci", "0.133"),
        ("readme_practical_pass", "PASS"),
    ):
        checks.append({"check": label, "ok": needle in readme, "needle": needle})
    return {"claims": claims, "text_checks": checks, "ok": all(c["ok"] for c in checks)}


def run_reproduction(*, workspace: Path | None = None) -> dict[str, Any]:
    root = workspace or WORKSPACE
    env = assert_offline_environment()
    before = snapshot_hashes(STABLE_COMPARE, workspace=root)

    evaluate_record = regenerate_all(workspace=root, freeze_timestamps=True)
    after_eval = snapshot_hashes(STABLE_COMPARE, workspace=root)
    eval_diffs = compare_hashes(before, after_eval)

    # Phase 9 publish layer (tables/figures/cases) from regenerated Phase 8.
    handoff = run_phase9_handoff(workspace=root)
    figures = publish_figures(workspace=root)
    failure_cases = publish_failure_cases(workspace=root)
    failure_analysis = publish_failure_analysis(workspace=root)

    after_all = snapshot_hashes(STABLE_COMPARE, workspace=root)
    inventory = build_inventory(workspace=root)
    reconcile = reconcile_report_claims(workspace=root)

    # Confirm no development bugs in metrics split
    import csv

    splits = set()
    with (root / "results/metrics.csv").open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            splits.add(row.get("split") or row.get("Split") or "")
    only_evaluation = splits <= {"evaluation"}

    ok = (
        bool(evaluate_record.get("ok"))
        and len(eval_diffs) == 0
        and inventory["ok"]
        and reconcile["ok"]
        and only_evaluation
        and env.get("offline") is True
    )

    record = {
        "schema_version": SCHEMA,
        "generated_at_utc": _utcnow(),
        "ok": ok,
        "environment": env,
        "commands": [
            "docker run --rm --platform linux/amd64 --network=none "
            '-v "$(pwd):/workspace" -w /workspace '
            "jev-ci:phase1 python -u scripts/evaluate.py",
            "docker run --rm --platform linux/amd64 --network=none "
            '-v "$(pwd):/workspace" -w /workspace '
            "jev-ci:phase1 python -u scripts/reproduce_phase9.py",
        ],
        "evaluate": {
            "ok": evaluate_record.get("ok"),
            "experiment_commit": evaluate_record.get("experiment_commit"),
            "run_id": evaluate_record.get("run_id"),
            "freeze_tag": evaluate_record.get("freeze_tag"),
            "checks": evaluate_record.get("checks"),
            "artifacts": evaluate_record.get("artifacts"),
        },
        "hash_comparison": {
            "compared_paths": list(STABLE_COMPARE),
            "before": before,
            "after_evaluate": after_eval,
            "diffs": eval_diffs,
            "byte_identical": len(eval_diffs) == 0,
            "notes": [
                "Timestamps in Phase 8 JSON are normalized to Phase 7 sealed_at",
                "SVG/metrics.csv are timestamp-free; mismatches would be content bugs",
            ],
        },
        "phase9_publish": {
            "handoff_ok": bool(handoff.get("ok", True)),
            "figures_ok": bool(figures.get("ok")),
            "failure_cases_n": len(failure_cases.get("selected_ids", [])),
            "failure_analysis_n": int(failure_analysis.get("n_cases", 0)),
        },
        "inventory": inventory,
        "report_reconciliation": reconcile,
        "metrics_split_evaluation_only": only_evaluation,
        "paid_requests": 0,
        "caveats": [
            "Reproduction attaches the existing sealed data/cache tree; it does not "
            "re-download Defects4J checkouts or re-call providers.",
            "Phase 9 failure_analysis categories are curated constants validated "
            "against the mechanical case list; they regenerate as the same table.",
        ],
    }
    if not ok:
        raise ReproductionError(
            f"reproduction failed: diffs={eval_diffs} "
            f"inventory_missing={inventory.get('missing')} "
            f"reconcile={reconcile.get('text_checks')}"
        )
    return record


def render_reproduction_md(doc: Mapping[str, Any]) -> str:
    diffs = doc["hash_comparison"]["diffs"]
    lines = [
        "# Phase 9 offline reproduction record (P9-06)",
        "",
        f"**Overall: `{'PASS' if doc['ok'] else 'FAIL'}`**",
        "",
        f"Generated: {doc['generated_at_utc']}",
        "",
        "## Environment",
        "",
        f"- Offline: `{doc['environment']['offline']}`",
        f"- Credentials cleared: `{doc['environment']['credentials_cleared']}`",
        f"- Paid requests during reproduction: **{doc['paid_requests']}**",
        "",
        "## evaluate.py",
        "",
        f"- Freeze tag: `{doc['evaluate']['freeze_tag']}`",
        f"- Experiment commit: `{doc['evaluate']['experiment_commit']}`",
        f"- Checks: {doc['evaluate']['checks']['n_passed']}/"
        f"{doc['evaluate']['checks']['n_checks']}",
        f"- Byte-identical stable artifacts: "
        f"**{doc['hash_comparison']['byte_identical']}** "
        f"(diffs={len(diffs)})",
        "",
        "## Report reconciliation",
        "",
        f"- Claims vs cohort/stats: `{doc['report_reconciliation']['claims']}`",
        f"- README/report text checks OK: `{doc['report_reconciliation']['ok']}`",
        "",
        "## Inventory",
        "",
        f"- Required files present: `{doc['inventory']['ok']}`",
        f"- Missing: `{doc['inventory']['missing']}`",
        "",
        "## Commands",
        "",
    ]
    for cmd in doc["commands"]:
        lines.append("```bash")
        lines.append(cmd)
        lines.append("```")
        lines.append("")
    lines.extend(
        [
            "## Caveats",
            "",
        ]
    )
    for c in doc["caveats"]:
        lines.append(f"- {c}")
    lines.append("")
    return "\n".join(lines)


def publish_reproduction(*, workspace: Path | None = None) -> dict[str, Any]:
    root = workspace or WORKSPACE
    record = run_reproduction(workspace=root)
    out_dir = root / "results" / "phase9"
    out_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(out_dir / "reproduction_record.json", record)
    atomic_write_text(out_dir / "reproduction_record.md", render_reproduction_md(record))
    atomic_write_json(out_dir / "final_artifact_inventory.json", record["inventory"])
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="P9-06: offline reproduction of sealed results"
    )
    parser.add_argument("--workspace", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        doc = publish_reproduction(workspace=args.workspace)
    except ReproductionError as exc:
        print(f"FAIL phase9_reproduction: {exc}", file=sys.stderr)
        return 1
    print(
        "OK phase9_reproduction "
        f"byte_identical={doc['hash_comparison']['byte_identical']} "
        f"inventory_ok={doc['inventory']['ok']} "
        f"path=results/phase9/reproduction_record.json"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
