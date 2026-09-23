"""P5-04: Embedding baseline — cosine ranking, cache, no BM25, over-limit."""

from __future__ import annotations

import math
import tempfile
import unittest
from pathlib import Path
from typing import Any

from src.embeddings import (
    EMBEDDING_MODEL_ID,
    EXPECTED_DIMENSIONS,
    OVER_LIMIT_RULE,
    EmbeddingError,
    EmbeddingLimitError,
    EmbeddingRoute,
    cosine_similarity,
    generate_embedding_ranking,
    get_or_embed_texts,
    rank_by_cosine,
)
from src.example_contract import ExampleId, load_manifest
from src.semantic_cache import embedding_cache_key, load_embedding_cache

_REPO = Path(__file__).resolve().parents[1]
_DATA = _REPO / "data"
_HAS_CLI30 = (_DATA / "tests" / "Cli_30" / "inventory.json").is_file()


def _unit(vec: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in vec))
    return [x / n for x in vec]


class CosineAndRankTests(unittest.TestCase):
    def test_identical_vectors_score_one(self) -> None:
        v = _unit([1.0, 2.0, 3.0])
        self.assertAlmostEqual(cosine_similarity(v, v), 1.0, places=12)

    def test_orthogonal_score_zero(self) -> None:
        a = _unit([1.0, 0.0])
        b = _unit([0.0, 1.0])
        self.assertAlmostEqual(cosine_similarity(a, b), 0.0, places=12)

    def test_rank_cosine_desc_fqcn_asc_ties(self) -> None:
        query = _unit([1.0, 0.0])
        # b and a both orthogonal→same score 0; c aligned.
        docs = {
            "b.B": _unit([0.0, 1.0]),
            "a.A": _unit([0.0, 1.0]),
            "c.C": _unit([1.0, 0.0]),
        }
        ranked = rank_by_cosine(query=query, documents=docs)
        self.assertEqual([r["test_class"] for r in ranked], ["c.C", "a.A", "b.B"])
        self.assertAlmostEqual(ranked[0]["score"], 1.0, places=12)
        self.assertEqual(ranked[1]["score"], ranked[2]["score"])

    def test_rejects_non_finite(self) -> None:
        with self.assertRaises(EmbeddingError):
            cosine_similarity([1.0], [float("nan")])


class CacheAndClientTests(unittest.TestCase):
    def test_cache_hit_skips_network(self) -> None:
        calls: list[list[str]] = []

        def fake_batch(inputs: list[str]) -> tuple[list[list[float]], dict[str, Any], str | None, float]:
            calls.append(list(inputs))
            vectors = []
            for i, _ in enumerate(inputs):
                raw = [0.0] * EXPECTED_DIMENSIONS
                raw[0] = 1.0
                raw[1] = float(i + 1)
                vectors.append(_unit(raw))
            return vectors, {"input_tokens": 3 * len(inputs), "cost": 0.0}, "req-1", 1.0

        route = EmbeddingRoute(
            provider="openrouter",
            request_model="openai/text-embedding-3-small",
            canonical_model_id=EMBEDDING_MODEL_ID,
            price_route="openrouter_embedding",
            url="https://example.invalid/embeddings",
            api_key_env="OPENROUTER_API_KEY",
        )
        with tempfile.TemporaryDirectory() as tmp:
            cache_root = Path(tmp) / "cache"
            ledger = Path(tmp) / "ledger.jsonl"
            texts = ["alpha text", "beta text"]
            first = get_or_embed_texts(
                texts,
                route=route,
                cache_root=cache_root,
                ledger_path=ledger,
                embed_batch=fake_batch,
            )
            self.assertEqual(len(calls), 1)
            self.assertEqual(len(first), 2)
            self.assertEqual(first[0]["dimensions"], EXPECTED_DIMENSIONS)

            second = get_or_embed_texts(
                texts,
                route=route,
                cache_root=cache_root,
                ledger_path=ledger,
                embed_batch=fake_batch,
            )
            self.assertEqual(len(calls), 1)  # no new network
            self.assertEqual(second[0]["cache_key"], first[0]["cache_key"])
            key = embedding_cache_key(model_id=EMBEDDING_MODEL_ID, input_text="alpha text")
            self.assertIsNotNone(load_embedding_cache(key, cache_root=cache_root))

    def test_over_limit_fail_closed(self) -> None:
        def boom(_inputs: list[str]):
            raise EmbeddingLimitError("maximum context length exceeded 8192")

        route = EmbeddingRoute(
            provider="openai",
            request_model=EMBEDDING_MODEL_ID,
            canonical_model_id=EMBEDDING_MODEL_ID,
            price_route="openai_embedding",
            url="https://example.invalid/embeddings",
            api_key_env="OPENAI_API_KEY",
        )
        with tempfile.TemporaryDirectory() as tmp:
            cache_root = Path(tmp) / "cache"
            with self.assertRaises(EmbeddingLimitError):
                get_or_embed_texts(
                    ["huge"],
                    route=route,
                    cache_root=cache_root,
                    ledger_path=Path(tmp) / "ledger.jsonl",
                    embed_batch=boom,
                )
            # Failure recorded, not a success embedding.
            failures = list((cache_root / "failures").glob("*.json"))
            self.assertEqual(len(failures), 1)

    def test_over_limit_rule_constant(self) -> None:
        self.assertEqual(OVER_LIMIT_RULE, "fail_closed_no_truncate_v1")


