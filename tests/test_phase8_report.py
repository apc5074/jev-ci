"""P8-07: metrics.csv, headline table, and figure outputs."""

from __future__ import annotations

import csv
import unittest
from pathlib import Path

from src.example_contract import WORKSPACE
from src.report_outputs import CSV_COLUMNS, METHODS, run_report_outputs


@unittest.skipUnless(
    (WORKSPACE / "results" / "phase8" / "cohort_summaries.json").is_file(),
    "requires Phase 8 cohort summaries",
)
class ReportOutputTests(unittest.TestCase):
    def test_metrics_csv_schema_and_counts(self) -> None:
        sidecar = run_report_outputs()
        path = WORKSPACE / "results" / "metrics.csv"
        self.assertTrue(path.is_file())
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            self.assertEqual(reader.fieldnames, CSV_COLUMNS)
            rows = list(reader)
        self.assertEqual(len(rows), 565)
        methods = {r["method"] for r in rows}
        self.assertEqual(methods, set(METHODS))
        self.assertTrue(all(r["split"] == "evaluation" for r in rows))
        # No development IDs
        self.assertTrue(all(r["qualified_id"].count("-") == 1 for r in rows))
        self.assertEqual(sidecar["metrics_csv"]["n_rows"], 565)
        self.assertTrue(
            (WORKSPACE / "results" / "phase8" / "headline_table.md").is_file()
        )
        self.assertTrue(
            (WORKSPACE / "results" / "phase8" / "figure_data.json").is_file()
        )
        for name in (
            "figure1_budget_curve.svg",
            "figure2_nftr_cdf.svg",
            "figure3_project_fdr10.svg",
            "figure4_quality_vs_cost.svg",
        ):
            self.assertTrue(
                (WORKSPACE / "results" / "phase8" / "figures" / name).is_file()
            )


if __name__ == "__main__":
    unittest.main()
