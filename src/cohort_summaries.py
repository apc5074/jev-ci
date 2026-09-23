"""Cohort, project, and candidate-ceiling summaries (P8-05).

Builds on sealed P8-02/P8-03/P8-04 artifacts. Headline FDR denominators are
always **125** evaluation bugs. Unavailable Jev rankings (A-001 gaps) count as
non-detections at every budget and receive worst-case continuous metrics
(``r = N``) so every method has a full 125-bug lineup for descriptive tables.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.example_contract import WORKSPACE, atomic_write_json, read_json, sha256_file
from src.metrics import BUDGET_LABELS, apfd, reciprocal_rank

SUMMARY_PATH = WORKSPACE / "results" / "phase8" / "cohort_summaries.json"
SUMMARY_SCHEMA = "jev-phase8-cohort-summaries-v1"
METHODS = ("Random", "BM25", "Embedding", "Jev", "GPT-Nano")
PROJECTS = ("Cli", "Lang", "Math", "Jsoup", "JacksonDatabind")
EVAL_BUGS = 125
PROJECT_BUGS = 25


class CohortSummaryError(Exception):
    """Cohort / project summary failed."""


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _mean(values: Sequence[float]) -> float:
    if not values:
        raise CohortSummaryError("mean of empty sequence")
    return float(sum(values) / len(values))


def _median(values: Sequence[float]) -> float:
    if not values:
        raise CohortSummaryError("median of empty sequence")
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return float(ordered[mid])
    return float((ordered[mid - 1] + ordered[mid]) / 2.0)


def _pp(delta_fraction: float) -> float:
    """Absolute percentage points from a fraction difference."""
    return 100.0 * float(delta_fraction)


def load_phase8_inputs(
    *,
    workspace: Path,
) -> dict[str, Any]:
    per_bug_path = workspace / "results" / "phase8" / "per_bug_metrics.json"
    random_path = workspace / "results" / "phase8" / "random_metrics.json"
    cost_path = workspace / "results" / "phase8" / "cost_latency.json"
    for path in (per_bug_path, random_path, cost_path):
        if not path.is_file():
            raise CohortSummaryError(f"missing Phase 8 artifact: {path}")
    return {
        "per_bug": read_json(per_bug_path),
        "random": read_json(random_path),
        "cost": read_json(cost_path),
        "paths": {
            "per_bug_metrics": "results/phase8/per_bug_metrics.json",
            "random_metrics": "results/phase8/random_metrics.json",
            "cost_latency": "results/phase8/cost_latency.json",
        },
        "hashes": {
            "per_bug_metrics": sha256_file(per_bug_path),
            "random_metrics": sha256_file(random_path),
            "cost_latency": sha256_file(cost_path),
        },
    }


def index_nonrandom_records(
    records: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, dict[str, Any]]]:
    """qualified_id -> method -> record."""
    out: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for rec in records:
        out[str(rec["qualified_id"])][str(rec["method"])] = dict(rec)
    return out


def materialize_jev_record(rec: Mapping[str, Any]) -> dict[str, Any]:
    """Impute worst-case continuous metrics when Jev ranking is unavailable."""
    row = dict(rec)
    if row.get("available"):
        return row
    n = int(row["num_test_classes"])
    r = n
    row["imputed"] = True
    row["imputation"] = "worst_case_r_equals_N_for_unavailable_jev"
    row["first_trigger_rank"] = r
    row["normalized_first_trigger_rank"] = 1.0
    row["reciprocal_rank"] = reciprocal_rank(r)
    row["apfd"] = apfd(r=r, n=n)
    for label in BUDGET_LABELS:
        row[f"detected_at_{label}"] = False
    return row


def method_detection_fraction(
    rows: Sequence[Mapping[str, Any]],
    *,
    label: str,
) -> float:
    if len(rows) not in {EVAL_BUGS, PROJECT_BUGS}:
        raise CohortSummaryError(f"unexpected row count {len(rows)}")
    field = f"detected_at_{label}"
    values: list[float] = []
    for row in rows:
        val = row.get(field)
        if isinstance(val, bool):
            values.append(1.0 if val else 0.0)
        elif isinstance(val, (int, float)):
            hits_frac = float(val)
            if not (0.0 <= hits_frac <= 1.0) or not math.isfinite(hits_frac):
                raise CohortSummaryError(f"bad fractional detection {hits_frac}")
            values.append(hits_frac)
        else:
            raise CohortSummaryError(f"missing {field}")
    return _mean(values)


def summarize_method_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    method: str,
    cost_per_bug: float | None,
    latency: Mapping[str, Any] | None,
) -> dict[str, Any]:
    n = len(rows)
    fdr = {
        f"fdr_at_{label}": method_detection_fraction(rows, label=label)
        for label in BUDGET_LABELS
    }
    rr = [float(r["reciprocal_rank"]) for r in rows]
    apfds = [float(r["apfd"]) for r in rows]
    nftrs = [float(r["normalized_first_trigger_rank"]) for r in rows]
    return {
        "method": method,
        "denominator": n,
        **fdr,
        "primary_fdr_at_10pct": fdr["fdr_at_10pct"],
        "mrr": _mean(rr),
        "mean_apfd": _mean(apfds),
        "mean_nftr": _mean(nftrs),
        "median_nftr": _median(nftrs),
        "cost_usd_per_bug": cost_per_bug,
        "request_latency_ms": (
            {
                "mean": (latency or {}).get("request_latency_ms", {}).get("mean"),
                "p50": (latency or {}).get("request_latency_ms", {}).get("p50"),
                "p95": (latency or {}).get("request_latency_ms", {}).get("p95"),
            }
            if latency
            else None
        ),
    }


def candidate_recall_at_200(rows_bm25: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if len(rows_bm25) != EVAL_BUGS:
        raise CohortSummaryError("candidate recall requires 125 BM25 rows")
    hits = [
        r
        for r in rows_bm25
        if r.get("candidate_trigger_in_top200") is True
    ]
    return {
        "metric": "bm25_trigger_recall_at_min_200_N",
        "denominator": EVAL_BUGS,
        "numerator": len(hits),
        "recall": len(hits) / float(EVAL_BUGS),
        "source": "sealed_candidate_ids_prefix",
    }


def classify_jev_misses(
    jev_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Classify every Jev non-detection at 10% as candidate vs reranker miss."""
    if len(jev_rows) != EVAL_BUGS:
        raise CohortSummaryError("Jev miss classification requires 125 rows")
    candidate_misses: list[str] = []
    reranker_misses: list[str] = []
    detections: list[str] = []
    for row in jev_rows:
        qid = str(row["qualified_id"])
        detected = bool(row.get("detected_at_10pct"))
        in_shortlist = bool(row.get("candidate_trigger_in_top200"))
        if detected:
            detections.append(qid)
            continue
        if in_shortlist:
            reranker_misses.append(qid)
        else:
            candidate_misses.append(qid)
    classified = len(candidate_misses) + len(reranker_misses)
    expected_misses = EVAL_BUGS - len(detections)
    if classified != expected_misses:
        raise CohortSummaryError(
            f"miss classification count {classified} != expected {expected_misses}"
        )
    return {
        "budget": "10pct",
        "denominator": EVAL_BUGS,
        "detections": sorted(detections),
        "n_detections": len(detections),
        "candidate_generation_misses": {
            "count": len(candidate_misses),
            "bug_ids": sorted(candidate_misses),
            "rule": "no_trigger_in_bm25_shortlist",
        },
        "reranker_misses": {
            "count": len(reranker_misses),
            "bug_ids": sorted(reranker_misses),
            "rule": (
                "trigger_in_bm25_shortlist_but_jev_not_detected_at_10pct "
                "(includes unavailable A-001 gaps imputed as non-detections)"
            ),
        },
        "n_misses": expected_misses,
    }


