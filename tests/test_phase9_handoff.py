"""P9-01: Phase 8 handoff verification and report headline."""

from __future__ import annotations

import unittest
from pathlib import Path

from src.example_contract import WORKSPACE, read_json, sha256_file
from src.phase9_handoff import (
    _best_methods,
    render_report_headline,
    run_phase9_handoff,
    verify_handoff,
)
from src.report_outputs import METHODS, build_headline_table


class BestMethodsUnitTests(unittest.TestCase):
    def test_ties_and_lower_better(self) -> None:
        methods = {
            "Random": {"fdr_at_10pct": 0.1, "median_nftr": 0.5},
            "BM25": {"fdr_at_10pct": 0.9, "median_nftr": 0.2},
            "Embedding": {"fdr_at_10pct": 0.9, "median_nftr": 0.2},
            "Jev": {"fdr_at_10pct": 0.8, "median_nftr": 0.1},
            "GPT-Nano": {"fdr_at_10pct": 0.85, "median_nftr": 0.15},
        }
        self.assertEqual(
            _best_methods(methods, "fdr_at_10pct"),
            {"BM25", "Embedding"},
        )
        self.assertEqual(
            _best_methods(methods, "median_nftr", lower_better=True),
            {"Jev"},
        )


@unittest.skipUnless(
    (WORKSPACE / "results" / "phase8" / "analysis_seal.json").is_file(),
    "requires sealed Phase 8 workspace",
)
class Phase9HandoffTests(unittest.TestCase):
    def test_verify_and_write_headline(self) -> None:
        result = run_phase9_handoff()
        self.assertTrue(result["ok"])
        verification = result["verification"]
        self.assertTrue(verification["ok"], msg=verification.get("errors"))
        self.assertEqual(verification["n_evaluation_bugs"], 113)
        self.assertEqual(verification["n_metrics_rows"], 565)

        md_path = Path(result["headline_md"])
        self.assertTrue(md_path.is_file())
        text = md_path.read_text(encoding="utf-8")
        for name in ("Random", "BM25", "Embedding", "Jev", "GPT-5.4 nano"):
            self.assertIn(name, text)
        self.assertIn("FDR@10%", text)
        self.assertIn("Provenance", text)
        self.assertIn("—", text)

        # Values match sealed cohort / Phase 8 headline builder
        table = build_headline_table(workspace=WORKSPACE)
        self.assertIn(f"{table['methods']['Jev']['fdr_at_10pct']:.4f}", text)
        self.assertIn(f"{table['methods']['BM25']['fdr_at_10pct']:.4f}", text)

        verify_path = WORKSPACE / "results" / "phase9" / "handoff_verification.json"
        self.assertTrue(verify_path.is_file())
        doc = read_json(verify_path)
        self.assertEqual(sha256_file(WORKSPACE / "results" / "metrics.csv"), doc["metrics_csv"]["sha256"])


if __name__ == "__main__":
    unittest.main()
