"""Measured cost and latency from sealed usage + predictions (P8-04).

Offline only. Costs come from the frozen usage ledger (and dated pricing
snapshot notes). Client-observed request latency comes from cache-backed
``predictions.jsonl`` fields. Shortlist wall-clock at concurrency 16 was not
instrumented during Phase 7 scoring; we reconstruct a deterministic estimate
from per-request latencies (batch max over waves of size 16).
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

from src.evaluation_inputs import load_and_verify_sealed_inputs
from src.example_contract import WORKSPACE, atomic_write_json, read_json, sha256_file
from src.semantic_scheduler import MAX_CONCURRENCY

COST_PATH = WORKSPACE / "results" / "phase8" / "cost_latency.json"
COST_SCHEMA = "jev-phase8-cost-latency-v1"
EVAL_BUGS = 125
JEV_GPT_COST_RATIO_THRESHOLD = 0.30
METHOD_KIND = {
    "Embedding": "embedding",
    "Jev": "jev",
    "GPT-Nano": "gpt",
}


class CostMetricsError(Exception):
    """Cost/latency reconciliation failed."""


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def percentile(values: Sequence[float], p: float) -> float:
    """Linear-interpolated percentile; ``p`` in ``[0, 100]``."""
    if not values:
        raise CostMetricsError("percentile of empty population")
    if not (0.0 <= p <= 100.0):
        raise CostMetricsError(f"percentile p out of range: {p}")
    ordered = sorted(float(v) for v in values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (p / 100.0) * (len(ordered) - 1)
    lo = int(math.floor(rank))
    hi = int(math.ceil(rank))
    if lo == hi:
        return ordered[lo]
    weight = rank - lo
    return ordered[lo] * (1.0 - weight) + ordered[hi] * weight


def mean(values: Sequence[float]) -> float:
    if not values:
        raise CostMetricsError("mean of empty population")
    return float(sum(values) / len(values))


def estimate_shortlist_wall_ms(
    latencies_ms: Sequence[float],
    *,
    concurrency: int = MAX_CONCURRENCY,
) -> float:
    """Reconstruct shortlist wall time: sum of max(latency) over waves of size C.

    Assumes up to ``concurrency`` in-flight requests; waves are successive
    chunks of the latency list in sealed shortlist order.
    """
    if concurrency < 1:
        raise CostMetricsError(f"concurrency must be >= 1, got {concurrency}")
    if not latencies_ms:
        return 0.0
    total = 0.0
    vals = [float(x) for x in latencies_ms]
    for i in range(0, len(vals), concurrency):
        total += max(vals[i : i + concurrency])
    return total


def load_ledger_by_cache_key(
    path: Path,
) -> dict[str, dict[str, Any]]:
    """First ledger row per cache_key (append-only ledger; first write wins)."""
    out: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            key = rec.get("cache_key")
            if isinstance(key, str) and key and key not in out:
                out[key] = rec
    return out


def sum_evaluation_ledger(path: Path) -> dict[str, dict[str, float | int]]:
    """Independent sum of evaluation-split ledger rows by kind."""
    by_kind: dict[str, dict[str, float | int]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            meta = rec.get("metadata") or {}
            if meta.get("split") != "evaluation":
                continue
            kind = str(rec.get("kind") or "unknown")
            bucket = by_kind.setdefault(
                kind,
                {
                    "rows": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cached_input_tokens": 0,
                    "list_price_inference_usd": 0.0,
                    "platform_fee_usd": 0.0,
                    "effective_prepaid_credits_usd": 0.0,
                    "provider_reported_cost_usd": 0.0,
                    "actual_cash_usd": 0.0,
                    "actual_cash_rows": 0,
                },
            )
            bucket["rows"] = int(bucket["rows"]) + 1
            bucket["input_tokens"] = int(bucket["input_tokens"]) + int(
                rec.get("input_tokens") or 0
            )
            bucket["output_tokens"] = int(bucket["output_tokens"]) + int(
                rec.get("output_tokens") or 0
            )
            cached = rec.get("cached_input_tokens")
            if isinstance(cached, int):
                bucket["cached_input_tokens"] = int(bucket["cached_input_tokens"]) + cached
            for field in (
                "list_price_inference_usd",
                "platform_fee_usd",
                "effective_prepaid_credits_usd",
                "provider_reported_cost_usd",
            ):
                val = rec.get(field)
                if isinstance(val, (int, float)) and math.isfinite(float(val)):
                    bucket[field] = float(bucket[field]) + float(val)
            cash = rec.get("actual_cash_usd")
            if isinstance(cash, (int, float)) and math.isfinite(float(cash)):
                bucket["actual_cash_usd"] = float(bucket["actual_cash_usd"]) + float(cash)
                bucket["actual_cash_rows"] = int(bucket["actual_cash_rows"]) + 1
    return by_kind


def _cost_fields(rec: Mapping[str, Any]) -> dict[str, float | int | None]:
    cached = rec.get("cached_input_tokens")
    return {
        "input_tokens": int(rec.get("input_tokens") or 0),
        "output_tokens": int(rec.get("output_tokens") or 0),
        "cached_input_tokens": int(cached) if isinstance(cached, int) else None,
        "list_price_inference_usd": float(rec.get("list_price_inference_usd") or 0.0),
        "platform_fee_usd": float(rec.get("platform_fee_usd") or 0.0),
        "effective_prepaid_credits_usd": float(
            rec.get("effective_prepaid_credits_usd") or 0.0
        ),
        "provider_reported_cost_usd": float(rec.get("provider_reported_cost_usd") or 0.0)
        if rec.get("provider_reported_cost_usd") is not None
        else None,
        "actual_cash_usd": float(rec["actual_cash_usd"])
        if isinstance(rec.get("actual_cash_usd"), (int, float))
        else None,
    }


def collect_prediction_usage(
    predictions_path: Path,
) -> dict[str, Any]:
    """Index evaluation prediction rows that carry cache-backed usage/latency."""
    # method -> cache_key -> set(qualified_id)
    key_bugs: dict[str, dict[str, set[str]]] = {
        m: defaultdict(set) for m in METHOD_KIND
    }
    # method -> qualified_id -> list[latency_ms] in file order (shortlist order approx)
    latencies: dict[str, dict[str, list[float]]] = {
        m: defaultdict(list) for m in METHOD_KIND
    }
    # method -> qualified_id -> set(cache_key)
    bug_keys: dict[str, dict[str, set[str]]] = {
        m: defaultdict(set) for m in METHOD_KIND
    }

    with predictions_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            method = row.get("method")
            if method not in METHOD_KIND:
                continue
            if not row.get("score_applicable"):
                continue
            qid = row["qualified_id"]
            key = row.get("cache_key")
            if not isinstance(key, str) or not key:
                raise CostMetricsError(
                    f"{qid} {method}: scored row missing cache_key"
                )
            key_bugs[method][key].add(qid)
            bug_keys[method][qid].add(key)
            lat = row.get("latency_ms")
            if not isinstance(lat, (int, float)) or not math.isfinite(float(lat)):
                raise CostMetricsError(f"{qid} {method}: missing latency_ms")
            latencies[method][qid].append(float(lat))

    return {
        "key_bugs": {m: {k: sorted(v) for k, v in d.items()} for m, d in key_bugs.items()},
        "bug_keys": {m: {q: sorted(ks) for q, ks in d.items()} for m, d in bug_keys.items()},
        "latencies": {m: dict(d) for m, d in latencies.items()},
    }


def equal_share_costs(
    *,
    method: str,
    key_bugs: Mapping[str, Sequence[str]],
    ledger_by_key: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Attribute each unique cache_key cost equally across evaluation bugs using it."""
    per_bug: dict[str, dict[str, float]] = defaultdict(
        lambda: {
            "list_price_inference_usd": 0.0,
            "platform_fee_usd": 0.0,
            "effective_prepaid_credits_usd": 0.0,
            "input_tokens": 0.0,
            "output_tokens": 0.0,
            "shared_keys": 0.0,
            "exclusive_keys": 0.0,
        }
    )
    unique_totals = {
        "list_price_inference_usd": 0.0,
        "platform_fee_usd": 0.0,
        "effective_prepaid_credits_usd": 0.0,
        "input_tokens": 0,
        "output_tokens": 0,
        "unique_keys": 0,
        "shared_keys": 0,
    }
    missing: list[str] = []
    for key, bugs in key_bugs.items():
        rec = ledger_by_key.get(key)
        if rec is None:
            missing.append(key[:16])
            continue
        fields = _cost_fields(rec)
        share_n = len(bugs)
        if share_n < 1:
            continue
        unique_totals["unique_keys"] = int(unique_totals["unique_keys"]) + 1
        if share_n > 1:
            unique_totals["shared_keys"] = int(unique_totals["shared_keys"]) + 1
        for field in (
            "list_price_inference_usd",
            "platform_fee_usd",
            "effective_prepaid_credits_usd",
        ):
            unique_totals[field] = float(unique_totals[field]) + float(fields[field] or 0.0)
        unique_totals["input_tokens"] = int(unique_totals["input_tokens"]) + int(
            fields["input_tokens"] or 0
        )
        unique_totals["output_tokens"] = int(unique_totals["output_tokens"]) + int(
            fields["output_tokens"] or 0
        )
        inv = 1.0 / float(share_n)
        for qid in bugs:
            bucket = per_bug[qid]
            for field in (
                "list_price_inference_usd",
                "platform_fee_usd",
                "effective_prepaid_credits_usd",
            ):
                bucket[field] += float(fields[field] or 0.0) * inv
            bucket["input_tokens"] += float(fields["input_tokens"] or 0) * inv
            bucket["output_tokens"] += float(fields["output_tokens"] or 0) * inv
            if share_n > 1:
                bucket["shared_keys"] += 1.0
            else:
                bucket["exclusive_keys"] += 1.0

    if missing:
        raise CostMetricsError(
            f"{method}: {len(missing)} prediction cache keys missing from ledger "
            f"(e.g. {missing[:3]})"
        )

    # Reconcile: sum of per-bug shares == unique totals
    sum_eff = sum(b["effective_prepaid_credits_usd"] for b in per_bug.values())
    if abs(sum_eff - float(unique_totals["effective_prepaid_credits_usd"])) > 1e-6:
        raise CostMetricsError(
            f"{method}: per-bug effective sum {sum_eff} != unique total "
            f"{unique_totals['effective_prepaid_credits_usd']}"
        )

    scored_candidate_pairs = sum(len(bugs) for bugs in key_bugs.values())

    return {
        "method": method,
        "attribution": "equal_share_unique_cache_key",
        "unique_cache_keys": unique_totals,
        "per_bug": {qid: dict(vals) for qid, vals in sorted(per_bug.items())},
        "cohort": {
            "list_price_inference_usd": float(unique_totals["list_price_inference_usd"]),
            "platform_fee_usd": float(unique_totals["platform_fee_usd"]),
            "effective_prepaid_credits_usd": float(
                unique_totals["effective_prepaid_credits_usd"]
            ),
            "mean_effective_usd_per_bug": float(
                unique_totals["effective_prepaid_credits_usd"]
            )
            / float(EVAL_BUGS),
            "mean_effective_usd_per_scored_candidate": (
                float(unique_totals["effective_prepaid_credits_usd"])
                / float(scored_candidate_pairs)
                if scored_candidate_pairs
                else None
            ),
            "scored_candidate_pairs": scored_candidate_pairs,
            "bugs_with_cost": len(per_bug),
        },
    }


