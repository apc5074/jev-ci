"""Per-bug ranking metrics for sealed evaluation inputs (P8-02).

Pure functions only — no provider calls. Random aggregation is P8-03;
cost/latency fields are filled in P8-04; ``metrics.csv`` is P8-07.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.evaluation_inputs import (
    BugInputs,
    SealedEvaluationBundle,
    load_and_verify_sealed_inputs,
)
from src.example_contract import WORKSPACE, atomic_write_json

BUDGET_FRACTIONS: tuple[float, ...] = (0.01, 0.02, 0.05, 0.10, 0.20, 0.50, 1.00)
BUDGET_LABELS: tuple[str, ...] = ("1pct", "2pct", "5pct", "10pct", "20pct", "50pct", "100pct")
NONRANDOM_METHODS: tuple[str, ...] = ("BM25", "Embedding", "Jev", "GPT-Nano")
PER_BUG_PATH = WORKSPACE / "results" / "phase8" / "per_bug_metrics.json"
PER_BUG_SCHEMA = "jev-phase8-per-bug-metrics-v1"


class MetricsError(Exception):
    """Ranking metric calculation failed."""


def budget_k(*, fraction: float, n: int) -> int:
    """Return ``max(1, ceil(fraction * N))`` for a detection budget."""
    if n < 1:
        raise MetricsError(f"N must be >= 1, got {n}")
    if not (0.0 < fraction <= 1.0) or not math.isfinite(fraction):
        raise MetricsError(f"fraction must be in (0, 1], got {fraction!r}")
    return max(1, math.ceil(fraction * n))


def ranking_ids(doc: Mapping[str, Any]) -> list[str]:
    if isinstance(doc.get("ranked_ids"), list) and doc["ranked_ids"]:
        return [str(x) for x in doc["ranked_ids"]]
    ranking = doc.get("ranking") or []
    ids = [str(e["test_class"]) for e in ranking]
    if not ids:
        raise MetricsError("ranking document has no class IDs")
    return ids


def first_trigger_rank(
    ranked_ids: Sequence[str],
    positive_classes: Sequence[str],
) -> int:
    """1-based rank of the earliest known triggering class."""
    if not ranked_ids:
        raise MetricsError("empty ranking")
    positives = set(positive_classes)
    if not positives:
        raise MetricsError("positive_classes must be nonempty")
    unknown = positives - set(ranked_ids)
    if unknown:
        raise MetricsError(f"trigger classes missing from ranking: {sorted(unknown)[:5]}")
    best: int | None = None
    for i, cls in enumerate(ranked_ids, start=1):
        if cls in positives:
            best = i if best is None else min(best, i)
    if best is None:
        raise MetricsError("no triggering class found in ranking")
    return best


def detected_at_budget(
    ranked_ids: Sequence[str],
    positive_classes: Sequence[str],
    *,
    fraction: float,
) -> bool:
    n = len(ranked_ids)
    k = budget_k(fraction=fraction, n=n)
    head = set(ranked_ids[:k])
    return any(cls in head for cls in positive_classes)


def reciprocal_rank(r: int) -> float:
    if r < 1:
        raise MetricsError(f"rank must be >= 1, got {r}")
    return 1.0 / float(r)


def normalized_first_trigger_rank(*, r: int, n: int) -> float:
    if n < 1 or r < 1 or r > n:
        raise MetricsError(f"invalid r={r} N={n}")
    return float(r) / float(n)


def apfd(*, r: int, n: int) -> float:
    """Single-fault APFD: ``1 - r/N + 1/(2N)``."""
    if n < 1 or r < 1 or r > n:
        raise MetricsError(f"invalid r={r} N={n}")
    return 1.0 - (float(r) / float(n)) + (1.0 / (2.0 * float(n)))


def candidate_trigger_in_top_k(
    *,
    candidate_ids: Sequence[str],
    positive_classes: Sequence[str],
) -> bool:
    head = set(candidate_ids)
    return any(cls in head for cls in positive_classes)


@dataclass(frozen=True)
class PerBugMethodMetrics:
    """One evaluation bug × nonrandom method metric record."""

    project: str
    bug_id: str
    qualified_id: str
    split: str
    method: str
    available: bool
    accepted_jev_gap: bool
    num_test_classes: int | None
    num_trigger_classes: int | None
    first_trigger_rank: int | None
    normalized_first_trigger_rank: float | None
    reciprocal_rank: float | None
    apfd: float | None
    detected_at_1pct: bool | None
    detected_at_2pct: bool | None
    detected_at_5pct: bool | None
    detected_at_10pct: bool | None
    detected_at_20pct: bool | None
    detected_at_50pct: bool | None
    detected_at_100pct: bool | None
    candidate_trigger_in_top200: bool | None
    K: int | None
    shortlist_sha256: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_per_bug_metrics(
    *,
    ranked_ids: Sequence[str],
    positive_classes: Sequence[str],
    candidate_ids: Sequence[str],
    project: str,
    bug_id: str,
    qualified_id: str,
    method: str,
    shortlist_sha256: str | None = None,
    accepted_jev_gap: bool = False,
) -> PerBugMethodMetrics:
    n = len(ranked_ids)
    r = first_trigger_rank(ranked_ids, positive_classes)
    detections = {
        label: detected_at_budget(ranked_ids, positive_classes, fraction=frac)
        for frac, label in zip(BUDGET_FRACTIONS, BUDGET_LABELS, strict=True)
    }
    return PerBugMethodMetrics(
        project=project,
        bug_id=bug_id,
        qualified_id=qualified_id,
        split="evaluation",
        method=method,
        available=True,
        accepted_jev_gap=accepted_jev_gap,
        num_test_classes=n,
        num_trigger_classes=len(set(positive_classes)),
        first_trigger_rank=r,
        normalized_first_trigger_rank=normalized_first_trigger_rank(r=r, n=n),
        reciprocal_rank=reciprocal_rank(r),
        apfd=apfd(r=r, n=n),
        detected_at_1pct=detections["1pct"],
        detected_at_2pct=detections["2pct"],
        detected_at_5pct=detections["5pct"],
        detected_at_10pct=detections["10pct"],
        detected_at_20pct=detections["20pct"],
        detected_at_50pct=detections["50pct"],
        detected_at_100pct=detections["100pct"],
        candidate_trigger_in_top200=candidate_trigger_in_top_k(
            candidate_ids=candidate_ids,
            positive_classes=positive_classes,
        ),
        K=len(candidate_ids),
        shortlist_sha256=shortlist_sha256,
    )


def unavailable_jev_record(bug: BugInputs) -> PerBugMethodMetrics:
    """Jev row for an accepted A-001 gap (no ranking; no invented scores)."""
    ex = bug.example
    return PerBugMethodMetrics(
        project=ex.project,
        bug_id=ex.bug_id,
        qualified_id=ex.qualified,
        split="evaluation",
        method="Jev",
        available=False,
        accepted_jev_gap=True,
        num_test_classes=bug.N,
        num_trigger_classes=len(bug.positive_classes),
        first_trigger_rank=None,
        normalized_first_trigger_rank=None,
        reciprocal_rank=None,
        apfd=None,
        detected_at_1pct=None,
        detected_at_2pct=None,
        detected_at_5pct=None,
        detected_at_10pct=None,
        detected_at_20pct=None,
        detected_at_50pct=None,
        detected_at_100pct=None,
        candidate_trigger_in_top200=candidate_trigger_in_top_k(
            candidate_ids=list(bug.candidates["candidate_ids"]),
            positive_classes=bug.positive_classes,
        ),
        K=bug.K,
        shortlist_sha256=str(bug.candidates.get("shortlist_sha256") or "") or None,
    )


def _ranking_for_method(bug: BugInputs, method: str) -> Mapping[str, Any] | None:
    if method == "BM25":
        return bug.bm25_ranking
    if method == "Embedding":
        return bug.embedding_ranking
    if method == "GPT-Nano":
        return bug.gpt_ranking
    if method == "Jev":
        return bug.jev_ranking
    raise MetricsError(f"unknown nonrandom method {method!r}")


def records_for_bug(bug: BugInputs) -> list[PerBugMethodMetrics]:
    out: list[PerBugMethodMetrics] = []
    candidate_ids = list(bug.candidates["candidate_ids"])
    shortlist = str(bug.candidates.get("shortlist_sha256") or "") or None
    for method in NONRANDOM_METHODS:
        doc = _ranking_for_method(bug, method)
        if doc is None:
            if method != "Jev" or not bug.accepted_jev_gap:
                raise MetricsError(
                    f"{bug.example.qualified}: missing {method} ranking"
                )
            out.append(unavailable_jev_record(bug))
            continue
        out.append(
            compute_per_bug_metrics(
                ranked_ids=ranking_ids(doc),
                positive_classes=bug.positive_classes,
                candidate_ids=candidate_ids,
                project=bug.example.project,
                bug_id=bug.example.bug_id,
                qualified_id=bug.example.qualified,
                method=method,
                shortlist_sha256=shortlist,
                accepted_jev_gap=False,
            )
        )
    return out


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


def aggregate_method_records(
    records: Sequence[PerBugMethodMetrics],
    *,
    method: str,
) -> dict[str, Any]:
    """Cohort summary over available rows for one method (denominator = available)."""
    rows = [r for r in records if r.method == method and r.available]
    gaps = [r for r in records if r.method == method and not r.available]
    if not rows:
        raise MetricsError(f"no available records for {method}")
    rr = [float(r.reciprocal_rank) for r in rows if r.reciprocal_rank is not None]
    apfds = [float(r.apfd) for r in rows if r.apfd is not None]
    nftrs = [
        float(r.normalized_first_trigger_rank)
        for r in rows
        if r.normalized_first_trigger_rank is not None
    ]
    fdr: dict[str, float] = {}
    for label in BUDGET_LABELS:
        field = f"detected_at_{label}"
        hits = sum(1 for r in rows if getattr(r, field) is True)
        fdr[f"fdr_at_{label}"] = hits / len(rows)
    return {
        "method": method,
        "n_available": len(rows),
        "n_unavailable": len(gaps),
        "denominator": len(rows),
        "mrr": _mean(rr),
        "mean_apfd": _mean(apfds),
        "mean_nftr": _mean(nftrs),
        "median_nftr": _median(nftrs),
        **fdr,
        "primary_fdr_at_10pct": fdr["fdr_at_10pct"],
    }


def compute_all_nonrandom_metrics(
    bundle: SealedEvaluationBundle,
) -> dict[str, Any]:
    records: list[PerBugMethodMetrics] = []
    for qid in sorted(bundle.bugs.keys(), key=lambda x: (x.split("-")[0], int(x.split("-")[1]))):
        records.extend(records_for_bug(bundle.bugs[qid]))

    expected = 125 * len(NONRANDOM_METHODS)
    if len(records) != expected:
        raise MetricsError(f"expected {expected} records, got {len(records)}")

    by_method = {
        method: aggregate_method_records(records, method=method)
        for method in NONRANDOM_METHODS
    }
    unavailable_jev = sum(
        1 for r in records if r.method == "Jev" and not r.available
    )
    return {
        "schema_version": PER_BUG_SCHEMA,
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "experiment_commit": bundle.experiment_commit,
        "run_id": bundle.run_id,
        "freeze_tag": bundle.freeze_tag,
        "predictions_sha256": bundle.predictions_sha256,
        "counts": {
            "evaluation_bugs": len(bundle.bugs),
            "records": len(records),
            "methods": list(NONRANDOM_METHODS),
            "unavailable_jev": unavailable_jev,
        },
        "aggregates": by_method,
        "records": [r.to_dict() for r in records],
        "notes": [
            "FDR@10% is the primary outcome (overall.md §24)",
            "Aggregates use available rows only (Jev denominator excludes 12 A-001 gaps)",
            "Cost/latency fields deferred to P8-04; Random deferred to P8-03",
            "Full metrics.csv (625 rows) is P8-07",
        ],
    }


def run_per_bug_metrics(
    *,
    workspace: Path | None = None,
    write_path: Path | None = None,
) -> dict[str, Any]:
    bundle = load_and_verify_sealed_inputs(
        workspace=workspace,
        clear_credentials=True,
    )
    payload = compute_all_nonrandom_metrics(bundle)
    out = write_path or (
        (workspace or WORKSPACE) / "results" / "phase8" / "per_bug_metrics.json"
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
        payload = run_per_bug_metrics(workspace=args.workspace, write_path=args.write)
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    ag = payload["aggregates"]
    print(
        f"OK records={payload['counts']['records']} "
        f"BM25_FDR10={ag['BM25']['primary_fdr_at_10pct']:.4f} "
        f"Emb_FDR10={ag['Embedding']['primary_fdr_at_10pct']:.4f} "
        f"Jev_FDR10={ag['Jev']['primary_fdr_at_10pct']:.4f} "
        f"GPT_FDR10={ag['GPT-Nano']['primary_fdr_at_10pct']:.4f} "
        f"path={payload.get('_write_path')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
