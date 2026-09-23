"""Phase 4 P4-03: full-corpus BM25 scoring and suite ranking."""

from __future__ import annotations

import json
import math
import unittest
from pathlib import Path

from src.bm25 import BM25_B, BM25_K1, bm25_idf, bm25_scores
from src.ranking import rank_suite, rank_tokenized_corpus

_REPO = Path(__file__).resolve().parents[1]
_DATA = _REPO / "data"
_MANIFEST_PATH = _DATA / "manifest.json"


def _load_manifest() -> dict:
    with _MANIFEST_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


class HandComputedToyCorpusTests(unittest.TestCase):
    """Three-doc corpus with a hand-derived score for term ``alpha``."""

    def test_matches_hand_computation(self) -> None:
        # Docs: A=[alpha,beta] B=[alpha,alpha,gamma] C=[delta]
        # Query raw=[alpha,alpha] → distinct [alpha]; N=3; avgdl=2.0
        # df(alpha)=2; IDF=ln(1+(3-2+0.5)/(2+0.5))=ln(1.6)
        documents = [
            ["alpha", "beta"],
            ["alpha", "alpha", "gamma"],
            ["delta"],
        ]
        query = ["alpha", "alpha"]
        scores = bm25_scores(query, documents, k1=BM25_K1, b=BM25_B)

        idf = math.log(1.0 + (3 - 2 + 0.5) / (2 + 0.5))
        self.assertAlmostEqual(idf, bm25_idf(n_docs=3, df=2), places=12)

        # Doc A: tf=1, dl=2
        denom_a = 1 + BM25_K1 * (1.0 - BM25_B + BM25_B * (2 / 2.0))
        expected_a = idf * (1 * (BM25_K1 + 1.0)) / denom_a
        # Doc B: tf=2, dl=3
        denom_b = 2 + BM25_K1 * (1.0 - BM25_B + BM25_B * (3 / 2.0))
        expected_b = idf * (2 * (BM25_K1 + 1.0)) / denom_b
        expected_c = 0.0

        self.assertAlmostEqual(scores[0], expected_a, places=12)
        self.assertAlmostEqual(scores[1], expected_b, places=12)
        self.assertAlmostEqual(scores[2], expected_c, places=12)
        self.assertGreater(scores[1], scores[0])
        self.assertGreater(scores[0], scores[2])


class OrderingTests(unittest.TestCase):
    def test_score_desc_fqcn_asc_ties(self) -> None:
        classes = ["b.B", "a.A", "c.C"]
        docs = [["x"], ["x"], ["y"]]
        ranked = rank_tokenized_corpus(
            test_classes=classes,
            document_token_lists=docs,
            query_tokens=["x"],
        )
        # a.A and b.B tie on score; a.A wins by FQCN. c.C last.
        self.assertEqual([r.test_class for r in ranked], ["a.A", "b.B", "c.C"])
        self.assertEqual([r.rank for r in ranked], [1, 2, 3])
        self.assertAlmostEqual(ranked[0].score, ranked[1].score)
        self.assertGreater(ranked[0].score, ranked[2].score)

    def test_empty_query_complete_zero_ranking(self) -> None:
        classes = ["z.Z", "a.A", "m.M"]
        docs = [["alpha"], ["beta"], ["gamma"]]
        ranked = rank_tokenized_corpus(
            test_classes=classes,
            document_token_lists=docs,
            query_tokens=[],
        )
        self.assertEqual([r.test_class for r in ranked], ["a.A", "m.M", "z.Z"])
        self.assertTrue(all(r.score == 0.0 for r in ranked))
        self.assertTrue(all(math.isfinite(r.score) for r in ranked))

    def test_no_overlap_still_complete(self) -> None:
        classes = ["b.B", "a.A"]
        ranked = rank_tokenized_corpus(
            test_classes=classes,
            document_token_lists=[["foo"], ["bar"]],
            query_tokens=["zzz"],
        )
        self.assertEqual({r.test_class for r in ranked}, {"a.A", "b.B"})
        self.assertEqual(len(ranked), 2)
        self.assertTrue(all(r.score == 0.0 for r in ranked))
        # Tie at zero → FQCN ascending.
        self.assertEqual([r.test_class for r in ranked], ["a.A", "b.B"])


@unittest.skipUnless(
    (_DATA / "bugs" / "Cli_30" / "example.json").is_file()
    and (_DATA / "bugs" / "Cli_30" / "checkouts" / "fixed").is_dir()
    and _MANIFEST_PATH.is_file(),
    "Cli-30 complete example + fixed checkout + manifest required",
)
class LiveCli30RankingTests(unittest.TestCase):
    def test_permutation_of_inventory(self) -> None:
        from src.example_contract import read_json
        from src.ranking import build_lexical_inputs

        manifest = _load_manifest()
        inputs = build_lexical_inputs("Cli-30", data_root=_DATA, manifest=manifest)
        ranking = rank_suite(inputs)
        inventory = read_json(_DATA / "tests" / "Cli_30" / "inventory.json")
        classes = inventory["test_classes"]
        ranked_ids = [r.test_class for r in ranking.ranked]
        self.assertEqual(len(ranked_ids), len(classes))
        self.assertEqual(set(ranked_ids), set(classes))
        self.assertEqual(len(ranked_ids), len(set(ranked_ids)))
        self.assertTrue(all(math.isfinite(r.score) for r in ranking.ranked))
        # Sorted by documented rule.
        for i in range(len(ranking.ranked) - 1):
            a, b = ranking.ranked[i], ranking.ranked[i + 1]
            self.assertLessEqual(
                (-a.score, a.test_class),
                (-b.score, b.test_class),
            )
            self.assertEqual(a.rank, i + 1)


@unittest.skipUnless(
    _MANIFEST_PATH.is_file()
    and (_DATA / "bugs" / "Cli_30" / "checkouts" / "fixed").is_dir(),
    "development artifacts + checkouts required",
)
class LiveDevelopmentRankingTests(unittest.TestCase):
    def test_all_development_bugs(self) -> None:
        from src.example_contract import read_json
        from src.ranking import build_lexical_inputs

        manifest = _load_manifest()
        for qid in manifest["development_bug_ids"]:
            slug = qid.replace("-", "_", 1)
            checkout = _DATA / "bugs" / slug / "checkouts" / "fixed"
            if not checkout.is_dir():
                self.skipTest(f"fixed checkout missing for {qid}")
            inputs = build_lexical_inputs(qid, data_root=_DATA, manifest=manifest)
            ranking = rank_suite(inputs)
            inventory = read_json(_DATA / "tests" / slug / "inventory.json")
            classes = inventory["test_classes"]
            ranked_ids = [r.test_class for r in ranking.ranked]
            self.assertEqual(len(ranked_ids), len(classes), msg=qid)
            self.assertEqual(set(ranked_ids), set(classes), msg=qid)
            self.assertTrue(
                all(math.isfinite(r.score) for r in ranking.ranked),
                msg=qid,
            )
            self.assertEqual(ranking.n_docs, len(classes), msg=qid)


if __name__ == "__main__":
    unittest.main()