def practical_success_table(
    *,
    fdr: Mapping[str, float],
    cost_ratio: Mapping[str, Any],
) -> dict[str, Any]:
    jev = float(fdr["Jev"])
    bm25 = float(fdr["BM25"])
    gpt = float(fdr["GPT-Nano"])
    delta_bm25_pp = _pp(jev - bm25)
    delta_gpt_pp = _pp(jev - gpt)
    abs_delta_gpt_pp = abs(delta_gpt_pp)
    ratio = float(cost_ratio["ratio"])
    alt1 = jev >= bm25 + 0.05
    alt2 = (abs(jev - gpt) <= 0.02) and bool(cost_ratio["jev_leq_30pct_of_gpt"])
    return {
        "criterion": (
            "Jev practically successful if (FDR10 >= BM25 + 5pp) OR "
            "(within 2pp of GPT-Nano AND cost <= 30% of GPT)"
        ),
        "fdr_at_10pct": {
            "Jev": jev,
            "BM25": bm25,
            "GPT-Nano": gpt,
            "Embedding": float(fdr["Embedding"]),
            "Random": float(fdr["Random"]),
        },
        "alternative_1_beat_bm25_by_5pp": {
            "delta_pp_jev_minus_bm25": delta_bm25_pp,
            "threshold_pp": 5.0,
            "passed": alt1,
        },
        "alternative_2_near_gpt_and_cheap": {
            "delta_pp_jev_minus_gpt": delta_gpt_pp,
            "abs_delta_pp": abs_delta_gpt_pp,
            "within_2pp": abs_delta_gpt_pp <= 2.0,
            "jev_gpt_cost_ratio": ratio,
            "cost_ratio_threshold": 0.30,
            "cost_ratio_passed": bool(cost_ratio["jev_leq_30pct_of_gpt"]),
            "numerator_jev_usd": cost_ratio["numerator_jev_usd"],
            "denominator_gpt_usd": cost_ratio["denominator_gpt_usd"],
            "passed": alt2,
        },
        "practically_successful": alt1 or alt2,
        "winning_alternative": (
            "alt1" if alt1 else ("alt2" if alt2 else None)
        ),
    }