@unittest.skipUnless(_HAS_CLI30, "Cli-30 development artifacts missing")
class DevelopmentRankingSmokeTests(unittest.TestCase):
    def test_cli30_ranking_from_fake_embeds(self) -> None:
        # Deterministic fake vectors derived from text length — no network.
        def fake_batch(inputs: list[str]):
            vectors = []
            for text in inputs:
                raw = [0.0] * EXPECTED_DIMENSIONS
                raw[0] = 1.0
                raw[1] = float(len(text) % 97) / 97.0
                raw[2] = float(sum(ord(c) for c in text[:50]) % 89) / 89.0
                vectors.append(_unit(raw))
            return vectors, {"input_tokens": sum(len(t) for t in inputs), "cost": 0.0}, None, 0.5

        route = EmbeddingRoute(
            provider="openrouter",
            request_model="openai/text-embedding-3-small",
            canonical_model_id=EMBEDDING_MODEL_ID,
            price_route="openrouter_embedding",
            url="https://example.invalid/embeddings",
            api_key_env="OPENROUTER_API_KEY",
        )
        # load_manifest uses WORKSPACE; pass manifest explicitly from host file.
        import json

        with (_DATA / "manifest.json").open(encoding="utf-8") as handle:
            manifest = json.load(handle)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            doc, outcome = generate_embedding_ranking(
                ExampleId.parse("Cli-30"),
                split="development",
                manifest=manifest,
                data_root=_DATA,
                results_root=tmp_path / "embeddings",
                cache_root=tmp_path / "cache",
                ledger_path=tmp_path / "ledger.jsonl",
                route=route,
                embed_batch=fake_batch,
            )
            self.assertIn(outcome.value, {"written", "reused", "regenerated"})
            self.assertEqual(doc["N"], len(doc["ranking"]))
            self.assertEqual(doc["settings"]["uses_bm25"], False)
            self.assertEqual(doc["settings"]["shortlist_restricted"], False)
            self.assertEqual(doc["over_limit_rule"], OVER_LIMIT_RULE)
            ids = [r["test_class"] for r in doc["ranking"]]
            self.assertEqual(len(ids), len(set(ids)))
            scores = [r["score"] for r in doc["ranking"]]
            self.assertTrue(all(math.isfinite(s) for s in scores))
            # Reuse
            _, outcome2 = generate_embedding_ranking(
                ExampleId.parse("Cli-30"),
                split="development",
                manifest=manifest,
                data_root=_DATA,
                results_root=tmp_path / "embeddings",
                cache_root=tmp_path / "cache",
                ledger_path=tmp_path / "ledger.jsonl",
                route=route,
                embed_batch=fake_batch,
            )
            self.assertEqual(outcome2.value, "reused")


if __name__ == "__main__":
    unittest.main()
