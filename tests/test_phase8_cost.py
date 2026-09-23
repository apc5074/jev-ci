"""P8-04: sealed cost and latency reconciliation."""

from __future__ import annotations

import unittest

from src.cost_metrics import (
    CostMetricsError,
    estimate_shortlist_wall_ms,
    mean,
    percentile,
    run_cost_latency,
    sum_evaluation_ledger,
)
from src.example_contract import WORKSPACE


class CostHelperTests(unittest.TestCase):
    def test_percentile_and_mean(self) -> None:
        vals = [1.0, 2.0, 3.0, 4.0]
        self.assertAlmostEqual(mean(vals), 2.5)
        self.assertAlmostEqual(percentile(vals, 50), 2.5)
        self.assertAlmostEqual(percentile([10.0], 95), 10.0)

    def test_shortlist_wall_waves(self) -> None:
        # concurrency 2: waves (10,3)->10; (4,5)->5; total 15
        self.assertAlmostEqual(
            estimate_shortlist_wall_ms([10, 3, 4, 5], concurrency=2),
            15.0,
        )
        self.assertAlmostEqual(estimate_shortlist_wall_ms([], concurrency=16), 0.0)

    def test_rejects_bad_percentile(self) -> None:
        with self.assertRaises(CostMetricsError):
            percentile([], 50)


@unittest.skipUnless(
    (WORKSPACE / "results" / "phase7" / "raw_evaluation_seal.json").is_file(),
    "requires sealed Phase 7 workspace",
)
class SealedCostLatencyTests(unittest.TestCase):
    def test_reconcile_and_criterion(self) -> None:
        payload = run_cost_latency()
        ledger = sum_evaluation_ledger(WORKSPACE / "results" / "usage_ledger.jsonl")
        # Independent ledger sums match the embedded evaluation_ledger totals
        for kind, bucket in ledger.items():
            reported = payload["evaluation_ledger_totals_by_kind"][kind]
            self.assertEqual(bucket["rows"], reported["rows"])
            self.assertAlmostEqual(
                float(bucket["effective_prepaid_credits_usd"]),
                float(reported["effective_prepaid_credits_usd"]),
                places=9,
            )

        emb = payload["methods"]["Embedding"]["cost"]
        # Per-bug shares reconcile to unique-key cohort total
        per_bug_sum = sum(
            b["effective_prepaid_credits_usd"] for b in emb["per_bug"].values()
        )
        self.assertAlmostEqual(
            per_bug_sum,
            emb["cohort"]["effective_prepaid_credits_usd"],
            places=6,
        )
        self.assertGreater(emb["unique_cache_keys"]["shared_keys"], 0)

        crit = payload["jev_vs_gpt_cost_criterion"]
        self.assertAlmostEqual(
            crit["ratio"],
            crit["numerator_jev_usd"] / crit["denominator_gpt_usd"],
            places=12,
        )
        self.assertEqual(
            crit["jev_leq_30pct_of_gpt"],
            crit["ratio"] <= 0.30,
        )

        jev_lat = payload["methods"]["Jev"]["latency"]["request_latency_ms"]
        self.assertGreater(jev_lat["n"], 0)
        self.assertLessEqual(jev_lat["p50"], jev_lat["p95"])


if __name__ == "__main__":
    unittest.main()
