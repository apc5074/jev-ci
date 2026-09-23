"""Unit tests for test inventory / trigger parsing / source resolution."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.example_contract import ExampleMismatchError, assert_no_private_fields
from src.extract_tests import (
    RESOLUTION_AMBIGUOUS,
    RESOLUTION_DIRECT,
    RESOLUTION_FALLBACK,
    RESOLUTION_MISSING,
    TestExtractionError,
    outer_test_class,
    parse_test_classes,
    parse_trigger_methods,
    positive_classes_from_triggers,
    resolve_all_test_sources,
    resolve_test_source,
    validate_trigger_consistency,
)


class ParseTestClassesTests(unittest.TestCase):
    def test_sorted_unique(self) -> None:
        raw = "b.B\na.A\n\n"
        self.assertEqual(parse_test_classes(raw), ["a.A", "b.B"])

    def test_rejects_duplicates(self) -> None:
        with self.assertRaises(TestExtractionError):
            parse_test_classes("a.A\na.A\n")

    def test_rejects_empty(self) -> None:
        with self.assertRaises(TestExtractionError):
            parse_test_classes("\n\n")


class TriggerParseTests(unittest.TestCase):
    def test_parse_and_dedupe_methods(self) -> None:
        raw = (
            "org.foo.ATest::testOne\n"
            "org.foo.BTest::testTwo\n"
            "org.foo.ATest::testOne\n"
        )
        methods = parse_trigger_methods(raw)
        self.assertEqual(
            methods,
            ["org.foo.ATest::testOne", "org.foo.BTest::testTwo"],
        )

    def test_positive_classes_sorted(self) -> None:
        methods = [
            "org.foo.BTest::t",
            "org.foo.ATest::t",
            "org.foo.BTest::u",
        ]
        self.assertEqual(
            positive_classes_from_triggers(methods),
            ["org.foo.ATest", "org.foo.BTest"],
        )

    def test_rejects_malformed_trigger(self) -> None:
        with self.assertRaises(TestExtractionError):
            parse_trigger_methods("org.foo.ATest\n")
        with self.assertRaises(TestExtractionError):
            parse_trigger_methods("::testOnly\n")


class ConsistencyTests(unittest.TestCase):
    def test_ok_when_all_present(self) -> None:
        report = validate_trigger_consistency(
            test_classes=["a.A", "b.B", "c.C"],
            positive_classes=["a.A", "c.C"],
        )
        self.assertTrue(report["all_positives_in_inventory"])
        self.assertEqual(report["anomalies"], [])

    def test_missing_positive_is_hard_error(self) -> None:
        with self.assertRaises(TestExtractionError) as ctx:
            validate_trigger_consistency(
                test_classes=["a.A"],
                positive_classes=["a.A", "missing.X"],
            )
        self.assertIn("silently add", str(ctx.exception))

    def test_empty_positives_rejected(self) -> None:
        with self.assertRaises(TestExtractionError):
            validate_trigger_consistency(
                test_classes=["a.A"],
                positive_classes=[],
            )


class VisibilityTests(unittest.TestCase):
    def test_inventory_may_not_hold_private_fields(self) -> None:
        with self.assertRaises(ExampleMismatchError):
            assert_no_private_fields(
                {"test_classes": ["a.A"], "positive_classes": ["a.A"]},
                context="inventory",
            )


class SourceResolutionTests(unittest.TestCase):
    def _write(self, root: Path, rel: str, body: str = "class X {}\n") -> None:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")

    def test_nested_maps_to_outer(self) -> None:
        self.assertEqual(
            outer_test_class("org.foo.FooTest$Nested"),
            "org.foo.FooTest",
        )

    def test_direct_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rel = "src/test/java/org/foo/FooTest.java"
            self._write(root, rel, "line1\nline2\n")
            entry = resolve_test_source(
                "org.foo.FooTest",
                checkout_root=root,
                dir_src_tests="src/test/java",
            )
            self.assertEqual(entry["resolution"], RESOLUTION_DIRECT)
            self.assertEqual(entry["source_file"], rel)
            self.assertFalse(entry["source_missing"])
            self.assertTrue(entry["readable"])
            self.assertEqual(entry["line_count"], 2)

    def test_nested_uses_outer_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rel = "src/test/java/org/foo/FooTest.java"
            self._write(root, rel)
            entry = resolve_test_source(
                "org.foo.FooTest$Inner",
                checkout_root=root,
                dir_src_tests="src/test/java",
            )
            self.assertEqual(entry["resolution"], RESOLUTION_DIRECT)
            self.assertEqual(entry["source_file"], rel)
            self.assertEqual(entry["outer_class"], "org.foo.FooTest")

    def test_fallback_with_package_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Direct path absent; recursive search + package evidence picks one.
            found = "src/test/java/legacy/org/foo/BarTest.java"
            distractor = "src/test/java/other/BarTest.java"
            self._write(root, found)
            self._write(root, distractor)
            entry = resolve_test_source(
                "org.foo.BarTest",
                checkout_root=root,
                dir_src_tests="src/test/java",
            )
            self.assertEqual(entry["resolution"], RESOLUTION_FALLBACK)
            self.assertEqual(entry["source_file"], found)
            self.assertFalse(entry["source_missing"])

    def test_ambiguous_does_not_pick(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = "src/test/java/a/DupTest.java"
            b = "src/test/java/b/DupTest.java"
            self._write(root, a)
            self._write(root, b)
            entry = resolve_test_source(
                "org.missing.DupTest",
                checkout_root=root,
                dir_src_tests="src/test/java",
            )
            self.assertEqual(entry["resolution"], RESOLUTION_AMBIGUOUS)
            self.assertTrue(entry["ambiguous"])
            self.assertTrue(entry["source_missing"])
            self.assertIsNone(entry["source_file"])
            self.assertEqual(entry["candidates"], [a, b])

    def test_missing_retained(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src/test/java").mkdir(parents=True)
            entry = resolve_test_source(
                "org.foo.GoneTest",
                checkout_root=root,
                dir_src_tests="src/test/java",
            )
            self.assertEqual(entry["resolution"], RESOLUTION_MISSING)
            self.assertTrue(entry["source_missing"])
            self.assertEqual(entry["test_class"], "org.foo.GoneTest")

    def test_resolve_all_keeps_every_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write(root, "src/test/java/org/foo/ATest.java")
            classes = ["org.foo.ATest", "org.foo.MissingTest"]
            source_map, counts = resolve_all_test_sources(
                classes,
                checkout_root=root,
                dir_src_tests="src/test/java",
            )
            self.assertEqual([e["test_class"] for e in source_map], classes)
            self.assertEqual(counts["source_resolved"], 1)
            self.assertEqual(counts["source_missing"], 1)


if __name__ == "__main__":
    unittest.main()
