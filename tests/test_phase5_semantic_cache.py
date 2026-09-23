"""P5-02: semantic cache keying, atomic writes, ledger dedupe."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.semantic_cache import (
    CACHE_SCHEMA_VERSION,
    GPT_PROMPT_VERSION,
    JEV_PROMPT_VERSION,
    CacheError,
    append_usage_ledger,
    build_failure_entry,
    build_jev_question,
    build_jev_state,
    build_success_score_entry,
    canonical_json,
    cost_breakdown_from_usage,
    default_price_basis,
    embedding_cache_key,
    get_or_none_score,
    load_score_cache,
    read_usage_ledger,
    semantic_cache_key,
    validate_score_entry,
    write_cache_entry,
)


class CanonicalSerializationTests(unittest.TestCase):
    def test_key_stable_and_order_independent_for_dict_keys(self) -> None:
        state = build_jev_state(code_change="A", candidate_test="B")
        question = build_jev_question()
        k1 = semantic_cache_key(
            provider="openrouter",
            model_id="typesafe/jev-1.13",
            prompt_version=JEV_PROMPT_VERSION,
            state=state,
            question=question,
        )
        # Rebuild question with different insertion order of criteria keys.
        q2 = {
            "criteria": {
                "false": question["criteria"]["false"],
                "true": question["criteria"]["true"],
            },
            "id": question["id"],
            "instructions": question["instructions"],
            "type": question["type"],
        }
        k2 = semantic_cache_key(
            provider="openrouter",
            model_id="typesafe/jev-1.13",
            prompt_version=JEV_PROMPT_VERSION,
            state={"candidate_test": "B", "code_change": "A"},
            question=q2,
        )
        self.assertEqual(k1, k2)
        self.assertEqual(len(k1), 64)

    def test_prompt_or_model_change_new_key(self) -> None:
        state = build_jev_state(code_change="A", candidate_test="B")
        question = build_jev_question()
        base = dict(
            provider="openrouter",
            model_id="typesafe/jev-1.13",
            prompt_version=JEV_PROMPT_VERSION,
            state=state,
            question=question,
        )
        k0 = semantic_cache_key(**base)
        self.assertNotEqual(
            k0,
            semantic_cache_key(**{**base, "prompt_version": "jev-v2"}),
        )
        self.assertNotEqual(
            k0,
            semantic_cache_key(**{**base, "model_id": "other"}),
        )
        self.assertNotEqual(
            k0,
            semantic_cache_key(**{**base, "provider": "typesafe_direct"}),
        )


class CacheRoundTripTests(unittest.TestCase):
    def test_write_load_and_hit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = build_jev_state(code_change="patch", candidate_test="test")
            question = build_jev_question()
            key, hit = get_or_none_score(
                kind="jev",
                provider="openrouter",
                model_id="typesafe/jev-1.13",
                prompt_version=JEV_PROMPT_VERSION,
                state=state,
                question=question,
                cache_root=root,
            )
            self.assertIsNone(hit)

            entry = build_success_score_entry(
                cache_key=key,
                provider="openrouter",
                model_id="typesafe/jev-1.13",
                observed_model_id="typesafe/jev-1.13-20260917",
                prompt_version=JEV_PROMPT_VERSION,
                state=state,
                question=question,
                score=0.87,
                usage={"input_tokens": 100, "output_tokens": 10, "cost": 0.00001},
                latency_ms=12.5,
                provider_request_id="req-1",
                price_basis=default_price_basis(route="openrouter"),
                metadata={"qualified_id": "Cli-30", "test_class": "a.A"},
            )
            # Metadata holds bug/class; state must not.
            self.assertNotIn("qualified_id", entry["state"])
            path = write_cache_entry(entry, kind="jev", cache_root=root)
            self.assertTrue(path.is_file())

            key2, hit2 = get_or_none_score(
                kind="jev",
                provider="openrouter",
                model_id="typesafe/jev-1.13",
                prompt_version=JEV_PROMPT_VERSION,
                state=state,
                question=question,
                cache_root=root,
            )
            self.assertEqual(key2, key)
            self.assertIsNotNone(hit2)
            assert hit2 is not None
            self.assertEqual(hit2["score"], 0.87)

    def test_corrupt_score_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = build_jev_state(code_change="p", candidate_test="t")
            question = build_jev_question()
            key = semantic_cache_key(
                provider="openrouter",
                model_id="m",
                prompt_version=JEV_PROMPT_VERSION,
                state=state,
                question=question,
            )
            bad = {
                "schema_version": CACHE_SCHEMA_VERSION,
                "status": "success",
                "cache_key": key,
                "provider": "openrouter",
                "model_id": "m",
                "prompt_version": JEV_PROMPT_VERSION,
                "state": state,
                "question": question,
                "score": 1.5,  # out of range
                "usage": {"input_tokens": 1, "output_tokens": 0},
            }
            path = root / "jev" / f"{key}.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(bad) + "\n", encoding="utf-8")
            with self.assertRaises(CacheError):
                load_score_cache(key, kind="jev", cache_root=root)

    def test_failure_not_usable_as_score(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            key = "a" * 64
            fail = build_failure_entry(
                cache_key=key,
                kind="jev",
                provider="openrouter",
                model_id="m",
                prompt_version=JEV_PROMPT_VERSION,
                error="timeout",
                retry_count=2,
            )
            write_cache_entry(fail, kind="failure", cache_root=root)
            # Success loader looks in jev/, not failures/.
            self.assertIsNone(load_score_cache(key, kind="jev", cache_root=root))
            with self.assertRaises(CacheError):
                validate_score_entry(fail)


class LedgerTests(unittest.TestCase):
    def test_no_double_count_on_resume(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "usage_ledger.jsonl"
            record = {
                "cache_key": "b" * 64,
                "attempt_id": "b" * 64,
                "kind": "jev",
                "status": "success",
                "input_tokens": 10,
                "costs": cost_breakdown_from_usage(
                    input_tokens=10,
                    price_basis=default_price_basis(route="openrouter"),
                    provider_reported_cost_usd=0.00001,
                ),
            }
            r1 = append_usage_ledger(record, ledger_path=ledger)
            r2 = append_usage_ledger(record, ledger_path=ledger)
            self.assertTrue(r1.appended)
            self.assertFalse(r2.appended)
            rows = read_usage_ledger(ledger_path=ledger)
            self.assertEqual(len(rows), 1)

    def test_cost_splits_list_and_fee(self) -> None:
        costs = cost_breakdown_from_usage(
            input_tokens=1_000_000,
            price_basis=default_price_basis(route="openrouter"),
            actual_cash_usd=0.05,
        )
        self.assertAlmostEqual(costs["list_price_inference_usd"], 0.042, places=12)
        self.assertAlmostEqual(costs["platform_fee_usd"], 0.042 * 0.055, places=12)
        self.assertEqual(costs["actual_cash_usd"], 0.05)


class EmbeddingKeyTests(unittest.TestCase):
    def test_text_change_new_key(self) -> None:
        a = embedding_cache_key(model_id="text-embedding-3-small", input_text="x")
        b = embedding_cache_key(model_id="text-embedding-3-small", input_text="y")
        self.assertNotEqual(a, b)


class PromptSeparationTests(unittest.TestCase):
    def test_gpt_prompt_version_distinct(self) -> None:
        self.assertNotEqual(JEV_PROMPT_VERSION, GPT_PROMPT_VERSION)
        self.assertIn("would_detect_regression", build_jev_question()["id"])


if __name__ == "__main__":
    unittest.main()
