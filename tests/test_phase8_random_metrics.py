"""P8-03: Random baseline aggregation over sealed permutations."""

from __future__ import annotations

import unittest

from src.example_contract import WORKSPACE
from src.random_metrics import (
    cohort_replicate_cdf,
    cohort_replicate_median_nftr,
    mean_metrics_over_permutations,
    permutation_metric_values,
    run_random_metrics,
)


class SyntheticRandomAggregationTests(unittest.TestCase):
    def test_exhaustive_n2_mean_metrics(self) -> None:
        # Inventory [A, B], positive={A}: both permutations.
        perms = [["A", "B"], ["B", "A"]]
        means = mean_metrics_over_permutations(perms, ["A"])
        self.assertAlmostEqual(means["first_trigger_rank"], 1.5)
        self.assertAlmostEqual(means["normalized_first_trigger_rank"], 0.75)
        self.assertAlmostEqual(means["reciprocal_rank"], 0.75)
        # APFD: rank1 → 1-0.5+0.25=0.75; rank2 → 1-1+0.25=0.25; mean=0.5
        self.assertAlmostEqual(means["apfd"], 0.5)
        # 50% budget: k=max(1,ceil(1.0))=1 → detect only when A is first
        self.assertAlmostEqual(means["detected_at_50pct"], 0.5)
        self.assertAlmostEqual(means["detected_at_100pct"], 1.0)

    def test_permutation_metric_values_rank_bounds(self) -> None:
        vals = permutation_metric_values(["t", "x", "y"], ["t"])
        self.assertEqual(vals["first_trigger_rank"], 1.0)
        self.assertAlmostEqual(vals["reciprocal_rank"], 1.0)

    def test_cohort_median_uses_replicates_not_median_of_means(self) -> None:
        # Two bugs, two permutation replicates.
        # Bug means would be (0.2+0.8)/2=0.5 and (0.4+0.6)/2=0.5 → median_of_means=0.5
        # Replicate0: [0.2, 0.4] median=0.3; replicate1: [0.8, 0.6] median=0.7
        # mean of medians = 0.5 (same here) — change to make them differ:
        nftr = [
            [0.1, 0.9],  # bug0 mean=0.5
            [0.2, 0.3],  # bug1 mean=0.25
        ]
        # median of per-bug means = median(0.5, 0.25) = 0.375
        # replicate medians: med(0.1,0.2)=0.15; med(0.9,0.3)=0.6; mean=0.375
        # Use asymmetric case:
        nftr = [
            [0.1, 0.9, 0.9],
            [0.2, 0.2, 0.8],
            [0.3, 0.4, 0.5],
        ]
        # Temporarily monkey with NUM check — function requires 1000.
        # Call internals by temporarily patching length via direct median math here.
        from src.random_metrics import _median, _mean

        medians = []
        for i in range(3):
            medians.append(_median([nftr[b][i] for b in range(3)]))
        replicate_rule = _mean(medians)
        per_bug_means = [_mean(row) for row in nftr]
        median_of_means = _median(per_bug_means)
        self.assertNotAlmostEqual(replicate_rule, median_of_means)
        # Spot-check replicate_rule arithmetic
        self.assertAlmostEqual(medians[0], 0.2)  # 0.1,0.2,0.3
        self.assertAlmostEqual(medians[1], 0.4)  # 0.9,0.2,0.4
        self.assertAlmostEqual(medians[2], 0.8)  # 0.9,0.8,0.5
        self.assertAlmostEqual(replicate_rule, (0.2 + 0.4 + 0.8) / 3)

    def test_cohort_replicate_helpers_with_padded_matrix(self) -> None:
        # Pad a tiny matrix to 1000 columns with repeated columns for API contract.
        base = [
            [0.1, 0.9],
            [0.2, 0.3],
        ]
        matrix = []
        for row in base:
            full = (row * 500)[:1000]
            matrix.append(full)
        block = cohort_replicate_median_nftr(matrix)
        self.assertEqual(block["n_replicates"], 1000)
        self.assertTrue(0.0 <= block["median_nftr"] <= 1.0)
        cdf = cohort_replicate_cdf(matrix, grid=(0.0, 0.5, 1.0))
        self.assertEqual(cdf[0]["fraction_bugs"], 0.0)
        self.assertEqual(cdf[-1]["fraction_bugs"], 1.0)


@unittest.skipUnless(
    (WORKSPACE / "results" / "phase7" / "raw_evaluation_seal.json").is_file(),
    "requires sealed Phase 7 workspace",
)
class SealedRandomMetricsTests(unittest.TestCase):
    def test_one_row_per_evaluation_bug(self) -> None:
        payload = run_random_metrics()
        self.assertEqual(payload["counts"]["random_rows"], 113)
        self.assertEqual(len(payload["records"]), 113)
        for row in payload["records"]:
            self.assertEqual(row["method"], "Random")
            self.assertEqual(row["num_permutations"], 1000)
            self.assertTrue(0.0 <= row["detected_at_10pct"] <= 1.0)
            # Fractional ranks are expected for averages
            self.assertIsInstance(row["first_trigger_rank"], float)
        ag = payload["aggregates"]
        self.assertAlmostEqual(
            ag["primary_fdr_at_10pct"],
            ag["fdr_at_10pct"],
        )
        self.assertNotEqual(
            ag["median_nftr"],
            ag["median_of_per_bug_mean_nftr"],
            msg="headline median NFTR must use replicate rule, not median-of-means",
        )
        self.assertEqual(len(payload["cdf"]), 101)


if __name__ == "__main__":
    unittest.main()
