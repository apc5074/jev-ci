"""P7-01: evaluation preflight gate."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.evaluation_preflight import (
    PreflightError,
    assert_evaluation_run_ready,
    check_evaluation_namespace_empty,
)
from src.freeze_guard import REQUIRED_TAG, FreezeGuardError


class EvaluationPreflightTests(unittest.TestCase):
    def test_namespace_empty_ok(self) -> None:
        report = check_evaluation_namespace_empty(["Cli-13", "Lang-5"])
        self.assertTrue(report["ok"])
        self.assertEqual(report["hit_count"], 0)

    def test_assert_requires_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lock = Path(tmp) / "freeze_lock.json"
            lock.write_text(
                json.dumps(
                    {
                        "tag": REQUIRED_TAG,
                        "commit_sha": "a" * 40,
                        "validated": True,
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch(
                "src.evaluation_preflight.assert_evaluation_allowed",
                return_value={
                    "tag": REQUIRED_TAG,
                    "commit_sha": "a" * 40,
                    "validated": True,
                },
            ):
                with self.assertRaises(PreflightError):
                    assert_evaluation_run_ready(path=Path(tmp) / "missing.json")


if __name__ == "__main__":
    unittest.main()
