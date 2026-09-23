"""P8-02: pure ranking metrics and sealed per-bug records."""

from __future__ import annotations

import math
import unittest

from src.example_contract import WORKSPACE
from src.metrics import (
    MetricsError,
    apfd,
    budget_k,
    compute_per_bug_metrics,
    detected_at_budget,
    first_trigger_rank,
    normalized_first_trigger_rank,
    reciprocal_rank,
    run_per_bug_metrics,
)


class HandWorkedMetricTests(unittest.TestCase):
    def test_budget_k_ceiling_and_floor(self) -> None:
        self.assertEqual(budget_k(fraction=0.10, n=100), 10)
        self.assertEqual(budget_k(fraction=0.10, n=15), 2)  # ceil(1.5)
        self.assertEqual(budget_k(fraction=0.01, n=1), 1)
        self.assertEqual(budget_k(fraction=1.0, n=7), 7)
        self.assertEqual(budget_k(fraction=0.01, n=50), 1)  # ceil(0.5)->1

    def test_rank_1_and_rank_n(self) -> None:
        ids = [f"c{i}" for i in range(1, 11)]
        self.assertEqual(first_trigger_rank(ids, ["c1"]), 1)
        self.assertEqual(first_trigger_rank(ids, ["c10"]), 10)
        self.assertEqual(reciprocal_rank(1), 1.0)
        self.assertEqual(reciprocal_rank(10), 0.1)
        self.assertEqual(normalized_first_trigger_rank(r=1, n=10), 0.1)
        self.assertEqual(normalized_first_trigger_rank(r=10, n=10), 1.0)
        self.assertAlmostEqual(apfd(r=1, n=10), 0.95)
        self.assertAlmostEqual(apfd(r=10, n=10), 0.05)

    def test_multiple_triggers_use_minimum_rank(self) -> None:
        ids = ["a", "b", "t2", "c", "t1", "d"]
        self.assertEqual(first_trigger_rank(ids, ["t1", "t2"]), 3)

    def test_detection_budgets(self) -> None:
        ids = [f"c{i}" for i in range(1, 101)]
        positives = ["c10"]  # rank 10
        self.assertFalse(detected_at_budget(ids, positives, fraction=0.05))  # k=5
        self.assertTrue(detected_at_budget(ids, positives, fraction=0.10))  # k=10
        self.assertTrue(detected_at_budget(ids, positives, fraction=1.0))

    def test_tiny_suite_k_always_at_least_one(self) -> None:
        ids = ["only"]
        self.assertTrue(detected_at_budget(ids, ["only"], fraction=0.01))
        self.assertEqual(budget_k(fraction=0.01, n=1), 1)
        self.assertAlmostEqual(apfd(r=1, n=1), 0.5)

    def test_apfd_limits(self) -> None:
        # Best case rank 1 → approaches 1 as N grows
        self.assertGreater(apfd(r=1, n=1000), 0.999)
        # Worst case rank N → 1/(2N)
        self.assertAlmostEqual(apfd(r=100, n=100), 0.005)

    def test_compute_record_fields(self) -> None:
        ranked = ["x", "trigger", "y", "z"]
        rec = compute_per_bug_metrics(
            ranked_ids=ranked,
            positive_classes=["trigger"],
            candidate_ids=["x", "trigger"],
            project="Cli",
            bug_id="1",
            qualified_id="Cli-1",
            method="BM25",
        )
        self.assertEqual(rec.first_trigger_rank, 2)
        self.assertTrue(rec.detected_at_50pct)
        self.assertTrue(rec.candidate_trigger_in_top200)
        self.assertTrue(rec.available)

    def test_rejects_empty_positives(self) -> None:
        with self.assertRaises(MetricsError):
            first_trigger_rank(["a"], [])


@unittest.skipUnless(
    (WORKSPACE / "results" / "phase7" / "raw_evaluation_seal.json").is_file(),
    "requires sealed Phase 7 workspace",
)
class SealedPerBugMetricsTests(unittest.TestCase):
    def test_every_bug_has_four_method_records(self) -> None:
        payload = run_per_bug_metrics()
        self.assertEqual(payload["counts"]["records"], 500)
        self.assertEqual(payload["counts"]["unavailable_jev"], 12)
        methods = {r["method"] for r in payload["records"]}
        self.assertEqual(methods, {"BM25", "Embedding", "Jev", "GPT-Nano"})
        # One available FDR@10% in [0,1] for each method
        for method, agg in payload["aggregates"].items():
            self.assertGreaterEqual(agg["primary_fdr_at_10pct"], 0.0)
            self.assertLessEqual(agg["primary_fdr_at_10pct"], 1.0)
            self.assertTrue(math.isfinite(agg["mrr"]))
            self.assertTrue(math.isfinite(agg["mean_apfd"]))
            self.assertTrue(math.isfinite(agg["median_nftr"]))
            if method == "Jev":
                self.assertEqual(agg["n_available"], 113)
            else:
                self.assertEqual(agg["n_available"], 125)


if __name__ == "__main__":
    unittest.main()
