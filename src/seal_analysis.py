"""Seal Phase 8 analyzed results and hand off to Phase 9 (P8-09)."""

from __future__ import annotations

import argparse
import csv
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.cohort_summaries import materialize_jev_record, index_nonrandom_records
from src.example_contract import (
    WORKSPACE,
    ExampleId,
    atomic_write_json,
    atomic_write_text,
    read_json,
    sha256_file,
)
from src.evaluate_checks import run_evaluate_checks

SEAL_PATH = WORKSPACE / "results" / "phase8" / "analysis_seal.json"
AUDIT_PATH = WORKSPACE / "results" / "phase8" / "analysis_audit.json"
HANDOFF_PATH = WORKSPACE / "docs" / "phase8-handoff.md"
CASE20_PATH = WORKSPACE / "results" / "phase8" / "case20_deltas.json"
SEAL_SCHEMA = "jev-phase8-analysis-seal-v1"


class AnalysisSealError(Exception):
    """Phase 8 analysis seal / audit failed."""


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _rel(path: Path, *, workspace: Path) -> str:
    try:
        return str(path.resolve().relative_to(workspace.resolve()))
    except ValueError:
        return str(path)


def _hash(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise AnalysisSealError(f"missing artifact: {path}")
    return {
        "path": _rel(path, workspace=WORKSPACE),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
    }


def load_metrics_rows(workspace: Path) -> list[dict[str, str]]:
    path = workspace / "results" / "metrics.csv"
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _as_float(value: str | float | int | None) -> float:
    if value is None or value == "":
        raise AnalysisSealError("expected numeric field")
    return float(value)


def _as_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).lower() == "true"


