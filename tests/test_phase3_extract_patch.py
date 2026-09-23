"""Unit tests for patch truncation and path helpers (no Defects4J required)."""

from __future__ import annotations

import unittest

from src.extract_patch import (
    PATCH_TRUNCATION_MARKER,
    REPRESENTATION_CHAR_CAP,
    build_representation,
    fqcn_to_relative_java,
    outer_class_name,
    parse_modified_classes,
    truncate_to_cap,
    unified_diff_for_file,
)


class TruncationTests(unittest.TestCase):
    def test_short_text_unchanged(self) -> None:
        text = "hello"
        out, truncated = truncate_to_cap(text)
        self.assertEqual(out, text)
        self.assertFalse(truncated)

    def test_exact_cap_unchanged(self) -> None:
        text = "a" * REPRESENTATION_CHAR_CAP
        out, truncated = truncate_to_cap(text)
        self.assertEqual(out, text)
        self.assertFalse(truncated)

    def test_over_cap_reserves_marker(self) -> None:
        text = "a" * (REPRESENTATION_CHAR_CAP + 100) + "b" * 50
        out, truncated = truncate_to_cap(text)
        self.assertTrue(truncated)
        self.assertEqual(len(out), REPRESENTATION_CHAR_CAP)
        self.assertIn(PATCH_TRUNCATION_MARKER, out)
        marker_len = len(PATCH_TRUNCATION_MARKER)
        remaining = REPRESENTATION_CHAR_CAP - marker_len
        prefix = remaining // 2
        suffix = remaining - prefix
        self.assertEqual(out[:prefix], text[:prefix])
        self.assertEqual(out[-suffix:], text[-suffix:])
        # Naive 6000+6000+marker would exceed the cap.
        self.assertGreater(6000 + marker_len + 6000, REPRESENTATION_CHAR_CAP)

    def test_equal_budgets_differ_by_at_most_one(self) -> None:
        text = "x" * (REPRESENTATION_CHAR_CAP + 1)
        out, _ = truncate_to_cap(text)
        left, _, right = out.partition(PATCH_TRUNCATION_MARKER)
        self.assertLessEqual(abs(len(left) - len(right)), 1)


class PathHelperTests(unittest.TestCase):
    def test_nested_outer_class(self) -> None:
        self.assertEqual(outer_class_name("pkg.Foo$Bar"), "pkg.Foo")
        self.assertEqual(
            fqcn_to_relative_java("org.apache.commons.cli.DefaultParser"),
            "org/apache/commons/cli/DefaultParser.java",
        )

    def test_parse_modified_classes_sorted_unique(self) -> None:
        raw = "b.B\na.A\nb.B\n\n"
        self.assertEqual(parse_modified_classes(raw), ["a.A", "b.B"])


class DiffDirectionTests(unittest.TestCase):
    def test_fixed_removed_buggy_added(self) -> None:
        diff = unified_diff_for_file(
            header_path="src/Main.java",
            fixed_lines=["int x = 1;\n"],
            buggy_lines=["int x = 2;\n"],
        )
        self.assertIn("--- src/Main.java\n", diff)
        self.assertIn("+++ src/Main.java\n", diff)
        self.assertNotIn("fixed/", diff)
        self.assertNotIn("buggy/", diff)
        self.assertIn("-int x = 1;\n", diff)
        self.assertIn("+int x = 2;\n", diff)
        # Body lines must be newline-terminated (not collapsed onto one line).
        self.assertGreaterEqual(diff.count("\n"), 5)

    def test_representation_shape(self) -> None:
        text = build_representation(
            modified_files=["a/A.java"],
            modified_classes=["a.A"],
            full_diff="--- a/A.java\n+++ a/A.java\n",
        )
        self.assertTrue(text.startswith("MODIFIED FILES:\n"))
        self.assertIn("MODIFIED CLASSES:\n", text)
        self.assertIn("PROPOSED CODE CHANGE:\n", text)


if __name__ == "__main__":
    unittest.main()
