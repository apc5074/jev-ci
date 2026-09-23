"""P8-06: exact McNemar and paired bootstrap fixtures."""

from __future__ import annotations

import math
import unittest

from src.example_contract import WORKSPACE
from src.statistics import (
    BOOTSTRAP_SEED,
    draw_bootstrap_index_samples,
    mcnemar_exact_two_sided,
    paired_detection_table,
    point_deltas,
    run_statistics,
)


class McNemarExactTests(unittest.TestCase):
    def test_zero_discordance(self) -> None:
        self.assertEqual(mcnemar_exact_two_sided(b=0, c=0), 1.0)

    def test_hand_worked_binomial(self) -> None:
        # n=5, k=5 → 2 * (1/32) = 1/16
        self.assertAlmostEqual(mcnemar_exact_two_sided(b=5, c=0), 1.0 / 16.0)
        # n=4, k=3 → 2 * (C(4,3)+C(4,4))/16 = 2*(4+1)/16 = 10/16 = 0.625
        self.assertAlmostEqual(mcnemar_exact_two_sided(b=3, c=1), 0.625)

    def test_paired_table_counts(self) -> None:
        jev = [True, True, False, False, True]
        bm25 = [True, False, True, False, True]
        table = paired_detection_table(jev, bm25)
        self.assertEqual(table["both"], 2)
        self.assertEqual(table["jev_only"], 1)
        self.assertEqual(table["other_only"], 1)
        self.assertEqual(table["neither"], 1)
        self.assertEqual(table["n_discordant"], 2)


class BootstrapFixtureTests(unittest.TestCase):
    def test_seed_deterministic_samples(self) -> None:
        a = draw_bootstrap_index_samples(n_bugs=5, n_samples=20, seed=BOOTSTRAP_SEED)
        b = draw_bootstrap_index_samples(n_bugs=5, n_samples=20, seed=BOOTSTRAP_SEED)
        self.assertEqual(a, b)
        c = draw_bootstrap_index_samples(n_bugs=5, n_samples=20, seed=BOOTSTRAP_SEED + 1)
        self.assertNotEqual(a, c)

    def test_point_deltas_sign(self) -> None:
        matrix = {
            "Jev": {
                "detected_at_10pct": [1.0, 1.0, 0.0],
                "reciprocal_rank": [1.0, 0.5, 0.25],
                "apfd": [0.9, 0.7, 0.5],
                "normalized_first_trigger_rank": [0.1, 0.2, 0.8],
            },
            "BM25": {
                "detected_at_10pct": [1.0, 0.0, 0.0],
                "reciprocal_rank": [0.5, 0.25, 0.2],
                "apfd": [0.7, 0.5, 0.4],
                "normalized_first_trigger_rank": [0.2, 0.4, 0.9],
            },
        }
        d = point_deltas(matrix, method_a="Jev", method_b="BM25")
        self.assertAlmostEqual(d["delta_fdr_at_10pct"], (2 / 3) - (1 / 3))
        self.assertGreater(d["delta_mrr"], 0.0)
        self.assertLess(d["delta_median_nftr"], 0.0)


@unittest.skipUnless(
    (WORKSPACE / "results" / "phase8" / "per_bug_metrics.json").is_file(),
    "requires Phase 8 metric artifacts",
)
class SealedStatisticsTests(unittest.TestCase):
    def test_primary_and_reproducible(self) -> None:
        first = run_statistics()
        second = run_statistics()
        # Drop timestamps for equality
        for payload in (first, second):
            payload.pop("created_at", None)
            payload.pop("_write_path", None)
        self.assertEqual(first, second)

        prim = first["primary"]
        self.assertEqual(prim["role"], "primary")
        self.assertEqual(prim["contrast"], ["Jev", "BM25"])
        table = prim["paired_detection_fdr_at_10pct"]
        self.assertEqual(
            table["both"]
            + table["jev_only"]
            + table["other_only"]
            + table["neither"],
            125,
        )
        self.assertEqual(first["configuration"]["bootstrap_samples"], 10000)
        self.assertEqual(first["configuration"]["bootstrap_seed"], BOOTSTRAP_SEED)
        self.assertEqual(len(first["secondary"]), 2)
        for sec in first["secondary"]:
            self.assertEqual(sec["role"], "secondary")
            for key in (
                "delta_fdr_at_10pct",
                "delta_mrr",
                "delta_apfd",
                "delta_median_nftr",
            ):
                block = sec["bootstrap"][key]
                self.assertLessEqual(block["ci95_low"], block["ci95_high"])
                self.assertIsNotNone(block["point"])


if __name__ == "__main__":
    unittest.main()
