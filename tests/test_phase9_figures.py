"""P9-02: publish final figures under results/figures/."""

from __future__ import annotations

import unittest
from pathlib import Path

from src.example_contract import WORKSPACE, read_json, sha256_file
from src.phase9_figures import FIGURE_MAP, publish_figures, verify_figure_data_against_cohort


@unittest.skipUnless(
    (WORKSPACE / "results" / "phase8" / "figure_data.json").is_file(),
    "requires Phase 8 figure_data",
)
class Phase9FiguresTests(unittest.TestCase):
    def test_figure_data_matches_cohort(self) -> None:
        errors = verify_figure_data_against_cohort(workspace=WORKSPACE)
        self.assertEqual(errors, [])

    def test_publish_copies_and_captions(self) -> None:
        manifest = publish_figures()
        self.assertTrue(manifest["ok"])
        self.assertEqual(manifest["n_evaluation_bugs"], 113)
        out = WORKSPACE / "results" / "figures"
        for _src, dst_name in FIGURE_MAP:
            path = out / dst_name
            self.assertTrue(path.is_file(), msg=dst_name)
            self.assertGreater(path.stat().st_size, 2000)
        captions = (out / "captions.md").read_text(encoding="utf-8")
        self.assertIn("Figure 1", captions)
        self.assertIn("Figure 4", captions)
        self.assertIn("n = 113", captions)
        self.assertIn("effective prepaid", captions.lower())
        self.assertIn("Jsoup n=13", captions)

        # Published bytes match Phase 8 sources
        for src_name, dst_name in FIGURE_MAP:
            src = WORKSPACE / "results" / "phase8" / "figures" / src_name
            dst = out / dst_name
            self.assertEqual(sha256_file(src), sha256_file(dst), msg=dst_name)

        man_path = WORKSPACE / "results" / "phase9" / "figures_manifest.json"
        self.assertTrue(man_path.is_file())
        doc = read_json(man_path)
        self.assertEqual(len(doc["figures"]), 4)


if __name__ == "__main__":
    unittest.main()