def audit_cross_file_consistency(*, workspace: Path) -> dict[str, Any]:
    """Check CSV ↔ rankings ↔ cohort ↔ statistics ↔ cost agreement."""
    errors: list[str] = []
    notes: list[str] = []

    rows = load_metrics_rows(workspace)
    if len(rows) != 625:
        errors.append(f"metrics.csv has {len(rows)} rows, expected 625")

    by_bug_method: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        key = (row["qualified_id"], row["method"])
        if key in by_bug_method:
            errors.append(f"duplicate metrics row {key}")
        by_bug_method[key] = row

    # Spot-check: CSV first_trigger_rank matches ranking for BM25 sample of all bugs
    for qid in sorted({r["qualified_id"] for r in rows}):
        ex = ExampleId.parse(qid)
        slug = ex.slug
        ranking = read_json(workspace / "results" / "rankings" / f"{slug}.json")
        labels = read_json(workspace / "data" / "tests" / slug / "labels.json")
        positives = set(labels["positive_classes"])
        ranked = [e["test_class"] for e in ranking["ranking"]]
        r = min(i for i, c in enumerate(ranked, start=1) if c in positives)
        csv_r = _as_float(by_bug_method[(qid, "BM25")]["first_trigger_rank"])
        if abs(csv_r - r) > 1e-9:
            errors.append(f"{qid} BM25 CSV rank {csv_r} != ranking {r}")

        jev_row = by_bug_method[(qid, "Jev")]
        jev_path = workspace / "results" / "semantic" / "jev" / f"{slug}.json"
        if jev_path.is_file():
            jev_doc = read_json(jev_path)
            j_ranked = list(
                jev_doc.get("ranked_ids")
                or [e["test_class"] for e in jev_doc["ranking"]]
            )
            jr = min(i for i, c in enumerate(j_ranked, start=1) if c in positives)
            csv_jr = _as_float(jev_row["first_trigger_rank"])
            if abs(csv_jr - jr) > 1e-9:
                errors.append(f"{qid} Jev CSV rank {csv_jr} != ranking {jr}")
        else:
            n = int(by_bug_method[(qid, "BM25")]["num_test_classes"])
            if abs(_as_float(jev_row["first_trigger_rank"]) - n) > 1e-9:
                errors.append(f"{qid} missing Jev ranking but CSV rank != N")

    # Cohort FDR@10% vs CSV means
    cohort = read_json(workspace / "results" / "phase8" / "cohort_summaries.json")
    for method in ("BM25", "Embedding", "Jev", "GPT-Nano", "Random"):
        method_rows = [r for r in rows if r["method"] == method]
        if len(method_rows) != 125:
            errors.append(f"{method}: expected 125 CSV rows, got {len(method_rows)}")
            continue
        if method == "Random":
            mean_det = sum(_as_float(r["detected_at_10pct"]) for r in method_rows) / 125.0
        else:
            mean_det = (
                sum(1 for r in method_rows if _as_bool(r["detected_at_10pct"])) / 125.0
            )
        reported = float(cohort["cohort"][method]["primary_fdr_at_10pct"])
        if abs(mean_det - reported) > 1e-9:
            errors.append(
                f"{method} FDR@10 CSV mean {mean_det} != cohort {reported}"
            )

    # Statistics primary delta FDR matches cohort
    stats = read_json(workspace / "results" / "statistics.json")
    jev_fdr = float(cohort["cohort"]["Jev"]["primary_fdr_at_10pct"])
    bm25_fdr = float(cohort["cohort"]["BM25"]["primary_fdr_at_10pct"])
    point = float(stats["primary"]["bootstrap"]["delta_fdr_at_10pct"]["point"])
    if abs(point - (jev_fdr - bm25_fdr)) > 1e-12:
        errors.append(
            f"stats delta FDR {point} != cohort Jev-BM25 {jev_fdr - bm25_fdr}"
        )

    # Cost totals: sum CSV Jev costs ≈ cohort * 125 for bugs with costs
    cost = read_json(workspace / "results" / "phase8" / "cost_latency.json")
    for method in ("Embedding", "Jev", "GPT-Nano"):
        csv_sum = 0.0
        n_cost = 0
        for r in rows:
            if r["method"] != method:
                continue
            val = r.get("reranker_cost_usd") or ""
            if val == "":
                continue
            csv_sum += float(val)
            n_cost += 1
        reported = float(
            cost["methods"][method]["cost"]["cohort"]["effective_prepaid_credits_usd"]
        )
        if abs(csv_sum - reported) > 1e-6:
            errors.append(
                f"{method} CSV cost sum {csv_sum} != cost cohort {reported}"
            )
        notes.append(f"{method}: cost rows with values={n_cost}")

    # Figure data denominators
    fig = read_json(workspace / "results" / "phase8" / "figure_data.json")
    for method, pts in fig["figure1_budget_curve"].items():
        if abs(float(pts[3]["fdr"]) - float(cohort["cohort"][method]["primary_fdr_at_10pct"])) > 1e-12:
            errors.append(f"figure1 {method} FDR@10 mismatch")
    for project, block in fig["figure3_project_fdr10"].items():
        for method, fdr in block.items():
            expected = float(
                cohort["projects"][project]["methods"][method]["primary_fdr_at_10pct"]
            )
            if abs(float(fdr) - expected) > 1e-12:
                errors.append(f"figure3 {project}/{method} FDR mismatch")

    # Evaluate checks
    checks = run_evaluate_checks(workspace=workspace)
    if not checks.get("ok"):
        errors.append(f"evaluate_checks failed: {checks.get('failures')}")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "evaluate_checks": checks,
        "n_metrics_rows": len(rows),
    }


