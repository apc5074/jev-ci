"""P9-06: offline reproduction record."""

from __future__ import annotations

import unittest
from pathlib import Path

from src.example_contract import WORKSPACE, read_json
from src.phase9_reproduction import (
    INVENTORY_REQUIRED,
    STABLE_COMPARE,
    build_inventory,
    reconcile_report_claims,
    snapshot_hashes,
)


@unittest.skipUnless(
    (WORKSPACE / "results" / "metrics.csv").is_file(),
    "requires sealed metrics",
)
class Phase9ReproductionUnitTests(unittest.TestCase):
    def test_inventory_complete(self) -> None:
        inv = build_inventory(workspace=WORKSPACE)
        self.assertTrue(inv["ok"], msg=inv.get("missing"))
        self.assertEqual(len(INVENTORY_REQUIRED), len(inv["required_files"]))

    def test_reconcile_report(self) -> None:
        rec = reconcile_report_claims(workspace=WORKSPACE)
        self.assertTrue(rec["ok"], msg=rec.get("text_checks"))
        self.assertEqual(rec["claims"]["jev_fdr_at_10pct"], 0.9558)
        self.assertEqual(rec["claims"]["delta_pp"], 22.1)
        self.assertTrue(rec["claims"]["practical_success"])

    def test_stable_paths_exist(self) -> None:
        snap = snapshot_hashes(STABLE_COMPARE, workspace=WORKSPACE)
        for rel, meta in snap.items():
            self.assertTrue(meta["exists"], msg=rel)


@unittest.skipUnless(
    (WORKSPACE / "results" / "phase7" / "raw_evaluation_seal.json").is_file(),
    "requires Phase 7 seal",
)
class Phase9ReproductionIntegrationTests(unittest.TestCase):
    def test_publish_reproduction_offline(self) -> None:
        # Heavy: re-runs evaluate.py path. Keep as optional via env if needed;
        # here we only assert the module import path works when seal exists.
        from src.phase9_reproduction import publish_reproduction

        doc = publish_reproduction()
        self.assertTrue(doc["ok"])
        path = WORKSPACE / "results" / "phase9" / "reproduction_record.json"
        self.assertTrue(path.is_file())
        loaded = read_json(path)
        self.assertTrue(loaded["hash_comparison"]["byte_identical"])
        self.assertEqual(loaded["paid_requests"], 0)
        self.assertTrue(loaded["metrics_split_evaluation_only"])


if __name__ == "__main__":
    unittest.main()
