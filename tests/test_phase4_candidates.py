"""Phase 4 P4-04: candidate shortlist + full ranking persistence."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.bm25 import BM25_B, BM25_K1, BM25_VERSION
from src.candidates import (
    CANDIDATE_K_CAP,
    CandidatesError,
    SaveOutcome,
    build_artifacts_from_ranking,
    candidate_k,
    generate_and_save,
    load_candidates,
    load_ranking,
    save_ranking_and_candidates,
    semantic_lock_path,
    shortlist_content_hash,
    verify_shortlist_is_ranking_prefix,
)
from src.ranking import RankedTestClass, SuiteRanking
from src.tokenize import TOKENIZER_VERSION

_REPO = Path(__file__).resolve().parents[1]
_DATA = _REPO / "data"
_MANIFEST_PATH = _DATA / "manifest.json"


def _load_manifest() -> dict:
    with _MANIFEST_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def _toy_ranking(*, n: int = 5) -> SuiteRanking:
    ranked = tuple(
        RankedTestClass(
            test_class=f"p.T{i}",
            score=float(n - i),
            rank=i + 1,
            source_missing=False,
        )
        for i in range(n)
    )
    return SuiteRanking(
        example_id="Toy_1",
        qualified_id="Toy-1",
        ranked=ranked,
        n_docs=n,
        avgdl=10.0,
        query_token_count=3,
        distinct_query_terms=3,
        bm25_version=BM25_VERSION,
        k1=BM25_K1,
        b=BM25_B,
        input_hashes={
            "lexical_input_contract_version": "jev-bm25-lexical-v1",
            "query_diff_source": "model_visible_representation",
            "test_class_ids_sha256": "a" * 64,
            "query_sha256": "b" * 64,
            "documents_sha256": "c" * 64,
            "inventory_sha256": "d" * 64,
            "patch_representation_sha256": "e" * 64,
            "tokenizer_version": TOKENIZER_VERSION,
            "tokenizer_config_sha256": "f" * 64,
            "bm25_version": BM25_VERSION,
            "bm25_k1": BM25_K1,
            "bm25_b": BM25_B,
        },
    )


class CandidateKTests(unittest.TestCase):
    def test_cap(self) -> None:
        self.assertEqual(candidate_k(n=50), 50)
        self.assertEqual(candidate_k(n=200), 200)
        self.assertEqual(candidate_k(n=500), CANDIDATE_K_CAP)
        self.assertEqual(CANDIDATE_K_CAP, 200)


class ArtifactShapeTests(unittest.TestCase):
    def test_shortlist_is_prefix(self) -> None:
        ranking = _toy_ranking(n=5)
        manifest = {
            "selection_seed": 1,
            "defects4j_commit": "abc",
            "defects4j_version": "3.0.1",
        }
        cand, full = build_artifacts_from_ranking(
            ranking, split="development", manifest=manifest, source_missing_count=0
        )
        self.assertEqual(cand["N"], 5)
        self.assertEqual(cand["K"], 5)
        self.assertEqual(cand["candidate_ids"], [f"p.T{i}" for i in range(5)])
        self.assertEqual(cand["candidate_ids"], full["candidate_ids"])
        self.assertEqual(
            cand["candidate_ids"],
            [e["test_class"] for e in full["ranking"][: cand["K"]]],
        )
        self.assertEqual(
            cand["shortlist_sha256"],
            shortlist_content_hash(cand["candidate_ids"]),
        )
        self.assertNotIn("positive_classes", cand)
        self.assertNotIn("trigger_methods", full)

    def test_k_capped_at_200(self) -> None:
        ranking = _toy_ranking(n=250)
        # Rebuild with 250 entries.
        ranked = tuple(
            RankedTestClass(
                test_class=f"p.T{i:04d}",
                score=float(250 - i),
                rank=i + 1,
                source_missing=False,
            )
            for i in range(250)
        )
        ranking = SuiteRanking(
            example_id="Toy_1",
            qualified_id="Toy-1",
            ranked=ranked,
            n_docs=250,
            avgdl=1.0,
            query_token_count=1,
            distinct_query_terms=1,
            bm25_version=BM25_VERSION,
            k1=BM25_K1,
            b=BM25_B,
            input_hashes=_toy_ranking().input_hashes,
        )
        cand, full = build_artifacts_from_ranking(
            ranking,
            split="development",
            manifest={"defects4j_commit": "x", "selection_seed": 1},
            source_missing_count=0,
        )
        self.assertEqual(cand["N"], 250)
        self.assertEqual(cand["K"], 200)
        self.assertEqual(len(cand["candidate_ids"]), 200)
        self.assertEqual(len(full["ranking"]), 250)
        self.assertEqual(
            cand["candidate_ids"],
            [e["test_class"] for e in full["ranking"][:200]],
        )


class PersistenceTests(unittest.TestCase):
    def test_write_reuse_and_lock(self) -> None:
        ranking = _toy_ranking(n=5)
        manifest = {
            "selection_seed": 1,
            "defects4j_commit": "abc",
            "defects4j_version": "3.0.1",
        }
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp) / "data"
            results_root = Path(tmp) / "results"
            data_root.mkdir()
            results_root.mkdir()

            r1 = save_ranking_and_candidates(
                ranking,
                split="development",
                manifest=manifest,
                data_root=data_root,
                results_root=results_root,
            )
            self.assertEqual(r1.outcome, SaveOutcome.WRITTEN)
            cand_bytes = r1.candidate_path.read_bytes()
            rank_bytes = r1.ranking_path.read_bytes()

            r2 = save_ranking_and_candidates(
                ranking,
                split="development",
                manifest=manifest,
                data_root=data_root,
                results_root=results_root,
            )
            self.assertEqual(r2.outcome, SaveOutcome.REUSED)
            self.assertEqual(r2.candidate_path.read_bytes(), cand_bytes)
            self.assertEqual(r2.ranking_path.read_bytes(), rank_bytes)

            loaded_c = load_candidates("Toy-1", data_root=data_root)
            loaded_r = load_ranking("Toy-1", results_root=results_root)
            verify_shortlist_is_ranking_prefix(candidates=loaded_c, ranking=loaded_r)

            # Stale: change an input hash → regenerate.
            stale = SuiteRanking(
                example_id=ranking.example_id,
                qualified_id=ranking.qualified_id,
                ranked=ranking.ranked,
                n_docs=ranking.n_docs,
                avgdl=ranking.avgdl,
                query_token_count=ranking.query_token_count,
                distinct_query_terms=ranking.distinct_query_terms,
                bm25_version=ranking.bm25_version,
                k1=ranking.k1,
                b=ranking.b,
                input_hashes={**ranking.input_hashes, "query_sha256": "9" * 64},
            )
            r3 = save_ranking_and_candidates(
                stale,
                split="development",
                manifest=manifest,
                data_root=data_root,
                results_root=results_root,
            )
            self.assertEqual(r3.outcome, SaveOutcome.REGENERATED)

            # Lock blocks overwrite when regeneration is required.
            lock = semantic_lock_path("Toy-1", data_root=data_root)
            lock.write_text("held\n", encoding="utf-8")
            locked = SuiteRanking(
                example_id=ranking.example_id,
                qualified_id=ranking.qualified_id,
                ranked=ranking.ranked,
                n_docs=ranking.n_docs,
                avgdl=ranking.avgdl,
                query_token_count=ranking.query_token_count,
                distinct_query_terms=ranking.distinct_query_terms,
                bm25_version=ranking.bm25_version,
                k1=ranking.k1,
                b=ranking.b,
                input_hashes={**ranking.input_hashes, "query_sha256": "8" * 64},
            )
            with self.assertRaises(CandidatesError) as ctx:
                save_ranking_and_candidates(
                    locked,
                    split="development",
                    manifest=manifest,
                    data_root=data_root,
                    results_root=results_root,
                )
            self.assertIn("semantic lock", str(ctx.exception))


@unittest.skipUnless(
    (_DATA / "bugs" / "Cli_30" / "example.json").is_file()
    and (_DATA / "bugs" / "Cli_30" / "checkouts" / "fixed").is_dir()
    and _MANIFEST_PATH.is_file(),
    "Cli-30 complete example + checkout + manifest required",
)
class LiveCli30CandidateTests(unittest.TestCase):
    def test_generate_prefix_and_reuse(self) -> None:
        manifest = _load_manifest()
        results_root = _REPO / "results"
        r1 = generate_and_save(
            "Cli-30",
            data_root=_DATA,
            results_root=results_root,
            manifest=manifest,
        )
        self.assertIn(r1.outcome, {SaveOutcome.WRITTEN, SaveOutcome.REGENERATED, SaveOutcome.REUSED})
        cand = load_candidates("Cli-30", data_root=_DATA)
        ranking = load_ranking("Cli-30", results_root=results_root)
        verify_shortlist_is_ranking_prefix(candidates=cand, ranking=ranking)
        self.assertEqual(cand["K"], candidate_k(n=cand["N"]))
        self.assertEqual(len(cand["candidate_ids"]), cand["K"])
        self.assertEqual(len(set(cand["candidate_ids"])), cand["K"])

        before = r1.candidate_path.read_bytes()
        r2 = generate_and_save(
            "Cli-30",
            data_root=_DATA,
            results_root=results_root,
            manifest=manifest,
        )
        self.assertEqual(r2.outcome, SaveOutcome.REUSED)
        self.assertEqual(r2.candidate_path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
