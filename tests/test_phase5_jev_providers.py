"""P5-01: Jev provider cost helpers (no network)."""

from __future__ import annotations

import unittest

from src.jev_providers import (
    OPENROUTER_JEV_MODEL,
    build_decision_record,
    build_pricing_snapshot,
    effective_input_cost_usd,
    estimate_workload_cost,
)


class CostMathTests(unittest.TestCase):
    def test_effective_cost_splits_fee(self) -> None:
        costs = effective_input_cost_usd(
            input_tokens=1_000_000,
            input_usd_per_mtok=0.042,
            platform_fee_rate=0.055,
        )
        self.assertAlmostEqual(costs["list_price_inference_usd"], 0.042, places=12)
        self.assertAlmostEqual(costs["platform_fee_usd"], 0.042 * 0.055, places=12)
        self.assertAlmostEqual(
            costs["effective_cash_if_prepaid_credits_usd"],
            0.042 * 1.055,
            places=12,
        )

    def test_typesafe_cheaper_than_openrouter_prepaid(self) -> None:
        ts = estimate_workload_cost(
            n_bugs=25,
            mean_candidates=150,
            mean_input_tokens_per_call=800,
            route="typesafe_direct",
        )
        orouter = estimate_workload_cost(
            n_bugs=25,
            mean_candidates=150,
            mean_input_tokens_per_call=800,
            route="openrouter",
        )
        self.assertTrue(ts["estimable"] and orouter["estimable"])
        self.assertLess(
            ts["effective_cash_if_prepaid_credits_usd"],
            orouter["effective_cash_if_prepaid_credits_usd"],
        )
        self.assertEqual(ts["list_price_inference_usd"], orouter["list_price_inference_usd"])


class DecisionTests(unittest.TestCase):
    def test_defaults_to_openrouter_without_typesafe(self) -> None:
        decision = build_decision_record(probe={})
        self.assertEqual(decision["selected_provider"], "openrouter")
        self.assertEqual(decision["selected_model_id"], OPENROUTER_JEV_MODEL)
        self.assertEqual(
            decision["cloudflare_status"],
            "rejected_for_evaluation_until_pin_and_price_verified",
        )
        self.assertTrue(decision["live_probe_required_before_scoring"])

    def test_prefers_typesafe_when_probe_ok(self) -> None:
        decision = build_decision_record(
            probe={
                "typesafe_direct": {"ok": True, "observed_model": "jev-1.13.0"},
                "openrouter": {"ok": True, "observed_model": OPENROUTER_JEV_MODEL},
            }
        )
        self.assertEqual(decision["selected_provider"], "typesafe_direct")
        self.assertFalse(decision["live_probe_required_before_scoring"])

    def test_pricing_snapshot_has_routes(self) -> None:
        snap = build_pricing_snapshot(decision_date="2026-09-22")
        self.assertEqual(snap["snapshot_date"], "2026-09-22")
        self.assertEqual(
            snap["jev"]["openrouter_request_model"],
            OPENROUTER_JEV_MODEL,
        )
        self.assertEqual(
            snap["jev"]["routes"]["typesafe_direct"]["input_usd_per_mtok"],
            0.042,
        )
        self.assertIsNone(snap["jev"]["routes"]["cloudflare"]["input_usd_per_mtok"])


if __name__ == "__main__":
    unittest.main()