def build_case20_deltas(*, workspace: Path) -> dict[str, Any]:
    """Deterministic BM25−Jev first-trigger rank deltas for Phase 9's 20-case review."""
    per_bug = read_json(workspace / "results" / "phase8" / "per_bug_metrics.json")
    by_bug = index_nonrandom_records(per_bug["records"])
    ordered = sorted(
        by_bug.keys(),
        key=lambda x: (x.split("-")[0], int(x.split("-")[1])),
    )
    rows: list[dict[str, Any]] = []
    for qid in ordered:
        bm25 = by_bug[qid]["BM25"]
        jev = materialize_jev_record(by_bug[qid]["Jev"])
        bm25_r = int(bm25["first_trigger_rank"])
        jev_r = int(jev["first_trigger_rank"])
        delta = bm25_r - jev_r  # positive => Jev earlier
        rows.append(
            {
                "qualified_id": qid,
                "project": bm25["project"],
                "bug_id": bm25["bug_id"],
                "bm25_first_trigger_rank": bm25_r,
                "jev_first_trigger_rank": jev_r,
                "delta_bm25_minus_jev": delta,
                "candidate_trigger_in_top200": bool(
                    bm25["candidate_trigger_in_top200"]
                ),
                "jev_available": bool(jev.get("available", True)),
                "jev_imputed": bool(jev.get("imputed", False)),
            }
        )

    # Tie-break: larger |interest| then manifest project/bug order (already sorted).
    gains = sorted(
        rows,
        key=lambda r: (-r["delta_bm25_minus_jev"], r["project"], int(r["bug_id"])),
    )[:10]
    losses = sorted(
        rows,
        key=lambda r: (r["delta_bm25_minus_jev"], r["project"], int(r["bug_id"])),
    )[:10]
    selected_ids = [r["qualified_id"] for r in gains] + [
        r["qualified_id"] for r in losses
    ]
    if len(set(selected_ids)) != 20:
        # Overlap when many zeros — drop duplicates from losses side first.
        seen = {r["qualified_id"] for r in gains}
        losses_unique = []
        for r in sorted(
            rows,
            key=lambda r: (r["delta_bm25_minus_jev"], r["project"], int(r["bug_id"])),
        ):
            if r["qualified_id"] in seen:
                continue
            losses_unique.append(r)
            seen.add(r["qualified_id"])
            if len(losses_unique) == 10:
                break
        losses = losses_unique
        selected_ids = [r["qualified_id"] for r in gains] + [
            r["qualified_id"] for r in losses
        ]
    if len(set(selected_ids)) != 20:
        raise AnalysisSealError(
            f"could not form 20 distinct case IDs (got {len(set(selected_ids))})"
        )

    return {
        "schema_version": "jev-phase8-case20-deltas-v1",
        "rule": (
            "delta = BM25_first_trigger_rank - Jev_first_trigger_rank; "
            "10 largest deltas (Jev gains) + 10 smallest (Jev losses); "
            "tie-break: project name then numeric bug_id (manifest order family)"
        ),
        "n_evaluation_bugs": len(rows),
        "all_deltas": rows,
        "top10_jev_gains": gains,
        "top10_jev_losses": losses,
        "selected_ids": selected_ids,
    }


