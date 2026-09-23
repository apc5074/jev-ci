"""P8-09: analysis seal and Phase 9 handoff."""

from __future__ import annotations

import unittest

from src.example_contract import WORKSPACE, read_json, sha256_file
from src.seal_analysis import audit_cross_file_consistency, build_case20_deltas


@unittest.skipUnless(
    (WORKSPACE / "results" / "metrics.csv").is_file(),
    "requires Phase 8 metrics workspace",
)
class AnalysisSealTests(unittest.TestCase):
    def test_audit_passes(self) -> None:
        report = audit_cross_file_consistency(workspace=WORKSPACE)
        self.assertTrue(report["ok"], msg=report.get("errors"))

    def test_case20_has_twenty_distinct_ids(self) -> None:
        case20 = build_case20_deltas(workspace=WORKSPACE)
        ids = case20["selected_ids"]
        self.assertEqual(len(ids), 20)
        self.assertEqual(len(set(ids)), 20)
        self.assertEqual(len(case20["top10_jev_gains"]), 10)
        self.assertEqual(len(case20["top10_jev_losses"]), 10)

    def test_seal_hashes_match_files(self) -> None:
        seal_path = WORKSPACE / "results" / "phase8" / "analysis_seal.json"
        self.assertTrue(seal_path.is_file())
        seal = read_json(seal_path)
        self.assertTrue(seal["ok"])
        # seal_sha256 is the hash of the seal body before embedding that field.
        self.assertTrue(isinstance(seal.get("seal_sha256"), str))
        self.assertEqual(len(seal["seal_sha256"]), 64)
        for key, meta in seal["phase8_artifacts"].items():
            if key == "figures":
                for name, fig in meta.items():
                    self.assertEqual(
                        sha256_file(WORKSPACE / fig["path"]),
                        fig["sha256"],
                        msg=name,
                    )
            else:
                self.assertEqual(
                    sha256_file(WORKSPACE / meta["path"]),
                    meta["sha256"],
                    msg=key,
                )
        handoff = WORKSPACE / "docs" / "phase8-handoff.md"
        self.assertTrue(handoff.is_file())
        self.assertIn("PASS", handoff.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
