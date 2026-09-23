"""P6-01: development baseline helpers."""

from __future__ import annotations

import unittest
from pathlib import Path

from src.development_baseline import ACCEPTED_JEV_GAPS, render_baseline_markdown


class DevelopmentBaselineTests(unittest.TestCase):
    def test_accepted_gap_documented(self) -> None:
        self.assertIn(
            ("Jsoup-70", "org.jsoup.integration.ConnectTest"),
            ACCEPTED_JEV_GAPS,
        )

    def test_markdown_render_smoke(self) -> None:
        md = render_baseline_markdown(
            {
                "generated_at": "2026-09-23T00:00:00+00:00",
                "git": {"commit_short": "abc", "branch": "main", "dirty": False},
                "frozen_for_baseline": {
                    "jev_prompt_version": "jev-would_detect_regression-v1",
                    "gpt_prompt_version": "gpt-would_detect_regression-v1",
                    "jev_model_id": "typesafe/jev-1.13",
                    "jev_revision_count": 0,
                },
                "accepted_gaps": [
                    {
                        "qualified_id": "Jsoup-70",
                        "test_class": "org.jsoup.integration.ConnectTest",
                        "system": "Jev",
                        "reason": "test",
                    }
                ],
                "summary": {
                    "ok": 25,
                    "count": 25,
                    "with_accepted_gap": 1,
                    "bm25_candidate_recall": 1.0,
                    "mean_bm25_first_trigger_rank": 2.0,
                },
                "bugs": [],
            }
        )
        self.assertIn("P6-01", md)
        self.assertIn("Jsoup-70", md)


@unittest.skipUnless(
    Path("/workspace/results/phase6/development_baseline.json").is_file(),
    "baseline artifact required",
)
class LiveBaselineTests(unittest.TestCase):
    def test_baseline_marks_twenty_five_ok(self) -> None:
        import json

        doc = json.loads(
            Path("/workspace/results/phase6/development_baseline.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertTrue(doc.get("ok"))
        self.assertEqual(doc["summary"]["ok"], 25)
        self.assertEqual(doc["summary"]["with_accepted_gap"], 1)


if __name__ == "__main__":
    unittest.main()
