"""Unit tests for run_candidates split gating (no Defects4J required)."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

from src.example_contract import ExampleContractError


def _load_run_candidates():
    path = Path(__file__).resolve().parents[1] / "scripts" / "run_candidates.py"
    spec = importlib.util.spec_from_file_location("run_candidates", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


run_candidates = _load_run_candidates()


def _manifest() -> dict:
    return {
        "development_bug_ids": (
            [f"Cli-{i}" for i in range(1, 6)]
            + [f"Lang-{i}" for i in range(1, 6)]
            + [f"Math-{i}" for i in range(1, 6)]
            + [f"Jsoup-{i}" for i in range(1, 6)]
            + [f"JacksonDatabind-{i}" for i in range(1, 6)]
        ),
        "evaluation_bug_ids": ["Cli-99"],
        "selection_seed": 20260922,
        "defects4j_commit": "abc",
    }


class SplitGateTests(unittest.TestCase):
    def test_development_returns_25(self) -> None:
        ids = run_candidates.resolve_target_ids(
            split="development",
            manifest=_manifest(),
            allow_evaluation=False,
            only=None,
        )
        self.assertEqual(len(ids), 25)

    def test_evaluation_requires_flag(self) -> None:
        with self.assertRaises(ExampleContractError):
            run_candidates.resolve_target_ids(
                split="evaluation",
                manifest=_manifest(),
                allow_evaluation=False,
                only=None,
            )

    def test_evaluation_with_flag(self) -> None:
        ids = run_candidates.resolve_target_ids(
            split="evaluation",
            manifest=_manifest(),
            allow_evaluation=True,
            only=None,
        )
        self.assertEqual([x.qualified for x in ids], ["Cli-99"])

    def test_only_must_be_in_split(self) -> None:
        with self.assertRaises(ExampleContractError):
            run_candidates.resolve_target_ids(
                split="development",
                manifest=_manifest(),
                allow_evaluation=False,
                only=["Cli-99"],
            )

    def test_summary_omits_trigger_fields(self) -> None:
        counts = run_candidates._summary_counts(
            [
                {
                    "qualified_id": "Cli-1",
                    "outcome": "skipped_reuse",
                    "N": 10,
                    "K": 10,
                    "source_missing": 0,
                },
                {
                    "qualified_id": "Cli-2",
                    "outcome": "failed",
                    "error": "boom",
                },
            ]
        )
        self.assertEqual(counts["completed"], 1)
        self.assertEqual(counts["failed"], 1)
        self.assertEqual(counts["failed_ids"], ["Cli-2"])
        self.assertNotIn("positive_classes", counts)
        self.assertNotIn("trigger_methods", counts)


if __name__ == "__main__":
    unittest.main()
