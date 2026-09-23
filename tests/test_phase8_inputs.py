"""P8-01: offline sealed evaluation input loader."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from src.evaluation_inputs import (
    InputValidationError,
    clear_provider_credentials,
    load_and_verify_sealed_inputs,
    write_validation_report,
)
from src.example_contract import WORKSPACE, sha256_file


def _workspace_ready() -> bool:
    return (WORKSPACE / "results" / "phase7" / "raw_evaluation_seal.json").is_file()


@unittest.skipUnless(_workspace_ready(), "requires sealed Phase 7 workspace at /workspace")
class SealedInputLoaderTests(unittest.TestCase):
    def test_load_accepts_seal_offline(self) -> None:
        os.environ["OPENROUTER_API_KEY"] = "sk-should-be-cleared"
        bundle = load_and_verify_sealed_inputs()
        self.assertEqual(len(bundle.bugs), 125)
        self.assertNotIn("OPENROUTER_API_KEY", os.environ)
        self.assertTrue(bundle.validation_report["ok"])
        self.assertEqual(bundle.validation_report["counts"]["methods"]["BM25"], 125)
        self.assertEqual(bundle.validation_report["counts"]["methods"]["Jev"], 113)
        # Labels present for analysis; ranking docs stay private-field-free
        bug = bundle.bug("Cli-13")
        self.assertTrue(bug.positive_classes)
        self.assertIsNone(bug.bm25_ranking.get("positive_classes"))
        self.assertIn("Jsoup-33", bundle.seal["accepted_jev_gaps"])
        self.assertTrue(bundle.bug("Jsoup-33").accepted_jev_gap)
        self.assertIsNone(bundle.bug("Jsoup-33").jev_ranking)

    def test_rejects_tampered_predictions_hash(self) -> None:
        seal_path = WORKSPACE / "results" / "phase7" / "raw_evaluation_seal.json"
        seal = json.loads(seal_path.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            bad_seal = Path(tmp) / "bad_seal.json"
            seal["predictions"]["sha256"] = "0" * 64
            bad_seal.write_text(json.dumps(seal), encoding="utf-8")
            with self.assertRaises(InputValidationError) as ctx:
                load_and_verify_sealed_inputs(seal_path=bad_seal)
            self.assertIn("sha256 mismatch", str(ctx.exception).lower())

    def test_rejects_tampered_ranking_file(self) -> None:
        ranking = WORKSPACE / "results" / "rankings" / "Cli_13.json"
        original = ranking.read_bytes()
        try:
            ranking.write_bytes(original + b"\n")
            with self.assertRaises(InputValidationError) as ctx:
                load_and_verify_sealed_inputs()
            self.assertIn("sha256 mismatch", str(ctx.exception).lower())
        finally:
            ranking.write_bytes(original)

    def test_rejects_wrong_freeze_commit(self) -> None:
        seal_path = WORKSPACE / "results" / "phase7" / "raw_evaluation_seal.json"
        seal = json.loads(seal_path.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            bad_seal = Path(tmp) / "bad_seal.json"
            seal["experiment_commit"] = "f" * 40
            # Keep predictions hash valid so we fail on freeze_lock mismatch
            bad_seal.write_text(json.dumps(seal), encoding="utf-8")
            with self.assertRaises(InputValidationError) as ctx:
                load_and_verify_sealed_inputs(seal_path=bad_seal)
            self.assertIn("freeze_lock", str(ctx.exception).lower())

    def test_write_validation_report(self) -> None:
        bundle = load_and_verify_sealed_inputs()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "input_validation.json"
            written = write_validation_report(bundle, path=out)
            doc = json.loads(written.read_text(encoding="utf-8"))
            self.assertTrue(doc["ok"])
            self.assertEqual(doc["predictions"]["sha256"], bundle.predictions_sha256)
            self.assertEqual(sha256_file(bundle.predictions_path), doc["predictions"]["sha256"])


class CredentialClearTests(unittest.TestCase):
    def test_clear_provider_credentials(self) -> None:
        os.environ["OPENAI_API_KEY"] = "x"
        cleared = clear_provider_credentials()
        self.assertTrue(cleared["OPENAI_API_KEY"])
        self.assertNotIn("OPENAI_API_KEY", os.environ)


if __name__ == "__main__":
    unittest.main()
