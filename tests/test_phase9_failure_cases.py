"""P9-03: mechanical 20-case selection."""

from __future__ import annotations

import unittest

from src.example_contract import WORKSPACE, read_json
from src.phase9_failure_cases import publish_failure_cases, select_failure_cases
from src.seal_analysis import build_case20_deltas


@unittest.skipUnless(
    (WORKSPACE / "results" / "phase8" / "per_bug_metrics.json").is_file(),
    "requires Phase 8 per_bug_metrics",
)
class Phase9FailureCasesTests(unittest.TestCase):
    def test_selection_matches_phase8_seal(self) -> None:
        doc = select_failure_cases()
        self.assertTrue(doc["ok"])
        self.assertEqual(doc["n_evaluation_bugs"], 113)
        self.assertEqual(len(doc["selected_ids"]), 20)
        self.assertEqual(len(set(doc["selected_ids"])), 20)
        self.assertEqual(len(doc["top10_jev_gains"]), 10)
        self.assertEqual(len(doc["top10_jev_losses"]), 10)

        sealed = read_json(WORKSPACE / "results" / "phase8" / "case20_deltas.json")
        self.assertEqual(doc["selected_ids"], sealed["selected_ids"])

        # Gains arm is nonincreasing delta; losses arm is nondecreasing.
        gain_deltas = [c["delta_bm25_minus_jev"] for c in doc["top10_jev_gains"]]
        loss_deltas = [c["delta_bm25_minus_jev"] for c in doc["top10_jev_losses"]]
        self.assertEqual(gain_deltas, sorted(gain_deltas, reverse=True))
        self.assertEqual(loss_deltas, sorted(loss_deltas))

        # Every case has ranks, delta, shortlist status, and accurate sign label.
        for case in doc["cases"]:
            self.assertIn(case["delta_sign_label"], {"jev_gain", "jev_loss", "tie"})
            d = case["delta_bm25_minus_jev"]
            if d > 0:
                self.assertEqual(case["delta_sign_label"], "jev_gain")
            elif d < 0:
                self.assertEqual(case["delta_sign_label"], "jev_loss")
            else:
                self.assertEqual(case["delta_sign_label"], "tie")
            self.assertIsInstance(case["candidate_trigger_in_top200"], bool)

    def test_regeneration_stable(self) -> None:
        a = build_case20_deltas(workspace=WORKSPACE)
        b = select_failure_cases()
        self.assertEqual(a["selected_ids"], b["selected_ids"])

    def test_publish_writes_artifacts(self) -> None:
        doc = publish_failure_cases()
        path = WORKSPACE / "results" / "failure_cases.json"
        md = WORKSPACE / "results" / "phase9" / "failure_cases.md"
        self.assertTrue(path.is_file())
        self.assertTrue(md.is_file())
        loaded = read_json(path)
        self.assertEqual(loaded["selected_ids"], doc["selected_ids"])
        self.assertIn("per_bug_metrics", loaded["input_hashes"])
        text = md.read_text(encoding="utf-8")
        self.assertIn("JacksonDatabind-62", text)
        self.assertIn("BM25−Jev", text)


if __name__ == "__main__":
    unittest.main()