def build_cohort_summaries(
    *,
    workspace: Path | None = None,
) -> dict[str, Any]:
    root = workspace or WORKSPACE
    inputs = load_phase8_inputs(workspace=root)
    per_bug = inputs["per_bug"]
    random_doc = inputs["random"]
    cost = inputs["cost"]

    by_bug = index_nonrandom_records(per_bug["records"])
    random_by_bug = {
        str(r["qualified_id"]): dict(r) for r in random_doc["records"]
    }
    if len(by_bug) != EVAL_BUGS or len(random_by_bug) != EVAL_BUGS:
        raise CohortSummaryError("expected 125 bugs in per-bug and random records")

    # Materialize full 125×5 descriptive rows (Random fractional OK).
    lineup: dict[str, list[dict[str, Any]]] = {m: [] for m in METHODS}
    for qid in sorted(by_bug.keys(), key=lambda x: (x.split("-")[0], int(x.split("-")[1]))):
        methods = by_bug[qid]
        for method in ("BM25", "Embedding", "GPT-Nano"):
            if method not in methods:
                raise CohortSummaryError(f"{qid}: missing {method}")
            lineup[method].append(dict(methods[method]))
        if "Jev" not in methods:
            raise CohortSummaryError(f"{qid}: missing Jev record")
        lineup["Jev"].append(materialize_jev_record(methods["Jev"]))
        if qid not in random_by_bug:
            raise CohortSummaryError(f"{qid}: missing Random row")
        lineup["Random"].append(random_by_bug[qid])

    for method, rows in lineup.items():
        if len(rows) != EVAL_BUGS:
            raise CohortSummaryError(f"{method}: expected 125 rows, got {len(rows)}")

    # Random median NFTR must use replicate rule from P8-03, not median of means.
    random_headline = dict(
        summarize_method_rows(
            lineup["Random"],
            method="Random",
            cost_per_bug=0.0,
            latency=None,
        )
    )
    random_headline["median_nftr"] = float(
        random_doc["aggregates"]["median_nftr"]
    )
    random_headline["median_nftr_rule"] = (
        "mean_of_cohort_medians_across_permutation_replicates"
    )

    cohort: dict[str, Any] = {"Random": random_headline}
    for method in ("BM25", "Embedding", "Jev", "GPT-Nano"):
        cost_block = cost["methods"][method]["cost"]["cohort"]
        latency = cost["methods"][method].get("latency")
        cohort[method] = summarize_method_rows(
            lineup[method],
            method=method,
            cost_per_bug=float(cost_block["mean_effective_usd_per_bug"]),
            latency=latency,
        )

    # Project slices (descriptive only).
    projects: dict[str, Any] = {}
    for project in PROJECTS:
        proj_rows = {
            method: [r for r in lineup[method] if r["project"] == project]
            for method in METHODS
        }
        for method, rows in proj_rows.items():
            if len(rows) != PROJECT_BUGS:
                raise CohortSummaryError(
                    f"{project}/{method}: expected 25 rows, got {len(rows)}"
                )
        projects[project] = {
            "denominator": PROJECT_BUGS,
            "significance": "descriptive_only_no_inference",
            "methods": {
                method: {
                    "primary_fdr_at_10pct": method_detection_fraction(
                        rows, label="10pct"
                    ),
                    "mrr": _mean([float(r["reciprocal_rank"]) for r in rows]),
                    "median_nftr": _median(
                        [float(r["normalized_first_trigger_rank"]) for r in rows]
                    ),
                }
                for method, rows in proj_rows.items()
            },
        }

    recall = candidate_recall_at_200(lineup["BM25"])
    misses = classify_jev_misses(lineup["Jev"])
    fdr10 = {m: float(cohort[m]["primary_fdr_at_10pct"]) for m in METHODS}
    success = practical_success_table(
        fdr=fdr10,
        cost_ratio=cost["jev_vs_gpt_cost_criterion"],
    )

    return {
        "schema_version": SUMMARY_SCHEMA,
        "created_at": _utcnow(),
        "experiment_commit": per_bug.get("experiment_commit"),
        "run_id": per_bug.get("run_id"),
        "inputs": inputs["paths"],
        "input_hashes": inputs["hashes"],
        "counts": {
            "evaluation_bugs": EVAL_BUGS,
            "projects": {p: PROJECT_BUGS for p in PROJECTS},
            "methods": list(METHODS),
            "jev_imputed_worst_case": sum(
                1 for r in lineup["Jev"] if r.get("imputed")
            ),
        },
        "cohort": cohort,
        "projects": projects,
        "candidate_ceiling": recall,
        "jev_miss_classification": misses,
        "practical_success": success,
        "notes": [
            "Headline FDR denominators are 125 for every method",
            "Unavailable Jev A-001 bugs imputed as non-detections with r=N",
            "Random median NFTR uses P8-03 replicate rule",
            "Project tables are descriptive only (no significance claims)",
        ],
    }


def run_cohort_summaries(
    *,
    workspace: Path | None = None,
    write_path: Path | None = None,
) -> dict[str, Any]:
    payload = build_cohort_summaries(workspace=workspace)
    out = write_path or (
        (workspace or WORKSPACE) / "results" / "phase8" / "cohort_summaries.json"
    )
    atomic_write_json(out, payload)
    payload["_write_path"] = str(out)
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=None)
    parser.add_argument("--write", type=Path, default=None)
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        payload = run_cohort_summaries(
            workspace=args.workspace, write_path=args.write
        )
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    ps = payload["practical_success"]
    print(
        f"OK recall@200={payload['candidate_ceiling']['recall']:.4f} "
        f"Jev_FDR10={payload['cohort']['Jev']['primary_fdr_at_10pct']:.4f} "
        f"practical_success={ps['practically_successful']} "
        f"jev_misses={payload['jev_miss_classification']['n_misses']} "
        f"path={payload.get('_write_path')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