def build_analysis_seal(
    *,
    workspace: Path,
    audit: Mapping[str, Any],
    case20: Mapping[str, Any],
) -> dict[str, Any]:
    phase7_seal = read_json(
        workspace / "results" / "phase7" / "raw_evaluation_seal.json"
    )
    cohort = read_json(workspace / "results" / "phase8" / "cohort_summaries.json")
    regen = read_json(workspace / "results" / "phase8" / "evaluate_regeneration.json")

    artifacts = {
        "metrics_csv": _hash(workspace / "results" / "metrics.csv"),
        "statistics_json": _hash(workspace / "results" / "statistics.json"),
        "headline_table": _hash(
            workspace / "results" / "phase8" / "headline_table.md"
        ),
        "figure_data": _hash(workspace / "results" / "phase8" / "figure_data.json"),
        "cohort_summaries": _hash(
            workspace / "results" / "phase8" / "cohort_summaries.json"
        ),
        "cost_latency": _hash(workspace / "results" / "phase8" / "cost_latency.json"),
        "evaluate_regeneration": _hash(
            workspace / "results" / "phase8" / "evaluate_regeneration.json"
        ),
        "case20_deltas": None,  # filled after write
        "figures": {
            name: _hash(workspace / "results" / "phase8" / "figures" / name)
            for name in (
                "figure1_budget_curve.svg",
                "figure2_nftr_cdf.svg",
                "figure3_project_fdr10.svg",
                "figure4_quality_vs_cost.svg",
            )
        },
    }

    deviations = [
        {
            "id": "A-001-eval",
            "kind": "availability",
            "detail": (
                "12 Jsoup evaluation bugs lack Jev rankings (OpenRouter WAF). "
                "Phase 8 imputes non-detection with r=N for denom-125 headlines."
            ),
        },
        {
            "id": "D-wallclock",
            "kind": "measurement",
            "detail": (
                "Shortlist wall times reconstructed from per-request latencies at "
                "concurrency 16; Phase 7 did not persist end-to-end walls."
            ),
        },
        {
            "id": "D-tag-name",
            "kind": "naming",
            "detail": (
                "Freeze tag is experiment-v1 (overall.md historically said "
                "experiment-v1-frozen)."
            ),
        },
    ]

    return {
        "schema_version": SEAL_SCHEMA,
        "ok": bool(audit.get("ok")),
        "sealed_at": _utcnow(),
        "freeze_tag": phase7_seal.get("freeze_tag"),
        "experiment_commit": phase7_seal.get("experiment_commit"),
        "run_id": phase7_seal.get("run_id"),
        "phase7_seal": {
            "path": "results/phase7/raw_evaluation_seal.json",
            "sha256": sha256_file(
                workspace / "results" / "phase7" / "raw_evaluation_seal.json"
            ),
            "predictions_sha256": phase7_seal["predictions"]["sha256"],
            "raw_result_index_sha256": phase7_seal["raw_result_index"]["sha256"],
        },
        "phase8_artifacts": artifacts,
        "practical_success": cohort["practical_success"],
        "candidate_ceiling": cohort["candidate_ceiling"],
        "projects": {
            project: {
                "denominator": 25,
                "fdr_at_10pct": {
                    method: block["methods"][method]["primary_fdr_at_10pct"]
                    for method in block["methods"]
                },
            }
            for project, block in cohort["projects"].items()
        },
        "jev_miss_classification": cohort["jev_miss_classification"],
        "case20": {
            "path": "results/phase8/case20_deltas.json",
            "selected_ids": case20["selected_ids"],
            "rule": case20["rule"],
        },
        "evaluate_command": (
            "docker run --rm --platform linux/amd64 --network=none "
            '-v "$(pwd):/workspace" -w /workspace '
            "jev-ci:phase1 python -u scripts/evaluate.py"
        ),
        "deviations": deviations,
        "audit_ok": audit.get("ok"),
        "regeneration_ok": regen.get("ok"),
        "notes": [
            "Do not overwrite Phase 7 sealed raw data",
            "Phase 9 must interpret these hashes; exploratory work stays separate",
        ],
    }


