"""Phase 4 P4-06: ranking/shortlist integrity and development recall."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.audit_phase4 import assert_ranking_sorted, AuditError
from src.candidates import shortlist_content_hash

_REPO = Path(__file__).resolve().parents[1]
_DATA = _REPO / "data"
_MANIFEST = _DATA / "manifest.json"


class RankingOrderTests(unittest.TestCase):
    def test_accepts_sorted(self) -> None:
        assert_ranking_sorted(
            [
                {"test_class": "b.B", "score": 2.0, "rank": 1},
                {"test_class": "a.A", "score": 1.0, "rank": 2},
                {"test_class": "c.C", "score": 1.0, "rank": 3},
            ]
        )

    def test_rejects_bad_order(self) -> None:
        with self.assertRaises(AuditError):
            assert_ranking_sorted(
                [
                    {"test_class": "a.A", "score": 1.0, "rank": 1},
                    {"test_class": "b.B", "score": 2.0, "rank": 2},
                ]
            )

    def test_tie_break_fqcn(self) -> None:
        # Equal scores must be ascending FQCN.
        with self.assertRaises(AuditError):
            assert_ranking_sorted(
                [
                    {"test_class": "b.B", "score": 1.0, "rank": 1},
                    {"test_class": "a.A", "score": 1.0, "rank": 2},
                ]
            )


class ShortlistHashContractTests(unittest.TestCase):
    def test_phase5_hash_stable(self) -> None:
        ids = ["a.A", "b.B"]
        self.assertEqual(shortlist_content_hash(ids), shortlist_content_hash(ids))
        self.assertNotEqual(
            shortlist_content_hash(ids),
            shortlist_content_hash(["b.B", "a.A"]),
        )


@unittest.skipUnless(
    _MANIFEST.is_file()
    and (_DATA / "candidates" / "Cli_30.json").is_file()
    and (_REPO / "results" / "rankings" / "Cli_30.json").is_file(),
    "development candidates/rankings required",
)
class LivePhase4AuditTests(unittest.TestCase):
    def test_audit_development_set(self) -> None:
        from src.audit_phase4 import audit_development_set
        from src.candidates import load_candidates

        report = audit_development_set(
            data_root=_DATA,
            results_root=_REPO / "results",
            manifest_path=_MANIFEST,
        )
        self.assertTrue(report["ok"], report.get("failed_ids"))
        self.assertEqual(report["counts"]["passed"], 25)
        self.assertEqual(
            report["candidate_trigger_recall_at_k"]["bugs_with_trigger_in_top_k"],
            25,
        )
        # Phase 5 reader returns the same ordered IDs for both rerankers.
        c = load_candidates("Cli-30", data_root=_DATA)
        again = load_candidates(
            "Cli-30",
            data_root=_DATA,
            require_hash=c["shortlist_sha256"],
        )
        self.assertEqual(c["candidate_ids"], again["candidate_ids"])


if __name__ == "__main__":
    unittest.main()
