"""P8-08: offline evaluate.py regeneration."""

from __future__ import annotations

import unittest
from pathlib import Path

from src.evaluate import regenerate_all
from src.example_contract import WORKSPACE, sha256_file
from src.evaluate_checks import run_evaluate_checks


@unittest.skipUnless(
    (WORKSPACE / "results" / "phase7" / "raw_evaluation_seal.json").is_file(),
    "requires sealed Phase 7 workspace",
)
class EvaluateOfflineTests(unittest.TestCase):
    def test_checks_pass_on_current_artifacts(self) -> None:
        report = run_evaluate_checks()
        self.assertTrue(report["ok"], msg=report.get("failures"))

    def test_regenerate_deterministic(self) -> None:
        first = regenerate_all()
        second = regenerate_all()
        self.assertTrue(first["ok"])
        self.assertTrue(second["ok"])
        # Stable artifacts must match across reruns
        self.assertEqual(
            first["artifacts"]["metrics_csv"]["sha256"],
            second["artifacts"]["metrics_csv"]["sha256"],
        )
        self.assertEqual(
            first["artifacts"]["headline_table"]["sha256"],
            second["artifacts"]["headline_table"]["sha256"],
        )
        self.assertEqual(
            first["artifacts"]["statistics_json"]["sha256"],
            second["artifacts"]["statistics_json"]["sha256"],
        )
        for name in first["artifacts"]["figures"]:
            self.assertEqual(
                first["artifacts"]["figures"][name]["sha256"],
                second["artifacts"]["figures"][name]["sha256"],
                msg=name,
            )
        # Live file hashes agree with the record
        self.assertEqual(
            sha256_file(WORKSPACE / "results" / "metrics.csv"),
            first["artifacts"]["metrics_csv"]["sha256"],
        )


class EvaluateFailureTests(unittest.TestCase):
    def test_missing_seal_fails(self) -> None:
        import tempfile
        from src.evaluate import EvaluateError, regenerate_all

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "results" / "phase7").mkdir(parents=True)
            with self.assertRaises(EvaluateError):
                regenerate_all(workspace=root)


if __name__ == "__main__":
    unittest.main()