def render_handoff_markdown(seal: Mapping[str, Any]) -> str:
    ps = seal["practical_success"]
    ceiling = seal["candidate_ceiling"]
    misses = seal["jev_miss_classification"]
    lines = [
        "# Phase 8 → Phase 9 handoff",
        "",
        f"**Overall: `{'PASS' if seal.get('ok') else 'FAIL'}`**",
        "",
        "Phase 8 analyzed results are sealed. Phase 9 interprets and presents them",
        "without changing methods, raw data, metrics, or the headline lineup.",
        "",
        "## Freeze identity",
        "",
        f"- `freeze_tag`: `{seal.get('freeze_tag')}`",
        f"- `experiment_commit`: `{seal.get('experiment_commit')}`",
        f"- `run_id`: `{seal.get('run_id')}`",
        f"- `sealed_at`: `{seal.get('sealed_at')}`",
        "",
        "## Canonical outputs",
        "",
        "| Artifact | Path | SHA-256 |",
        "| --- | --- | --- |",
    ]
    for key, meta in seal["phase8_artifacts"].items():
        if key == "figures":
            continue
        if not isinstance(meta, dict) or "path" not in meta:
            continue
        lines.append(f"| {key} | `{meta['path']}` | `{meta['sha256']}` |")
    for name, meta in seal["phase8_artifacts"]["figures"].items():
        lines.append(f"| figure {name} | `{meta['path']}` | `{meta['sha256']}` |")

    lines.extend(
        [
            "",
            "## Practical success",
            "",
            f"- **Result:** `{'PASS' if ps.get('practically_successful') else 'FAIL'}`",
            f"- Winning alternative: `{ps.get('winning_alternative')}`",
            f"- FDR@10% Jev={ps['fdr_at_10pct']['Jev']:.4f}, "
            f"BM25={ps['fdr_at_10pct']['BM25']:.4f}, "
            f"GPT-Nano={ps['fdr_at_10pct']['GPT-Nano']:.4f}",
            f"- Alt1 Δpp Jev−BM25: "
            f"{ps['alternative_1_beat_bm25_by_5pp']['delta_pp_jev_minus_bm25']:.1f}",
            f"- Alt2 cost ratio Jev/GPT: "
            f"{ps['alternative_2_near_gpt_and_cheap']['jev_gpt_cost_ratio']:.4f}",
            "",
            "## Candidate ceiling",
            "",
            f"- BM25 trigger recall@min(200,N): "
            f"**{ceiling['numerator']}/{ceiling['denominator']} = {ceiling['recall']:.4f}**",
            "",
            "## Jev misses @10%",
            "",
            f"- Detections: {misses['n_detections']}",
            f"- Misses: {misses['n_misses']}",
            f"- Candidate-generation: "
            f"{misses['candidate_generation_misses']['count']}",
            f"- Reranker: {misses['reranker_misses']['count']}",
            f"- Reranker IDs: `{', '.join(misses['reranker_misses']['bug_ids'])}`",
            "",
            "## 20-case qualitative review list",
            "",
            f"- Path: `{seal['case20']['path']}`",
            f"- Rule: {seal['case20']['rule']}",
            f"- IDs: `{', '.join(seal['case20']['selected_ids'])}`",
            "",
            "## Offline regenerate",
            "",
            "```bash",
            seal["evaluate_command"],
            "```",
            "",
            "## Deviations (transparent)",
            "",
        ]
    )
    for d in seal.get("deviations") or []:
        lines.append(f"- **{d['id']}** ({d['kind']}): {d['detail']}")
    lines.append("")
    return "\n".join(lines)


def run_seal_analysis(
    *,
    workspace: Path | None = None,
) -> dict[str, Any]:
    root = workspace or WORKSPACE
    audit = audit_cross_file_consistency(workspace=root)
    case20 = build_case20_deltas(workspace=root)
    atomic_write_json(root / "results" / "phase8" / "case20_deltas.json", case20)

    seal = build_analysis_seal(workspace=root, audit=audit, case20=case20)
    seal["phase8_artifacts"]["case20_deltas"] = _hash(
        root / "results" / "phase8" / "case20_deltas.json"
    )
    # Freeze seal timestamp for determinism relative to evaluate sealed_at when possible
    phase7 = read_json(root / "results" / "phase7" / "raw_evaluation_seal.json")
    seal["sealed_at"] = str(phase7.get("sealed_at") or _utcnow())

    atomic_write_json(
        root / "results" / "phase8" / "analysis_audit.json",
        {
            "schema_version": "jev-phase8-analysis-audit-v1",
            "created_at": seal["sealed_at"],
            **audit,
        },
    )
    seal_path = root / "results" / "phase8" / "analysis_seal.json"
    atomic_write_json(seal_path, seal)
    seal["seal_sha256"] = sha256_file(seal_path)
    atomic_write_json(seal_path, seal)

    handoff = render_handoff_markdown(seal)
    handoff_path = root / "docs" / "phase8-handoff.md"
    atomic_write_text(handoff_path, handoff)

    if not audit["ok"]:
        raise AnalysisSealError(f"analysis audit failed: {audit['errors'][:5]}")
    return seal


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=None)
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        seal = run_seal_analysis(workspace=args.workspace)
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        f"OK analysis_seal practical_success="
        f"{seal['practical_success']['practically_successful']} "
        f"case20={len(seal['case20']['selected_ids'])} "
        f"sha256={seal.get('seal_sha256', '')[:16]}…"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
