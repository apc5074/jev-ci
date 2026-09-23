"""Phase 3 integrity tests: fixtures + live Cli-30 / full-audit hooks."""

from __future__ import annotations

import os
import unittest
from pathlib import Path

from src.audit_phase3 import (
    audit_model_visible_text,
    find_pipeline_leaks,
    verify_patch_direction_sample,
)
from src.example_contract import WORKSPACE


class LeakageFixtureTests(unittest.TestCase):
    def test_pipeline_path_leak_detected(self) -> None:
        hits = find_pipeline_leaks("see checkouts/fixed/Foo.java")
        self.assertTrue(hits)

    def test_authentic_fixed_word_not_flagged(self) -> None:
        # Literal "fixed" in Java-like source is not a pipeline leak by itself.
        hits = find_pipeline_leaks("    // options were fixed in prior release\n")
        self.assertEqual(hits, [])

    def test_trigger_method_in_model_state(self) -> None:
        problems = audit_model_visible_text(
            "TEST CLASS:\nFoo\n\nTEST SOURCE:\norg.foo.BarTest::testX\n",
            qualified_id="Cli-30",
            trigger_methods=["org.foo.BarTest::testX"],
            context="rep",
            kind="test",
        )
        self.assertTrue(any("trigger method" in p for p in problems))

    def test_bug_id_in_envelope(self) -> None:
        problems = audit_model_visible_text(
            "TEST CLASS:\nCli-30\n\nSOURCE FILE:\nx\n\nTEST SOURCE:\n",
            qualified_id="Cli-30",
            trigger_methods=[],
            context="rep",
            kind="test",
        )
        self.assertTrue(any("bug id" in p for p in problems))

    def test_defects4j_in_source_body_not_flagged(self) -> None:
        problems = audit_model_visible_text(
            "TEST CLASS:\nFoo\n\nSOURCE FILE:\na.java\n\nTEST SOURCE:\n"
            "// Defects4J note and expected result\n",
            qualified_id="Cli-30",
            trigger_methods=[],
            context="rep",
            kind="test",
        )
        self.assertEqual(problems, [])


@unittest.skipUnless(
    (WORKSPACE / "data" / "bugs" / "Cli_30" / "example.json").is_file()
    or (Path("data/bugs/Cli_30/example.json")).is_file(),
    "Cli-30 example artifacts not present",
)
class LiveCli30Tests(unittest.TestCase):
    def test_patch_direction_sample(self) -> None:
        verify_patch_direction_sample("Cli-30")


@unittest.skipUnless(
    os.environ.get("JEV_RUN_FULL_PHASE3_AUDIT") == "1",
    "set JEV_RUN_FULL_PHASE3_AUDIT=1 to run the 25-example audit in unittest",
)
class FullAuditTests(unittest.TestCase):
    def test_audit_development_set(self) -> None:
        from src.audit_phase3 import audit_development_set

        report = audit_development_set()
        self.assertTrue(report["ok"], report.get("failed_ids"))


if __name__ == "__main__":
    unittest.main()
