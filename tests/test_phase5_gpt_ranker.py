"""P5-06: GPT comparison clients — multi-model, structured probability, cache."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from src.gpt_ranker import (
    COMPARISON_MODELS,
    GptRankerError,
    GptRoute,
    assert_gpt_request_contract,
    build_chat_body,
    build_gpt_messages,
    get_comparison_model,
    get_or_score_pair,
    parse_probability,
    primary_comparison_model,
)
from src.semantic_cache import (
    GPT_PROMPT_VERSION,
    build_gpt_question,
    build_jev_state,
    load_score_cache,
    semantic_cache_key,
)


class RegistryTests(unittest.TestCase):
    def test_primary_is_gpt_5_4_nano_snapshot(self) -> None:
        primary = primary_comparison_model()
        self.assertEqual(primary.canonical_model_id, "gpt-5.4-nano-2026-03-17")
        self.assertEqual(primary.reasoning_effort, "none")
        self.assertEqual(primary.ranking_name, "GPT-Nano")
        self.assertTrue(primary.is_primary)

    def test_multiple_comparison_models(self) -> None:
        keys = [m.key for m in COMPARISON_MODELS]
        self.assertGreaterEqual(len(keys), 2)
        self.assertIn("gpt-5.4-nano", keys)
        self.assertIn("gpt-4.1-nano", keys)
        self.assertIn("gpt-4o-mini", keys)
        self.assertIn("gpt-luna", keys)
        self.assertEqual(sum(1 for m in COMPARISON_MODELS if m.is_primary), 1)

    def test_gpt_luna_uses_none_reasoning(self) -> None:
        m = get_comparison_model("gpt-luna")
        self.assertEqual(m.canonical_model_id, "gpt-5.6-luna")
        self.assertEqual(m.reasoning_effort, "none")
        self.assertEqual(m.ranking_name, "GPT-Luna")
        self.assertFalse(m.is_primary)

    def test_lookup(self) -> None:
        m = get_comparison_model("gpt-4o-mini")
        self.assertEqual(m.canonical_model_id, "gpt-4o-mini-2024-07-18")


class PromptAndParseTests(unittest.TestCase):
    def test_messages_embed_exact_payloads(self) -> None:
        messages = build_gpt_messages(code_change="PATCH_X", candidate_test="TEST_Y")
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("Return a number from 0 to 1", messages[0]["content"])
        self.assertIn("RUBRIC INSTRUCTIONS:", messages[0]["content"])
        self.assertIn("Do not include chain-of-thought", messages[0]["content"])
        self.assertIn("PATCH_X", messages[1]["content"])
        self.assertIn("TEST_Y", messages[1]["content"])
        self.assertNotIn("PATCH_X", messages[0]["content"])

    def test_gpt_question_matches_jev_rubric_bytes(self) -> None:
        from src.semantic_cache import build_jev_question

        g = build_gpt_question()
        j = build_jev_question()
        self.assertEqual(g["instructions"], j["instructions"])
        self.assertEqual(g["criteria"], j["criteria"])
        self.assertTrue(g["no_chain_of_thought"])

    def test_parse_probability_strict(self) -> None:
        parsed = parse_probability(
            {
                "model": "openai/gpt-5.4-nano",
                "id": "gen-1",
                "choices": [
                    {"message": {"content": '{"probability": 0.33}'}},
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            }
        )
        self.assertEqual(parsed["score"], 0.33)
        with self.assertRaises(GptRankerError):
            parse_probability(
                {
                    "choices": [{"message": {"content": '{"probability": 1.2}'}}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                }
            )
        with self.assertRaises(GptRankerError):
            parse_probability(
                {
                    "choices": [
                        {"message": {"content": '{"probability": 0.5, "extra": 1}'}}
                    ],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                }
            )

    def test_request_contract_one_pair(self) -> None:
        route = GptRoute(
            provider="openrouter",
            chat_url="https://example.invalid/chat",
            api_key_env="OPENROUTER_API_KEY",
        )
        model = primary_comparison_model()
        body = build_chat_body(
            model=model,
            route=route,
            code_change="A",
            candidate_test="B",
        )
        self.assertEqual(body["reasoning"], {"effort": "none"})
        assert_gpt_request_contract(body=body, code_change="A", candidate_test="B")


class CacheClientTests(unittest.TestCase):
    def test_cache_hit_and_distinct_model_keys(self) -> None:
        calls: list[str] = []

        def fake_for(score: float, model_name: str):
            def _call() -> tuple[dict[str, Any], dict[str, Any], float]:
                calls.append(model_name)
                body = {"model": model_name, "messages": []}
                parsed = {
                    "score": score,
                    "usage": {
                        "input_tokens": 11,
                        "output_tokens": 3,
                        "cached_input_tokens": 0,
                        "cost": 0.0,
                    },
                    "observed_model_id": model_name,
                    "provider_request_id": "x",
                }
                return body, parsed, 1.0

            return _call

        route = GptRoute(
            provider="openrouter",
            chat_url="https://example.invalid/chat",
            api_key_env="OPENROUTER_API_KEY",
        )
        with tempfile.TemporaryDirectory() as tmp:
            cache_root = Path(tmp) / "cache"
            ledger = Path(tmp) / "ledger.jsonl"
            a = get_or_score_pair(
                code_change="A",
                candidate_test="B",
                model="gpt-5.4-nano",
                route=route,
                cache_root=cache_root,
                ledger_path=ledger,
                call_fn=fake_for(0.4, "nano"),
            )
            b = get_or_score_pair(
                code_change="A",
                candidate_test="B",
                model="gpt-4o-mini",
                route=route,
                cache_root=cache_root,
                ledger_path=ledger,
                call_fn=fake_for(0.6, "mini"),
            )
            self.assertEqual(a.score, 0.4)
            self.assertEqual(b.score, 0.6)
            self.assertNotEqual(a.cache_key, b.cache_key)
            self.assertEqual(len(calls), 2)

            a2 = get_or_score_pair(
                code_change="A",
                candidate_test="B",
                model="gpt-5.4-nano",
                route=route,
                cache_root=cache_root,
                ledger_path=ledger,
                call_fn=fake_for(0.4, "nano"),
            )
            self.assertTrue(a2.from_cache)
            self.assertEqual(len(calls), 2)

            key = semantic_cache_key(
                provider="openrouter",
                model_id="gpt-5.4-nano-2026-03-17",
                prompt_version=GPT_PROMPT_VERSION,
                state=build_jev_state(code_change="A", candidate_test="B"),
                question=build_gpt_question(),
            )
            self.assertIsNotNone(load_score_cache(key, kind="gpt", cache_root=cache_root))


if __name__ == "__main__":
    unittest.main()
