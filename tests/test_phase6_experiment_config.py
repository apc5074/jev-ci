"""P6-04: locked experiment configuration."""

from __future__ import annotations

import unittest
from pathlib import Path

from src.experiment_config import (
    EXPERIMENT_JSON,
    EXPERIMENT_YAML,
    ExperimentConfigError,
    load_experiment_config,
)


class ExperimentConfigTests(unittest.TestCase):
    @unittest.skipUnless(EXPERIMENT_JSON.is_file(), "experiment.json required")
    def test_load_locked_config(self) -> None:
        doc = load_experiment_config()
        self.assertEqual(doc["systems"], ["Random", "BM25", "Embedding", "Jev", "GPT-Nano"])
        self.assertEqual(doc["jev"]["prompt_decision"], "retain_original")
        self.assertEqual(doc["outcomes"]["bootstrap_samples"], 10000)
        self.assertEqual(doc["bm25"]["k_cap"], 200)
        self.assertTrue(EXPERIMENT_YAML.is_file())
        # YAML mentions primary metric
        text = EXPERIMENT_YAML.read_text(encoding="utf-8")
        self.assertIn("FDR@10%", text)
        self.assertIn("effective_prepaid_credits_usd", text)

    def test_readme_carries_freeze_essentials(self) -> None:
        path = Path("/workspace/README.md")
        if not path.is_file():
            path = Path("README.md")
        self.assertTrue(path.is_file())
        text = path.read_text(encoding="utf-8").lower()
        for needle in (
            "fdr@10%",
            "experiment.yaml",
            "≥5 pp",
            "defects4j",
            "bm25 top-200",
            "experiment-v1",
        ):
            self.assertIn(needle, text)

    def test_missing_path_fails(self) -> None:
        with self.assertRaises(ExperimentConfigError):
            load_experiment_config(path=Path("/tmp/no-such-experiment.json"))


if __name__ == "__main__":
    unittest.main()
