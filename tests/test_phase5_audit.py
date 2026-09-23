"""P5-09: Phase 5 development audit helpers."""

from __future__ import annotations

import unittest
from pathlib import Path

from src.audit_phase5 import (
    REQUIRED_SEMANTIC,
    _assert_permutation,
    summarize_usage_ledger,
)


class AuditHelperTests(unittest.TestCase):
    def test_permutation_helper(self) -> None:
        ids = ["a.A", "b.B", "c.C"]
        _assert_permutation(ids, expected=set(ids), label="ok")
        with self.assertRaises(Exception):
            _assert_permutation(["a.A", "a.A"], expected={"a.A"}, label="dup")

    def test_required_semantic_methods(self) -> None:
        self.assertEqual(REQUIRED_SEMANTIC, ("Jev", "GPT-Nano"))

    def test_usage_ledger_summary_shape(self) -> None:
        summary = summarize_usage_ledger(
            Path("/workspace/results/usage_ledger.jsonl")
            if Path("/workspace/results/usage_ledger.jsonl").is_file()
            else Path("results/usage_ledger.jsonl")
        )
        self.assertIn("present", summary)
        self.assertIn("rows", summary)

    def test_usage_ledger_reads_flat_cost_fields(self) -> None:
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.jsonl"
            path.write_text(
                json.dumps(
                    {
                        "kind": "jev",
                        "input_tokens": 100,
                        "output_tokens": 0,
                        "list_price_inference_usd": 0.25,
                        "platform_fee_usd": 0.05,
                        "effective_prepaid_credits_usd": 0.30,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            summary = summarize_usage_ledger(path)
            bucket = summary["by_kind"]["jev"]
            self.assertAlmostEqual(bucket["list_price_usd"], 0.25)
            self.assertAlmostEqual(bucket["platform_fee_usd"], 0.05)
            self.assertAlmostEqual(bucket["effective_prepaid_credits_usd"], 0.30)


@unittest.skipUnless(
    Path("/workspace/results/semantic/jev/Cli_30.json").is_file()
    and Path("/workspace/results/semantic/gpt_nano/Cli_30.json").is_file(),
    "Cli-30 semantic rankings required",
)
class Cli30AuditSmokeTests(unittest.TestCase):
    def test_audit_one_example(self) -> None:
        from src.audit_phase5 import audit_one_example

        row = audit_one_example("Cli-30")
        self.assertTrue(row["ok"])
        self.assertEqual(len(row["semantic"]), 2)
        self.assertGreater(row["N"], 0)
        self.assertEqual(row["K"], row["N"])  # Cli-30 is fully shortlisted


if __name__ == "__main__":
    unittest.main()
