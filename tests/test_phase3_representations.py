"""Unit tests for tokenizer, BM25, and test-source compaction."""

from __future__ import annotations

import unittest

from src.bm25 import bm25_idf, bm25_scores
from src.representations import (
    SOURCE_MISSING_PLACEHOLDER,
    build_representation_text,
    compact_source_lines,
    concat_windows_dedupe,
    make_windows,
    select_top_windows,
)
from src.tokenize import tokenize


class TokenizerTests(unittest.TestCase):
    def test_parse_http_response_example(self) -> None:
        self.assertEqual(
            tokenize("parseHTTPResponse_v2"),
            ["parse", "http", "response", "v2"],
        )

    def test_discards_singletons_keeps_keywords(self) -> None:
        # "a" dropped; "if" / "for" kept (no stopword/keyword removal).
        tokens = tokenize("a if for HTTP")
        self.assertEqual(tokens, ["if", "for", "http"])

    def test_empty(self) -> None:
        self.assertEqual(tokenize(""), [])
        self.assertEqual(tokenize("   "), [])


class BM25Tests(unittest.TestCase):
    def test_idf_nonnegative(self) -> None:
        self.assertGreater(bm25_idf(n_docs=10, df=1), 0.0)
        self.assertGreater(bm25_idf(n_docs=10, df=0), 0.0)

    def test_relevant_doc_ranks_higher(self) -> None:
        query = tokenize("parse option group")
        docs = [
            tokenize("unrelated math vector"),
            tokenize("parse option group selected"),
            tokenize("option only"),
        ]
        scores = bm25_scores(query, docs)
        self.assertEqual(len(scores), 3)
        self.assertGreater(scores[1], scores[0])
        self.assertGreater(scores[1], scores[2])

    def test_empty_query_zeros(self) -> None:
        self.assertEqual(bm25_scores([], [["a"], ["b"]]), [0.0, 0.0])


class WindowTests(unittest.TestCase):
    def test_make_windows_stride_and_tail(self) -> None:
        lines = [str(i) for i in range(200)]
        windows = make_windows(lines, size=80, stride=60)
        starts = [w[0] for w in windows]
        self.assertEqual(starts[0], 0)
        self.assertEqual(starts[1], 60)
        self.assertLessEqual(windows[-1][1], 200)
        self.assertEqual(windows[-1][1], 200)

    def test_short_file_full_mode(self) -> None:
        lines = [f"line{i}" for i in range(10)]
        out, meta = compact_source_lines(lines, query_tokens=["line"])
        self.assertEqual(meta["mode"], "full")
        self.assertEqual(out, lines)

    def test_long_file_top3_order_and_dedupe(self) -> None:
        # 300 lines: windows at 0, 60, 120, 180, 240.
        lines = []
        for i in range(300):
            if 120 <= i < 200:
                lines.append(f"parse option group {i}")
            else:
                lines.append(f"zzz unrelated {i}")
        out, meta = compact_source_lines(
            lines, query_tokens=tokenize("parse option group")
        )
        self.assertEqual(meta["mode"], "windows")
        self.assertEqual(len(meta["windows_selected"]), 3)
        starts = [s for s, _e in meta["windows_selected"]]
        self.assertEqual(starts, sorted(starts))
        # Selected window starts should prefer the region with query terms.
        self.assertTrue(any(s <= 120 < e for s, e in meta["windows_selected"]))
        # Overlap dedupe: consecutive selected windows should not repeat lines.
        windows = make_windows(lines)
        scores = [0.0] * len(windows)
        # Force select overlapping windows 0 and 1.
        scores[0] = 10.0
        scores[1] = 9.0
        scores[2] = 8.0
        selected = select_top_windows(windows, scores, top_k=3)
        deduped = concat_windows_dedupe(selected)
        # Cover lines [0, end) without duplicating the 20-line overlaps.
        self.assertEqual(len(deduped), selected[-1][1] - selected[0][0])

    def test_tie_break_prefers_earlier_window(self) -> None:
        windows = [(0, 2, ["a"]), (2, 4, ["b"]), (4, 6, ["c"])]
        scores = [1.0, 1.0, 1.0]
        selected = select_top_windows(windows, scores, top_k=2)
        self.assertEqual([s for s, _e, _l, _sc in selected], [0, 2])

    def test_missing_representation_convention(self) -> None:
        text = build_representation_text(
            test_class="org.foo.BarTest",
            source_file=None,
            test_source="",
            source_missing=True,
        )
        self.assertIn("TEST CLASS:\norg.foo.BarTest\n", text)
        self.assertIn(f"SOURCE FILE:\n{SOURCE_MISSING_PLACEHOLDER}\n", text)
        self.assertTrue(text.endswith("TEST SOURCE:\n"))


if __name__ == "__main__":
    unittest.main()
