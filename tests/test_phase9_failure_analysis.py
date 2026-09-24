"""P9-04: bounded qualitative failure analysis."""

from __future__ import annotations

import unittest

from src.example_contract import WORKSPACE, read_json
from src.phase9_failure_analysis import (
    ANALYSIS_ROWS,
    CATEGORIES,
    publish_failure_analysis,
    validate_analysis_rows,
)


@unittest.skipUnless(
    (WORKSPACE / "results" / "failure_cases.json").is_file(),
    "requires P9-03 failure_cases.json",
)
class Phase9FailureAnalysisTests(unittest.TestCase):
    def test_rows_match_selection(self) -> None:
        fc = read_json(WORKSPACE / "results" / "failure_cases.json")
        validate_analysis_rows(ANALYSIS_ROWS, selected_ids=fc["selected_ids"])
        for row in ANALYSIS_ROWS:
            self.assertIn(row["dominant_category"], CATEGORIES)
            self.assertGreater(len(row["evidence"]), 40)

    def test_publish(self) -> None:
        doc = publish_failure_analysis()
        self.assertTrue(doc["ok"])
        self.assertEqual(doc["n_cases"], 20)
        self.assertEqual(doc["shortlist_miss_cases"], 0)
        path = WORKSPACE / "results" / "failure_analysis.json"
        md = WORKSPACE / "results" / "phase9" / "failure_analysis.md"
        self.assertTrue(path.is_file())
        self.assertTrue(md.is_file())
        loaded = read_json(path)
        self.assertEqual(loaded["selected_ids"], doc["selected_ids"])
        cats = {c["dominant_category"] for c in loaded["cases"]}
        self.assertTrue(cats <= set(CATEGORIES))
        # No BM25 shortlist miss in this set — all trig∈top200.
        self.assertNotIn("BM25 candidate-generation miss", cats)
        text = md.read_text(encoding="utf-8")
        self.assertIn("JacksonDatabind-62", text)
        self.assertIn("behavioral semantic match", text)
        self.assertIn("Category", text)


if __name__ == "__main__":
    unittest.main()
