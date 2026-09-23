"""P5-08: assemble semantic rankings from shared BM25 shortlist."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.assemble_rankings import (
    AssembleError,
    assemble_from_scores,
    assemble_gpt_ranking,
    assemble_jev_ranking,
)


def _bm25_doc(ids: list[str], *, k: int | None = None) -> dict:
    k = len(ids) if k is None else k
    from src.candidates import shortlist_content_hash

    cand = ids[:k]
    digest = shortlist_content_hash(cand)
    return {
        "qualified_id": "Toy-1",
        "N": len(ids),
        "K": k,
        "shortlist_sha256": digest,
        "candidate_ids": cand,
        "ranking": [
            {"test_class": c, "score": float(len(ids) - i), "rank": i + 1}
            for i, c in enumerate(ids)
        ],
    }


def _candidates_doc(ids: list[str], *, k: int) -> dict:
    from src.candidates import shortlist_content_hash

    cand = ids[:k]
    return {
        "qualified_id": "Toy-1",
        "N": len(ids),
        "K": k,
        "k_cap": 200,
        "candidate_ids": cand,
        "shortlist_sha256": shortlist_content_hash(cand),
        "split": "development",
    }


class AssembleFromScoresTests(unittest.TestCase):
    def test_prefix_reordered_tail_unchanged(self) -> None:
        ids = ["a.A", "b.B", "c.C", "d.D", "e.E"]
        k = 3
        bm25 = _bm25_doc(ids, k=k)
        cand = _candidates_doc(ids, k=k)
        # Prefer c, then a, then b (vs BM25 a,b,c)
        scores = {"a.A": 0.2, "b.B": 0.1, "c.C": 0.9}
        doc = assemble_from_scores(
            example="Cli-30",  # parseable; ids are synthetic
            method="Jev",
            scores=scores,
            candidates=cand,
            bm25_ranking=bm25,
            provenance={"model_id": "x"},
        )
        # Use ExampleId - Cli-30 works for slug fields only
        self.assertEqual(doc["ranked_ids"], ["c.C", "a.A", "b.B", "d.D", "e.E"])
        self.assertEqual(doc["tail_ids"], ["d.D", "e.E"])
        self.assertEqual(doc["tail_ids"], ids[k:])
        self.assertTrue(doc["ranking"][0]["scored"])
        self.assertFalse(doc["ranking"][3]["scored"])
        self.assertIsNone(doc["ranking"][3]["score"])

    def test_tie_break_uses_bm25_rank(self) -> None:
        ids = ["b.B", "a.A", "c.C"]
        bm25 = _bm25_doc(ids, k=3)
        cand = _candidates_doc(ids, k=3)
        scores = {"a.A": 0.5, "b.B": 0.5, "c.C": 0.1}
        doc = assemble_from_scores(
            example="Cli-30",
            method="Jev",
            scores=scores,
            candidates=cand,
            bm25_ranking=bm25,
            provenance={},
        )
        # Equal 0.5: BM25 rank of b.B is 1, a.A is 2 → b then a
        self.assertEqual(doc["ranked_ids"][:2], ["b.B", "a.A"])

    def test_missing_score_fails_closed(self) -> None:
        ids = ["a.A", "b.B", "c.C"]
        bm25 = _bm25_doc(ids, k=2)
        cand = _candidates_doc(ids, k=2)
        with self.assertRaises(AssembleError):
            assemble_from_scores(
                example="Cli-30",
                method="Jev",
                scores={"a.A": 0.5},
                candidates=cand,
                bm25_ranking=bm25,
                provenance={},
            )

    def test_out_of_range_score_rejected(self) -> None:
        ids = ["a.A", "b.B"]
        bm25 = _bm25_doc(ids, k=2)
        cand = _candidates_doc(ids, k=2)
        with self.assertRaises(AssembleError):
            assemble_from_scores(
                example="Cli-30",
                method="Jev",
                scores={"a.A": 1.5, "b.B": 0.1},
                candidates=cand,
                bm25_ranking=bm25,
                provenance={},
            )

    def test_settings_forbid_candidate_regen(self) -> None:
        ids = ["a.A", "b.B"]
        doc = assemble_from_scores(
            example="Cli-30",
            method="Jev",
            scores={"a.A": 0.2, "b.B": 0.8},
            candidates=_candidates_doc(ids, k=2),
            bm25_ranking=_bm25_doc(ids, k=2),
            provenance={},
        )
        self.assertFalse(doc["settings"]["regenerates_candidates"])


@unittest.skipUnless(
    Path("/workspace/data/candidates/Cli_30.json").is_file()
    and Path("/workspace/results/rankings/Cli_30.json").is_file()
    and Path("/workspace/cache/jev").is_dir(),
    "Cli-30 artifacts require /workspace mount",
)
class Cli30LiveAssemblyTests(unittest.TestCase):
    def test_assemble_jev_and_primary_gpt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jev = assemble_jev_ranking("Cli-30", results_root=root, write=True)
            self.assertEqual(jev.document["method"], "Jev")
            self.assertEqual(jev.document["N"], len(jev.document["ranked_ids"]))
            from src.candidates import load_ranking

            bm25 = load_ranking("Cli-30")
            bm25_ids = [e["test_class"] for e in bm25["ranking"]]
            k = jev.document["K"]
            self.assertEqual(
                set(jev.document["prefix_order"]),
                set(jev.document["candidate_ids"]),
            )
            self.assertEqual(jev.document["ranked_ids"][k:], bm25_ids[k:])
            self.assertTrue(jev.path.is_file())

            gpt = assemble_gpt_ranking(
                "Cli-30",
                model="gpt-5.4-nano",
                results_root=root,
                write=True,
            )
            self.assertEqual(gpt.document["method"], "GPT-Nano")
            self.assertEqual(
                gpt.document["shortlist_sha256"],
                jev.document["shortlist_sha256"],
            )
            self.assertEqual(
                gpt.document["candidate_ids"],
                jev.document["candidate_ids"],
            )
            self.assertEqual(gpt.document["ranked_ids"][k:], bm25_ids[k:])


if __name__ == "__main__":
    unittest.main()
