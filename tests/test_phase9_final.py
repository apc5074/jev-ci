"""P9-07: final Phase 9 closeout."""

from __future__ import annotations

import unittest

from src.example_contract import WORKSPACE, read_json
from src.phase9_final import publish_final


@unittest.skipUnless(
    (WORKSPACE / "results" / "phase9" / "reproduction_record.json").is_file(),
    "requires P9-06 reproduction record",
)
class Phase9FinalTests(unittest.TestCase):
    def test_publish_final(self) -> None:
        doc = publish_final()
        self.assertTrue(doc["ok"])
        self.assertTrue(doc["phase_complete"])
        self.assertTrue(doc["consistency"]["ok"])
        path = WORKSPACE / "results" / "phase9" / "final_index.json"
        finding = WORKSPACE / "results" / "phase9" / "main_finding.md"
        self.assertTrue(path.is_file())
        self.assertTrue(finding.is_file())
        loaded = read_json(path)
        self.assertIn("artifact_index", loaded)
        self.assertIn("metrics", loaded["artifact_index"])
        text = finding.read_text(encoding="utf-8")
        self.assertIn("10% test-class", text)
        self.assertIn("does **not** claim", text)


if __name__ == "__main__":
    unittest.main()
