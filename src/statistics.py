"""Paired McNemar and bootstrap comparisons (P8-06).

Primary contrast: Jev vs BM25 on FDR@10% (exact McNemar + bootstrap CIs).
Secondary: Jev vs Embedding, Jev vs GPT-Nano (bootstrap only for the four
deltas; McNemar still reported for detection tables).

Bootstrap seed: Phase 6 ``selection_seed`` ``20260922`` (no separate bootstrap
seed was named in the freeze; this is the locked experiment seed).
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.cohort_summaries import (
    index_nonrandom_records,
    materialize_jev_record,
)
from src.example_contract import WORKSPACE, atomic_write_json, read_json, sha256_file

STATS_PATH = WORKSPACE / "results" / "statistics.json"
STATS_SCHEMA = "jev-phase8-statistics-v1"
BOOTSTRAP_SAMPLES = 10_000
BOOTSTRAP_SEED = 20260922  # Phase 6 selection_seed / locked experiment seed
EVAL_BUGS = 125
PRIMARY = ("Jev", "BM25")
SECONDARY = (("Jev", "Embedding"), ("Jev", "GPT-Nano"))


class StatisticsError(Exception):
    """Paired statistical analysis failed."""


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return float(ordered[mid])
    return float((ordered[mid - 1] + ordered[mid]) / 2.0)


def _mean(values: Sequence[float]) -> float:
    return float(sum(values) / len(values))


def _percentile_sorted(ordered: Sequence[float], p: float) -> float:
    """Linear-interpolated percentile on a pre-sorted sequence; p in [0,100]."""
    if not ordered:
        raise StatisticsError("percentile of empty sequence")
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (p / 100.0) * (len(ordered) - 1)
    lo = int(math.floor(rank))
    hi = int(math.ceil(rank))
    if lo == hi:
        return float(ordered[lo])
    w = rank - lo
    return float(ordered[lo] * (1.0 - w) + ordered[hi] * w)


def mcnemar_exact_two_sided(*, b: int, c: int) -> float:
    """Exact two-sided McNemar p-value on discordant counts ``b``, ``c``.

    Uses ``p = min(1, 2 * P(X >= max(b,c)))`` for ``X ~ Binomial(n=b+c, 0.5)``.
    When ``n == 0``, returns ``1.0`` by definition.
    """
    if b < 0 or c < 0:
        raise StatisticsError(f"discordant counts must be >= 0, got b={b} c={c}")
    n = b + c
    if n == 0:
        return 1.0
    k = max(b, c)
    # sum_{i=k}^{n} C(n,i) / 2^n
    total = 0
    for i in range(k, n + 1):
        total += math.comb(n, i)
    p = 2.0 * (total / float(2**n))
    return float(min(1.0, p))


def paired_detection_table(
    jev_detected: Sequence[bool],
    other_detected: Sequence[bool],
) -> dict[str, Any]:
    if len(jev_detected) != len(other_detected):
        raise StatisticsError("paired detection vectors length mismatch")
    both = jev_only = other_only = neither = 0
    for j, o in zip(jev_detected, other_detected, strict=True):
        if j and o:
            both += 1
        elif j and not o:
            jev_only += 1
        elif (not j) and o:
            other_only += 1
        else:
            neither += 1
    b = jev_only  # Jev detected, other missed
    c = other_only  # other detected, Jev missed
    return {
        "both": both,
        "jev_only": jev_only,
        "other_only": other_only,
        "neither": neither,
        "discordant_b_jev_only": b,
        "discordant_c_other_only": c,
        "n_discordant": b + c,
        "mcnemar_exact_two_sided_p": mcnemar_exact_two_sided(b=b, c=c),
        "n": len(jev_detected),
    }


def _as_bool_detection(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        # Should not appear for nonrandom; treat >0.5 as detected if fractional
        return bool(value)
    raise StatisticsError(f"bad detection value {value!r}")


def load_method_metric_matrix(
    *,
    workspace: Path,
) -> tuple[list[str], dict[str, dict[str, list[float]]]]:
    """Return ordered bug IDs and per-method metric vectors (length 125)."""
    per_bug = read_json(workspace / "results" / "phase8" / "per_bug_metrics.json")
    by_bug = index_nonrandom_records(per_bug["records"])
    if len(by_bug) != EVAL_BUGS:
        raise StatisticsError(f"expected {EVAL_BUGS} bugs, got {len(by_bug)}")

    ordered = sorted(
        by_bug.keys(),
        key=lambda x: (x.split("-")[0], int(x.split("-")[1])),
    )
    methods = ("BM25", "Embedding", "Jev", "GPT-Nano")
    matrix: dict[str, dict[str, list[float]]] = {
        m: {
            "detected_at_10pct": [],
            "reciprocal_rank": [],
            "apfd": [],
            "normalized_first_trigger_rank": [],
        }
        for m in methods
    }

    for qid in ordered:
        recs = by_bug[qid]
        for method in methods:
            if method not in recs:
                raise StatisticsError(f"{qid}: missing {method}")
            row = (
                materialize_jev_record(recs[method])
                if method == "Jev"
                else dict(recs[method])
            )
            matrix[method]["detected_at_10pct"].append(
                1.0 if _as_bool_detection(row["detected_at_10pct"]) else 0.0
            )
            matrix[method]["reciprocal_rank"].append(float(row["reciprocal_rank"]))
            matrix[method]["apfd"].append(float(row["apfd"]))
            matrix[method]["normalized_first_trigger_rank"].append(
                float(row["normalized_first_trigger_rank"])
            )

    return ordered, matrix


def point_deltas(
    matrix: Mapping[str, Mapping[str, Sequence[float]]],
    *,
    method_a: str,
    method_b: str,
) -> dict[str, float]:
    """Jev-minus-comparator point estimates on the full cohort."""
    a = matrix[method_a]
    b = matrix[method_b]
    return {
        "delta_fdr_at_10pct": _mean(a["detected_at_10pct"]) - _mean(b["detected_at_10pct"]),
        "delta_mrr": _mean(a["reciprocal_rank"]) - _mean(b["reciprocal_rank"]),
        "delta_apfd": _mean(a["apfd"]) - _mean(b["apfd"]),
        "delta_median_nftr": _median(a["normalized_first_trigger_rank"])
        - _median(b["normalized_first_trigger_rank"]),
    }


def bootstrap_deltas(
    matrix: Mapping[str, Mapping[str, Sequence[float]]],
    *,
    method_a: str,
    method_b: str,
    indices_samples: Sequence[Sequence[int]],
) -> dict[str, Any]:
    """Compute percentile CIs from pre-drawn paired index samples."""
    a = matrix[method_a]
    b = matrix[method_b]
    keys = (
        "delta_fdr_at_10pct",
        "delta_mrr",
        "delta_apfd",
        "delta_median_nftr",
    )
    series: dict[str, list[float]] = {k: [] for k in keys}

    for idxs in indices_samples:
        fdr_a = _mean([a["detected_at_10pct"][i] for i in idxs])
        fdr_b = _mean([b["detected_at_10pct"][i] for i in idxs])
        mrr_a = _mean([a["reciprocal_rank"][i] for i in idxs])
        mrr_b = _mean([b["reciprocal_rank"][i] for i in idxs])
        apfd_a = _mean([a["apfd"][i] for i in idxs])
        apfd_b = _mean([b["apfd"][i] for i in idxs])
        nftr_a = _median([a["normalized_first_trigger_rank"][i] for i in idxs])
        nftr_b = _median([b["normalized_first_trigger_rank"][i] for i in idxs])
        series["delta_fdr_at_10pct"].append(fdr_a - fdr_b)
        series["delta_mrr"].append(mrr_a - mrr_b)
        series["delta_apfd"].append(apfd_a - apfd_b)
        series["delta_median_nftr"].append(nftr_a - nftr_b)

    out: dict[str, Any] = {}
    for key, vals in series.items():
        ordered = sorted(vals)
        out[key] = {
            "point": None,  # filled by caller
            "mean_of_bootstrap": _mean(vals),
            "ci95_low": _percentile_sorted(ordered, 2.5),
            "ci95_high": _percentile_sorted(ordered, 97.5),
        }
    return out


def draw_bootstrap_index_samples(
    *,
    n_bugs: int,
    n_samples: int,
    seed: int,
) -> list[list[int]]:
    rng = random.Random(seed)
    samples: list[list[int]] = []
    for _ in range(n_samples):
        samples.append([rng.randrange(n_bugs) for _ in range(n_bugs)])
    return samples


def contrast_block(
    *,
    matrix: Mapping[str, Mapping[str, Sequence[float]]],
    method_a: str,
    method_b: str,
    indices_samples: Sequence[Sequence[int]],
    role: str,
) -> dict[str, Any]:
    jev_det = [bool(x) for x in matrix[method_a]["detected_at_10pct"]]
    other_det = [bool(x) for x in matrix[method_b]["detected_at_10pct"]]
    table = paired_detection_table(jev_det, other_det)
    points = point_deltas(matrix, method_a=method_a, method_b=method_b)
    boot = bootstrap_deltas(
        matrix,
        method_a=method_a,
        method_b=method_b,
        indices_samples=indices_samples,
    )
    for key, point in points.items():
        boot[key]["point"] = point
    return {
        "role": role,
        "contrast": [method_a, method_b],
        "delta_definition": f"{method_a}_minus_{method_b}",
        "paired_detection_fdr_at_10pct": table,
        "bootstrap": boot,
    }


def compute_statistics(
    *,
    workspace: Path | None = None,
    n_bootstrap: int = BOOTSTRAP_SAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    root = workspace or WORKSPACE
    ordered_ids, matrix = load_method_metric_matrix(workspace=root)
    samples = draw_bootstrap_index_samples(
        n_bugs=len(ordered_ids),
        n_samples=n_bootstrap,
        seed=seed,
    )

    primary = contrast_block(
        matrix=matrix,
        method_a=PRIMARY[0],
        method_b=PRIMARY[1],
        indices_samples=samples,
        role="primary",
    )
    secondary = [
        contrast_block(
            matrix=matrix,
            method_a=a,
            method_b=b,
            indices_samples=samples,
            role="secondary",
        )
        for a, b in SECONDARY
    ]

    per_bug_path = root / "results" / "phase8" / "per_bug_metrics.json"
    cohort_path = root / "results" / "phase8" / "cohort_summaries.json"
    seal_path = root / "results" / "phase7" / "raw_evaluation_seal.json"

    return {
        "schema_version": STATS_SCHEMA,
        "created_at": _utcnow(),
        "experiment_commit": read_json(seal_path).get("experiment_commit"),
        "run_id": read_json(seal_path).get("run_id"),
        "freeze_tag": read_json(seal_path).get("freeze_tag"),
        "configuration": {
            "bootstrap_samples": n_bootstrap,
            "bootstrap_seed": seed,
            "bootstrap_seed_source": (
                "Phase 6 selection_seed / experiment.yaml "
                "(no separate bootstrap seed was named at freeze)"
            ),
            "bootstrap_interval": "percentile_95_linear_interpolation",
            "ci_percentiles": [2.5, 97.5],
            "pairing": "by_bug",
            "primary_contrast": list(PRIMARY),
            "secondary_contrasts": [list(x) for x in SECONDARY],
            "mcnemar": "exact_two_sided_binomial",
            "n_evaluation_bugs": EVAL_BUGS,
            "bug_id_order": ordered_ids,
        },
        "input_hashes": {
            "per_bug_metrics": sha256_file(per_bug_path),
            "cohort_summaries": sha256_file(cohort_path)
            if cohort_path.is_file()
            else None,
            "raw_evaluation_seal": sha256_file(seal_path),
        },
        "primary": primary,
        "secondary": secondary,
        "notes": [
            "Deltas are Jev minus comparator (positive favors Jev for FDR/MRR/APFD; "
            "negative median-NFTR delta favors Jev)",
            "Secondary contrasts are not additional primary tests",
            "Jev A-001 gaps imputed as non-detections with r=N (same as P8-05)",
            "All contrasts share identical bootstrap index samples",
        ],
    }


def run_statistics(
    *,
    workspace: Path | None = None,
    write_path: Path | None = None,
    n_bootstrap: int = BOOTSTRAP_SAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    payload = compute_statistics(
        workspace=workspace, n_bootstrap=n_bootstrap, seed=seed
    )
    out = write_path or ((workspace or WORKSPACE) / "results" / "statistics.json")
    atomic_write_json(out, payload)
    payload["_write_path"] = str(out)
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=None)
    parser.add_argument("--write", type=Path, default=None)
    parser.add_argument("--bootstrap-samples", type=int, default=BOOTSTRAP_SAMPLES)
    parser.add_argument("--seed", type=int, default=BOOTSTRAP_SEED)
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        payload = run_statistics(
            workspace=args.workspace,
            write_path=args.write,
            n_bootstrap=args.bootstrap_samples,
            seed=args.seed,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    prim = payload["primary"]
    table = prim["paired_detection_fdr_at_10pct"]
    d_fdr = prim["bootstrap"]["delta_fdr_at_10pct"]
    print(
        f"OK primary Jev-BM25 McNemar_p={table['mcnemar_exact_two_sided_p']:.6g} "
        f"both={table['both']} jev_only={table['jev_only']} "
        f"bm25_only={table['other_only']} neither={table['neither']} "
        f"dFDR10={d_fdr['point']:.4f} "
        f"CI=[{d_fdr['ci95_low']:.4f},{d_fdr['ci95_high']:.4f}] "
        f"path={payload.get('_write_path')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
