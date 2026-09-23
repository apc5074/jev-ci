"""Unit tests for prepare_dataset split gating (no Defects4J checkouts)."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

from src.example_contract import ExampleContractError


def _load_prepare_dataset():
    path = Path(__file__).resolve().parents[1] / "scripts" / "prepare_dataset.py"
    spec = importlib.util.spec_from_file_location("prepare_dataset", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


prepare_dataset = _load_prepare_dataset()


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
        ids = prepare_dataset.resolve_target_ids(
            split="development",
            manifest=_manifest(),
            allow_evaluation=False,
            only=None,
        )
        self.assertEqual(len(ids), 25)

    def test_evaluation_requires_flag(self) -> None:
        with self.assertRaises(ExampleContractError):
            prepare_dataset.resolve_target_ids(
                split="evaluation",
                manifest=_manifest(),
                allow_evaluation=False,
                only=None,
            )

    def test_evaluation_with_flag(self) -> None:
        ids = prepare_dataset.resolve_target_ids(
            split="evaluation",
            manifest=_manifest(),
            allow_evaluation=True,
            only=None,
        )
        self.assertEqual([x.qualified for x in ids], ["Cli-99"])

    def test_only_must_be_in_split(self) -> None:
        with self.assertRaises(ExampleContractError):
            prepare_dataset.resolve_target_ids(
                split="development",
                manifest=_manifest(),
                allow_evaluation=False,
                only=["Cli-99"],
            )


if __name__ == "__main__":
    unittest.main()
