"""P8-05: cohort, project, and candidate-ceiling summaries."""

from __future__ import annotations

import unittest

from src.cohort_summaries import (
    materialize_jev_record,
    practical_success_table,
    run_cohort_summaries,
)
from src.example_contract import WORKSPACE


class PracticalSuccessUnitTests(unittest.TestCase):
    def test_alt1_and_alt2(self) -> None:
        cost = {
            "ratio": 0.25,
            "jev_leq_30pct_of_gpt": True,
            "numerator_jev_usd": 1.0,
            "denominator_gpt_usd": 4.0,
        }
        # Beat BM25 by 5pp
        table = practical_success_table(
            fdr={
                "Jev": 0.80,
                "BM25": 0.70,
                "GPT-Nano": 0.90,
                "Embedding": 0.75,
                "Random": 0.1,
            },
            cost_ratio=cost,
        )
        self.assertTrue(table["alternative_1_beat_bm25_by_5pp"]["passed"])
        self.assertTrue(table["practically_successful"])

        # Near GPT but cost fails
        cost_fail = dict(cost, ratio=0.5, jev_leq_30pct_of_gpt=False)
        table2 = practical_success_table(
            fdr={
                "Jev": 0.90,
                "BM25": 0.88,
                "GPT-Nano": 0.91,
                "Embedding": 0.85,
                "Random": 0.1,
            },
            cost_ratio=cost_fail,
        )
        self.assertFalse(table2["alternative_1_beat_bm25_by_5pp"]["passed"])
        self.assertFalse(table2["alternative_2_near_gpt_and_cheap"]["passed"])
        self.assertFalse(table2["practically_successful"])

    def test_impute_and_classify(self) -> None:
        gap = {
            "qualified_id": "Jsoup-33",
            "available": False,
            "num_test_classes": 20,
            "candidate_trigger_in_top200": True,
            "detected_at_10pct": None,
        }
        row = materialize_jev_record(gap)
        self.assertFalse(row["detected_at_10pct"])
        self.assertEqual(row["first_trigger_rank"], 20)
        self.assertTrue(row["imputed"])


@unittest.skipUnless(
    (WORKSPACE / "results" / "phase8" / "per_bug_metrics.json").is_file(),
    "requires Phase 8 metric artifacts",
)
class SealedCohortSummaryTests(unittest.TestCase):
    def test_denominators_and_miss_partition(self) -> None:
        payload = run_cohort_summaries()
        for method, block in payload["cohort"].items():
            self.assertEqual(block["denominator"], 113, msg=method)
        for project, block in payload["projects"].items():
            expected = 13 if project == "Jsoup" else 25
            self.assertEqual(block["denominator"], expected, msg=project)
        recall = payload["candidate_ceiling"]
        self.assertEqual(recall["denominator"], 113)
        self.assertGreaterEqual(recall["recall"], 0.0)
        self.assertLessEqual(recall["recall"], 1.0)

        misses = payload["jev_miss_classification"]
        self.assertEqual(
            misses["n_misses"],
            misses["candidate_generation_misses"]["count"]
            + misses["reranker_misses"]["count"],
        )
        self.assertEqual(
            misses["n_detections"] + misses["n_misses"],
            113,
        )
        # Every miss ID appears once
        ids = (
            misses["candidate_generation_misses"]["bug_ids"]
            + misses["reranker_misses"]["bug_ids"]
        )
        self.assertEqual(len(ids), len(set(ids)))

        ps = payload["practical_success"]
        self.assertIn("practically_successful", ps)
        self.assertAlmostEqual(
            ps["fdr_at_10pct"]["Jev"],
            payload["cohort"]["Jev"]["primary_fdr_at_10pct"],
        )


if __name__ == "__main__":
    unittest.main()
