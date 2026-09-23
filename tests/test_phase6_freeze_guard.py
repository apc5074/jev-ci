"""P6-06/P6-07: freeze lock blocks evaluation until validated."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.freeze_guard import (
    REQUIRED_TAG,
    assert_evaluation_allowed,
    evaluation_is_unlocked,
    FreezeGuardError,
)


class FreezeGuardTests(unittest.TestCase):
    def test_missing_lock_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "freeze_lock.json"
            self.assertFalse(evaluation_is_unlocked(path=path))
            with self.assertRaises(FreezeGuardError):
                assert_evaluation_allowed(path=path)

    def test_valid_lock_unlocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "freeze_lock.json"
            path.write_text(
                json.dumps(
                    {
                        "tag": REQUIRED_TAG,
                        "commit_sha": "a" * 40,
                        "validated": True,
                    }
                ),
                encoding="utf-8",
            )
            self.assertTrue(evaluation_is_unlocked(path=path))
            doc = assert_evaluation_allowed(path=path)
            self.assertEqual(doc["commit_sha"], "a" * 40)

    def test_invalid_tag_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "freeze_lock.json"
            path.write_text(
                json.dumps(
                    {
                        "tag": "wrong-tag",
                        "commit_sha": "a" * 40,
                        "validated": True,
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(FreezeGuardError):
                assert_evaluation_allowed(path=path)


if __name__ == "__main__":
    unittest.main()
