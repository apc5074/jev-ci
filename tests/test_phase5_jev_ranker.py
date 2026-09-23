"""P5-05: Jev one-pair client — Noul parse, one-pair contract, cache, aliases."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from src.jev_ranker import (
    JEV_QUESTION_ID,
    JevRankerError,
    JevRoute,
    assert_model_allowed_for_eval,
    assert_one_pair_request,
    build_systemone_body,
    get_or_score_pair,
    parse_noul_score,
    redact_secrets,
)
from src.jev_providers import OPENROUTER_JEV_MODEL
from src.semantic_cache import (
    JEV_PROMPT_VERSION,
    build_jev_question,
    build_jev_state,
    load_score_cache,
    semantic_cache_key,
)


class AliasAndRedactionTests(unittest.TestCase):
    def test_rejects_latest_alias(self) -> None:
        with self.assertRaises(JevRankerError):
            assert_model_allowed_for_eval("jev-latest")
        with self.assertRaises(JevRankerError):
            assert_model_allowed_for_eval("~typesafe/jev-latest")

    def test_allows_pinned_openrouter_model(self) -> None:
        assert_model_allowed_for_eval(OPENROUTER_JEV_MODEL)
        assert_model_allowed_for_eval("typesafe/jev-1.13-20260917")

    def test_redacts_bearer_and_env(self) -> None:
        import os

        os.environ["OPENROUTER_API_KEY"] = "sk-test-secret-value"
        try:
            text = redact_secrets("Authorization: Bearer sk-test-secret-value boom")
            self.assertNotIn("sk-test-secret-value", text)
            self.assertIn("[REDACTED]", text)
        finally:
            del os.environ["OPENROUTER_API_KEY"]


class NoulParseTests(unittest.TestCase):
    def test_parses_valid_noul(self) -> None:
        parsed = parse_noul_score(
            {
                "model": "typesafe/jev-1.13-20260917",
                "answers": {
                    JEV_QUESTION_ID: {"type": "noul", "noul": 0.42},
                },
                "usage": {"input_tokens": 10, "output_tokens": 1},
                "id": "gen-1",
            }
        )
        self.assertEqual(parsed["score"], 0.42)

    def test_rejects_out_of_range_and_non_noul(self) -> None:
        with self.assertRaises(JevRankerError):
            parse_noul_score(
                {
                    "answers": {JEV_QUESTION_ID: {"type": "noul", "noul": 1.5}},
                    "usage": {"input_tokens": 1},
                }
            )
        with self.assertRaises(JevRankerError):
            parse_noul_score(
                {
                    "answers": {
                        JEV_QUESTION_ID: {"type": "confidence", "confidence": 0.9}
                    },
                    "usage": {"input_tokens": 1},
                }
            )


class OnePairContractTests(unittest.TestCase):
    def test_body_is_exactly_one_pair(self) -> None:
        route = JevRoute(
            provider="openrouter",
            request_model=OPENROUTER_JEV_MODEL,
            endpoint="https://example.invalid/systemone",
            price_route="openrouter",
            api_key_env="OPENROUTER_API_KEY",
        )
        state = build_jev_state(code_change="PATCH", candidate_test="TEST")
        question = build_jev_question()
        body = build_systemone_body(route=route, state=state, question=question)
        assert_one_pair_request(body=body, code_change="PATCH", candidate_test="TEST")
        self.assertEqual(list(body["questions"].keys()), [JEV_QUESTION_ID])
        self.assertEqual(body["questions"][JEV_QUESTION_ID]["type"], "noul")
        # Question text matches overall.md / semantic_cache v1
        self.assertIn("Would this test class be likely", question["instructions"])

    def test_rejects_extra_state_keys(self) -> None:
        body = {
            "model": OPENROUTER_JEV_MODEL,
            "state": {
                "code_change": "A",
                "candidate_test": "B",
                "bug_id": "Cli-30",
            },
            "questions": {JEV_QUESTION_ID: {"type": "noul", "instructions": "x", "criteria": {}}},
        }
        with self.assertRaises(JevRankerError):
            assert_one_pair_request(body=body, code_change="A", candidate_test="B")


class CacheClientTests(unittest.TestCase):
    def test_cache_hit_skips_network(self) -> None:
        calls = {"n": 0}

        def fake_call() -> tuple[dict[str, Any], dict[str, Any], float]:
            calls["n"] += 1
            body = {
                "model": OPENROUTER_JEV_MODEL,
                "state": {"code_change": "A", "candidate_test": "B"},
                "questions": {JEV_QUESTION_ID: {"type": "noul"}},
            }
            parsed = {
                "score": 0.77,
                "usage": {"input_tokens": 12, "output_tokens": 2, "cost": 0.0},
                "observed_model_id": "typesafe/jev-1.13-20260917",
                "provider_request_id": "gen-x",
            }
            return body, parsed, 3.5

        route = JevRoute(
            provider="openrouter",
            request_model=OPENROUTER_JEV_MODEL,
            endpoint="https://example.invalid/systemone",
            price_route="openrouter",
            api_key_env="OPENROUTER_API_KEY",
        )
        with tempfile.TemporaryDirectory() as tmp:
            cache_root = Path(tmp) / "cache"
            ledger = Path(tmp) / "ledger.jsonl"
            capture = Path(tmp) / "captured.json"
            first = get_or_score_pair(
                code_change="A",
                candidate_test="B",
                route=route,
                cache_root=cache_root,
                ledger_path=ledger,
                capture_path=capture,
                call_fn=fake_call,
                metadata={"qualified_id": "Cli-30", "test_class": "t.T"},
            )
            self.assertFalse(first.from_cache)
            self.assertEqual(first.score, 0.77)
            self.assertEqual(calls["n"], 1)
            self.assertTrue(capture.is_file())
            captured = json.loads(capture.read_text(encoding="utf-8"))
            self.assertEqual(
                sorted(captured["request_body"]["state"].keys()),
                ["candidate_test", "code_change"],
            )

            second = get_or_score_pair(
                code_change="A",
                candidate_test="B",
                route=route,
                cache_root=cache_root,
                ledger_path=ledger,
                call_fn=fake_call,
            )
            self.assertTrue(second.from_cache)
            self.assertEqual(calls["n"], 1)
            key = semantic_cache_key(
                provider="openrouter",
                model_id=OPENROUTER_JEV_MODEL,
                prompt_version=JEV_PROMPT_VERSION,
                state=build_jev_state(code_change="A", candidate_test="B"),
                question=build_jev_question(),
            )
            self.assertIsNotNone(load_score_cache(key, kind="jev", cache_root=cache_root))

    def test_failure_does_not_create_score(self) -> None:
        def boom() -> tuple[dict[str, Any], dict[str, Any], float]:
            raise JevRankerError("simulated failure")

        route = JevRoute(
            provider="openrouter",
            request_model=OPENROUTER_JEV_MODEL,
            endpoint="https://example.invalid/systemone",
            price_route="openrouter",
            api_key_env="OPENROUTER_API_KEY",
        )
        with tempfile.TemporaryDirectory() as tmp:
            cache_root = Path(tmp) / "cache"
            with self.assertRaises(JevRankerError):
                get_or_score_pair(
                    code_change="A",
                    candidate_test="B",
                    route=route,
                    cache_root=cache_root,
                    ledger_path=Path(tmp) / "ledger.jsonl",
                    call_fn=boom,
                )
            # No success under cache/jev
            jev_dir = cache_root / "jev"
            if jev_dir.is_dir():
                self.assertEqual(list(jev_dir.glob("*.json")), [])
            self.assertTrue(list((cache_root / "failures").glob("*.json")))


if __name__ == "__main__":
    unittest.main()
