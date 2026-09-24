"""Random baseline aggregation over 1,000 sealed permutations (P8-03).

Uses the same per-bug metric primitives as P8-02. Each **headline-cohort** bug
gets one ``method=Random`` row whose numeric fields are **means over 1,000
permutations** (so ranks and detection indicators may be fractional).

Headline cohort: 113 bugs (A-001 Jsoup Jev WAF gaps excluded for all methods).

Cohort rules
------------
* Linear headlines (FDR, MRR, mean APFD, mean NFTR): mean of the 113 per-bug
  Random rows (each row already averaged over permutations).
* Median NFTR: for replicate ``i`` in ``0..999``, take NFTR under permutation
  ``i`` for every headline bug, compute the cohort median, then average those
  1,000 medians. Do **not** take the median of per-bug means.
* First-trigger CDF: for each grid point ``y``, average the 1,000 replicate
  empirical CDFs ``F_i(y) = (#bugs with NFTR_i <= y) / 113``.
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

from src.analysis_cohort import (
    COHORT_POLICY_NOTE,
    HEADLINE_EVAL_BUGS,
    cohort_metadata,
    filter_headline_ids,
    require_headline_size,
)
from src.evaluation_inputs import (
    BugInputs,
    SealedEvaluationBundle,
    load_and_verify_sealed_inputs,
)
from src.example_contract import WORKSPACE, atomic_write_json
from src.metrics import (
    BUDGET_FRACTIONS,
    BUDGET_LABELS,
    MetricsError,
    apfd,
    candidate_trigger_in_top_k,
    detected_at_budget,
    first_trigger_rank,
    normalized_first_trigger_rank,
    reciprocal_rank,
)
from src.random_baseline import (
    NUM_PERMUTATIONS,
    regenerate_from_contract,
)


def _mean(values: Sequence[float]) -> float:
    if not values:
        raise MetricsError("mean of empty sequence")
    return float(sum(values) / len(values))


def _median(values: Sequence[float]) -> float:
    if not values:
        raise MetricsError("median of empty sequence")
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return float(ordered[mid])
    return float(ordered[mid - 1] + ordered[mid]) / 2.0

RANDOM_METRICS_PATH = WORKSPACE / "results" / "phase8" / "random_metrics.json"
RANDOM_METRICS_SCHEMA = "jev-phase8-random-metrics-v1"
CDF_GRID = tuple(round(i / 100.0, 2) for i in range(0, 101))


def permutation_metric_values(
    ranked_ids: Sequence[str],
    positive_classes: Sequence[str],
) -> dict[str, float]:
    """Raw metrics for one ranking permutation (numeric + 0/1 detections)."""
    n = len(ranked_ids)
    r = first_trigger_rank(ranked_ids, positive_classes)
    out: dict[str, float] = {
        "first_trigger_rank": float(r),
        "normalized_first_trigger_rank": normalized_first_trigger_rank(r=r, n=n),
        "reciprocal_rank": reciprocal_rank(r),
        "apfd": apfd(r=r, n=n),
    }
    for frac, label in zip(BUDGET_FRACTIONS, BUDGET_LABELS, strict=True):
        out[f"detected_at_{label}"] = (
            1.0 if detected_at_budget(ranked_ids, positive_classes, fraction=frac) else 0.0
        )
    return out


def mean_metrics_over_permutations(
    permutations: Sequence[Sequence[str]],
    positive_classes: Sequence[str],
) -> dict[str, float]:
    if not permutations:
        raise MetricsError("no permutations to average")
    acc: dict[str, float] | None = None
    for perm in permutations:
        vals = permutation_metric_values(perm, positive_classes)
        if acc is None:
            acc = {k: float(v) for k, v in vals.items()}
        else:
            for k, v in vals.items():
                acc[k] += float(v)
    assert acc is not None
    n = float(len(permutations))
    return {k: v / n for k, v in acc.items()}


def random_row_for_bug(
    bug: BugInputs,
    *,
    permutations: Sequence[Sequence[str]] | None = None,
) -> dict[str, Any]:
    """One Random metrics row: means over permutations (fractional fields OK)."""
    contract = bug.random_contract
    if int(contract.get("num_permutations") or 0) != NUM_PERMUTATIONS:
        raise MetricsError(
            f"{bug.example.qualified}: expected {NUM_PERMUTATIONS} permutations"
        )
    perms = (
        list(permutations)
        if permutations is not None
        else regenerate_from_contract(contract, test_classes=list(bug.inventory_classes))
    )
    if len(perms) != NUM_PERMUTATIONS:
        raise MetricsError(
            f"{bug.example.qualified}: regenerated {len(perms)} != {NUM_PERMUTATIONS}"
        )

    acc: dict[str, float] | None = None
    nftr_by_perm: list[float] = []
    for perm in perms:
        vals = permutation_metric_values(perm, bug.positive_classes)
        nftr_by_perm.append(vals["normalized_first_trigger_rank"])
        if acc is None:
            acc = {k: float(v) for k, v in vals.items()}
        else:
            for k, v in vals.items():
                acc[k] += float(v)
    assert acc is not None
    n = float(len(perms))
    means = {k: v / n for k, v in acc.items()}

    candidate_ids = list(bug.candidates["candidate_ids"])
    return {
        "project": bug.example.project,
        "bug_id": bug.example.bug_id,
        "qualified_id": bug.example.qualified,
        "split": "evaluation",
        "method": "Random",
        "available": True,
        "num_permutations": NUM_PERMUTATIONS,
        "seed": int(contract["seed"]),
        "bug_index": int(contract["bug_index"]),
        "permutations_sha256": contract.get("permutations_sha256"),
        "num_test_classes": bug.N,
        "num_trigger_classes": len(bug.positive_classes),
        "K": bug.K,
        "candidate_trigger_in_top200": candidate_trigger_in_top_k(
            candidate_ids=candidate_ids,
            positive_classes=bug.positive_classes,
        ),
        "schema_note": (
            "Numeric fields are means over 1000 permutations; "
            "first_trigger_rank and detected_at_* may be fractional"
        ),
        **means,
        "_nftr_by_perm": nftr_by_perm,
    }


def _linear_cohort_from_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    if len(rows) != HEADLINE_EVAL_BUGS:
        raise MetricsError(
            f"expected {HEADLINE_EVAL_BUGS} Random rows, got {len(rows)}"
        )
    out: dict[str, float] = {
        "mrr": _mean([float(r["reciprocal_rank"]) for r in rows]),
        "mean_apfd": _mean([float(r["apfd"]) for r in rows]),
        "mean_nftr": _mean([float(r["normalized_first_trigger_rank"]) for r in rows]),
        # Documented anti-pattern placeholder (not used for headlines):
        "median_of_per_bug_mean_nftr": _median(
            [float(r["normalized_first_trigger_rank"]) for r in rows]
        ),
    }
    for label in BUDGET_LABELS:
        key = f"detected_at_{label}"
        out[f"fdr_at_{label}"] = _mean([float(r[key]) for r in rows])
    out["primary_fdr_at_10pct"] = out["fdr_at_10pct"]
    return out


def cohort_replicate_median_nftr(
    nftr_by_bug_by_perm: Sequence[Sequence[float]],
) -> dict[str, Any]:
    """Mean of 1,000 cohort medians (replicate i uses permutation i for all bugs)."""
    if not nftr_by_bug_by_perm:
        raise MetricsError("empty nftr matrix")
    n_bugs = len(nftr_by_bug_by_perm)
    n_perm = len(nftr_by_bug_by_perm[0])
    if n_perm != NUM_PERMUTATIONS:
        raise MetricsError(f"expected {NUM_PERMUTATIONS} perms, got {n_perm}")
    if any(len(row) != n_perm for row in nftr_by_bug_by_perm):
        raise MetricsError("ragged nftr_by_bug_by_perm")

    medians: list[float] = []
    for i in range(n_perm):
        replicate = [nftr_by_bug_by_perm[b][i] for b in range(n_bugs)]
        medians.append(_median(replicate))
    return {
        "median_nftr": _mean(medians),
        "n_replicates": n_perm,
        "n_bugs": n_bugs,
        "rule": "mean_of_cohort_medians_across_permutation_replicates",
    }


def cohort_replicate_cdf(
    nftr_by_bug_by_perm: Sequence[Sequence[float]],
    *,
    grid: Sequence[float] = CDF_GRID,
) -> list[dict[str, float]]:
    """Average empirical CDFs over permutation replicates."""
    n_bugs = len(nftr_by_bug_by_perm)
    n_perm = len(nftr_by_bug_by_perm[0])
    points: list[dict[str, float]] = []
    for y in grid:
        total = 0.0
        for i in range(n_perm):
            hits = sum(
                1 for b in range(n_bugs) if nftr_by_bug_by_perm[b][i] <= y + 1e-15
            )
            total += hits / float(n_bugs)
        points.append({"nftr": float(y), "fraction_bugs": total / float(n_perm)})
    return points


def compute_random_metrics(
    bundle: SealedEvaluationBundle,
) -> dict[str, Any]:
    ordered_ids = filter_headline_ids(bundle.bugs.keys())
    require_headline_size(ordered_ids, context="random_metrics")
    rows: list[dict[str, Any]] = []
    nftr_matrix: list[list[float]] = []
    for qid in ordered_ids:
        row = random_row_for_bug(bundle.bugs[qid])
        nftr_matrix.append(list(row.pop("_nftr_by_perm")))
        rows.append(row)

    linear = _linear_cohort_from_rows(rows)
    median_block = cohort_replicate_median_nftr(nftr_matrix)
    cdf = cohort_replicate_cdf(nftr_matrix)

    return {
        "schema_version": RANDOM_METRICS_SCHEMA,
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "experiment_commit": bundle.experiment_commit,
        "run_id": bundle.run_id,
        "freeze_tag": bundle.freeze_tag,
        "num_permutations": NUM_PERMUTATIONS,
        "analysis_cohort": cohort_metadata(),
        "counts": {
            "evaluation_bugs": len(rows),
            "random_rows": len(rows),
            "full_evaluation_bugs": len(bundle.bugs),
        },
        "semantics": {
            "per_bug_row": (
                "Each Random row stores the mean of each metric over 1000 "
                "permutations for that bug; first_trigger_rank and detected_at_* "
                "may be fractional."
            ),
            "linear_cohort": (
                f"FDR/MRR/mean APFD/mean NFTR = arithmetic mean of the "
                f"{HEADLINE_EVAL_BUGS} per-bug Random rows."
            ),
            "median_nftr": (
                "For replicate i, use permutation i for every headline bug; take "
                "the cohort median NFTR; report the mean of those 1000 medians."
            ),
            "cdf": (
                "Average of 1000 replicate empirical CDFs on a 0.00..1.00 grid."
            ),
            "do_not": (
                "Do not take median of per-bug mean NFTRs for the headline "
                "median NFTR; do not pick a single lucky permutation."
            ),
        },
        "aggregates": {
            "method": "Random",
            "n_available": len(rows),
            "denominator": len(rows),
            **linear,
            "median_nftr": median_block["median_nftr"],
            "median_nftr_detail": median_block,
        },
        "cdf": cdf,
        "records": rows,
        "notes": [
            COHORT_POLICY_NOTE,
            "candidate_trigger_in_top200 uses the sealed BM25 shortlist (shared)",
            "Permutations regenerated from sealed Random contracts + inventory",
        ],
    }


def run_random_metrics(
    *,
    workspace: Path | None = None,
    write_path: Path | None = None,
) -> dict[str, Any]:
    bundle = load_and_verify_sealed_inputs(
        workspace=workspace,
        clear_credentials=True,
    )
    payload = compute_random_metrics(bundle)
    out = write_path or (
        (workspace or WORKSPACE) / "results" / "phase8" / "random_metrics.json"
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
        payload = run_random_metrics(workspace=args.workspace, write_path=args.write)
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    ag = payload["aggregates"]
    print(
        f"OK random_rows={payload['counts']['random_rows']} "
        f"FDR10={ag['primary_fdr_at_10pct']:.4f} "
        f"MRR={ag['mrr']:.4f} "
        f"median_NFTR={ag['median_nftr']:.4f} "
        f"path={payload.get('_write_path')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