def latency_summary(
    *,
    method: str,
    latencies_by_bug: Mapping[str, Sequence[float]],
) -> dict[str, Any]:
    request_latencies: list[float] = []
    wall_by_bug: dict[str, float] = {}
    for qid, lats in sorted(latencies_by_bug.items()):
        request_latencies.extend(float(x) for x in lats)
        wall_by_bug[qid] = estimate_shortlist_wall_ms(lats, concurrency=MAX_CONCURRENCY)

    walls = list(wall_by_bug.values())
    return {
        "method": method,
        "request_latency_ms": {
            "population": "cache_backed_send_to_full_response",
            "n": len(request_latencies),
            "mean": mean(request_latencies) if request_latencies else None,
            "p50": percentile(request_latencies, 50) if request_latencies else None,
            "p95": percentile(request_latencies, 95) if request_latencies else None,
        },
        "shortlist_wall_ms": {
            "population": (
                f"reconstructed_from_request_latencies_concurrency_{MAX_CONCURRENCY}"
            ),
            "concurrency": MAX_CONCURRENCY,
            "n_bugs": len(walls),
            "mean": mean(walls) if walls else None,
            "p50": percentile(walls, 50) if walls else None,
            "p95": percentile(walls, 95) if walls else None,
            "per_bug": wall_by_bug,
            "note": (
                "Phase 7 scoring did not persist end-to-end shortlist wall clocks; "
                "values are deterministic reconstructions (sum of per-wave maxima)."
            ),
        },
    }


def compute_cost_latency(
    *,
    workspace: Path | None = None,
) -> dict[str, Any]:
    root = workspace or WORKSPACE
    bundle = load_and_verify_sealed_inputs(workspace=root, clear_credentials=True)
    ledger_path = bundle.usage_ledger_path
    predictions_path = bundle.predictions_path
    pricing_path = root / "results" / "pricing_snapshot.json"
    pricing = read_json(pricing_path)

    ledger_eval = sum_evaluation_ledger(ledger_path)
    ledger_by_key = load_ledger_by_cache_key(ledger_path)
    pred = collect_prediction_usage(predictions_path)

    methods_out: dict[str, Any] = {}
    for method, kind in METHOD_KIND.items():
        share = equal_share_costs(
            method=method,
            key_bugs=pred["key_bugs"][method],
            ledger_by_key=ledger_by_key,
        )
        lat = latency_summary(
            method=method,
            latencies_by_bug=pred["latencies"][method],
        )
        methods_out[method] = {
            "kind": kind,
            "cost": share,
            "latency": lat,
            "evaluation_ledger_kind_totals": ledger_eval.get(kind),
        }

    jev_eff = methods_out["Jev"]["cost"]["cohort"]["effective_prepaid_credits_usd"]
    gpt_eff = methods_out["GPT-Nano"]["cost"]["cohort"]["effective_prepaid_credits_usd"]
    if gpt_eff <= 0:
        raise CostMetricsError("GPT effective cost is zero; cannot form Jev/GPT ratio")
    ratio = jev_eff / gpt_eff
    criterion = {
        "basis": "effective_prepaid_credits_usd",
        "definition": "list_price_inference_usd + platform_fee_usd (dated snapshot rates)",
        "numerator_jev_usd": jev_eff,
        "denominator_gpt_usd": gpt_eff,
        "ratio": ratio,
        "threshold": JEV_GPT_COST_RATIO_THRESHOLD,
        "jev_leq_30pct_of_gpt": ratio <= JEV_GPT_COST_RATIO_THRESHOLD,
        "pricing_snapshot_path": "results/pricing_snapshot.json",
        "pricing_snapshot_sha256": sha256_file(pricing_path),
        "pricing_snapshot_date": pricing.get("snapshot_date"),
        "notes": [
            "Do not treat promotional actual_cash_usd or free-tier credits as zero inference cost",
            "Embedding vectors reused across bugs are equal-share attributed; cohort totals use unique cache keys",
            "Random and BM25 have zero measured inference cost",
        ],
    }

    # Free methods
    methods_out["BM25"] = {
        "kind": None,
        "cost": {
            "cohort": {
                "effective_prepaid_credits_usd": 0.0,
                "mean_effective_usd_per_bug": 0.0,
            }
        },
        "latency": None,
    }
    methods_out["Random"] = {
        "kind": None,
        "cost": {
            "cohort": {
                "effective_prepaid_credits_usd": 0.0,
                "mean_effective_usd_per_bug": 0.0,
            }
        },
        "latency": None,
    }

    return {
        "schema_version": COST_SCHEMA,
        "created_at": _utcnow(),
        "experiment_commit": bundle.experiment_commit,
        "run_id": bundle.run_id,
        "freeze_tag": bundle.freeze_tag,
        "predictions_sha256": bundle.predictions_sha256,
        "usage_ledger_path": "results/usage_ledger.jsonl",
        "usage_ledger_sha256": sha256_file(ledger_path),
        "evaluation_ledger_totals_by_kind": ledger_eval,
        "methods": methods_out,
        "jev_vs_gpt_cost_criterion": criterion,
        "concurrency_cap": MAX_CONCURRENCY,
    }


def run_cost_latency(
    *,
    workspace: Path | None = None,
    write_path: Path | None = None,
) -> dict[str, Any]:
    payload = compute_cost_latency(workspace=workspace)
    # Drop bulky per-bug wall maps from the default written artifact? Keep them —
    # useful for metrics.csv later. Optionally trim in a summary view.
    out = write_path or (
        (workspace or WORKSPACE) / "results" / "phase8" / "cost_latency.json"
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
        payload = run_cost_latency(workspace=args.workspace, write_path=args.write)
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    crit = payload["jev_vs_gpt_cost_criterion"]
    print(
        f"OK jev_eff={crit['numerator_jev_usd']:.4f} "
        f"gpt_eff={crit['denominator_gpt_usd']:.4f} "
        f"ratio={crit['ratio']:.4f} "
        f"leq30pct={crit['jev_leq_30pct_of_gpt']} "
        f"path={payload.get('_write_path')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
