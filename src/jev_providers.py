"""Jev provider routes, pricing comparison, and development-only probes (P5-01).

Selected route for this experiment: **OpenRouter** with request model
``typesafe/jev-1.13`` (TypeSafe direct unavailable / waitlist). Record the
``response.model`` snapshot (e.g. ``typesafe/jev-1.13-YYYYMMDD``) for provenance.

Do not use ``jev-latest`` / ``~typesafe/jev-latest`` for evaluation. Do not claim
Cloudflare Jev inference is free from Gateway/Workers AI allowances alone.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.example_contract import WORKSPACE, atomic_write_json

# TypeSafe-native pin (used if direct access returns).
JEV_TYPESAFE_PINNED_MODEL_ID = "jev-1.13.0"
# OpenRouter request slug (maps to TypeSafe Jev 1.13).
OPENROUTER_JEV_MODEL = "typesafe/jev-1.13"
JEV_ALIAS_FORBIDDEN_FOR_EVAL = (
    "jev-latest",
    "jev-preview",
    "~typesafe/jev-latest",
)

TYPESAFE_BASE_URL = "https://api.typesafe.ai"
TYPESAFE_MODELS_PATH = "/v1/models"
TYPESAFE_SYSTEMONE_PATH = "/v1/systemone"

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_SYSTEMONE_PATH = "/systemone"

CLOUDFLARE_CATALOG_ID = "typesafe/jev"

RESULTS_DIR = WORKSPACE / "results"
PRICING_SNAPSHOT_PATH = RESULTS_DIR / "pricing_snapshot.json"
TYPESAFE_MODELS_PATH_OUT = RESULTS_DIR / "typesafe_models.json"
OPENROUTER_PROBE_PATH_OUT = RESULTS_DIR / "openrouter_jev_probe.json"
PROBE_REPORT_PATH = RESULTS_DIR / "jev_provider_probe.json"
DECISION_PATH = RESULTS_DIR / "jev_provider_decision.json"

# Development-only tiny probe (not benchmark data).
PROBE_STATE = {
    "code_change": "MODIFIED FILES:\nprobe.java\n\nPROPOSED CODE CHANGE:\n- return 1;\n+ return 2;\n",
    "candidate_test": "TEST CLASS:\nprobe.ProbeTest\n\nTEST SOURCE:\nassertEquals(1, probe());\n",
}
PROBE_QUESTION_ID = "would_detect_regression"
PROBE_NOUL = {
    "type": "noul",
    "instructions": (
        "Would this test class be likely to expose an incorrect behavioral "
        "regression caused by the proposed code change if such a regression exists?"
    ),
    "criteria": {
        "true": "The test exercises behavior affected by the change.",
        "false": "The test is unrelated to the changed behavior.",
    },
}

# Published list prices (USD per million tokens). Update via pricing_snapshot.
PUBLISHED_RATES: dict[str, dict[str, Any]] = {
    "typesafe_direct": {
        "provider": "typesafe_direct",
        "input_usd_per_mtok": 0.042,
        "output_usd_per_mtok": 0.0,
        "platform_fee_rate": 0.0,
        "sources": [
            "https://typesafe.ai/blog/introducing-system-one-models-and-jev",
            "https://api.typesafe.ai/docs",
        ],
    },
    "openrouter": {
        "provider": "openrouter",
        "input_usd_per_mtok": 0.042,
        "output_usd_per_mtok": 0.0,
        "platform_fee_rate": 0.055,  # standard credit purchase fee
        "model_slug": OPENROUTER_JEV_MODEL,
        "sources": [
            "https://openrouter.ai/typesafe/jev-1.13/api",
            "https://openrouter.ai/pricing",
            "https://openrouter.ai/docs/guides/community/typesafe-sdk",
        ],
    },
    "cloudflare": {
        "provider": "cloudflare",
        "input_usd_per_mtok": None,  # dashboard-only; do not invent
        "output_usd_per_mtok": None,
        "platform_fee_rate": 0.05,  # Unified Billing credit purchase fee
        "catalog_id": CLOUDFLARE_CATALOG_ID,
        "pinning": "unverified",
        "sources": [
            "https://developers.cloudflare.com/ai/models/typesafe/jev/",
            "https://developers.cloudflare.com/ai-gateway/features/unified-billing/",
        ],
        "notes": (
            "Public docs send Jev pricing to the Cloudflare dashboard. "
            "AI Gateway core features being free does not imply free Jev inference. "
            "Catalog id typesafe/jev is not proven to pin jev-1.13.0 for all future calls."
        ),
    },
    "openai_embedding": {
        "provider": "openai",
        "model": "text-embedding-3-small",
        "input_usd_per_mtok": 0.02,
        "output_usd_per_mtok": 0.0,
        "platform_fee_rate": 0.0,
        "sources": [
            "https://developers.openai.com/api/docs/models/text-embedding-3-small",
        ],
    },
    "openrouter_embedding": {
        "provider": "openrouter",
        "model": "text-embedding-3-small",
        "request_model": "openai/text-embedding-3-small",
        "input_usd_per_mtok": 0.02,
        "output_usd_per_mtok": 0.0,
        "platform_fee_rate": 0.055,
        "sources": [
            "https://developers.openai.com/api/docs/models/text-embedding-3-small",
            "https://openrouter.ai/pricing",
        ],
    },
    "openai_gpt": {
        "provider": "openai",
        "model": "gpt-5.4-nano-2026-03-17",
        "input_usd_per_mtok": 0.20,
        "output_usd_per_mtok": 1.25,
        "platform_fee_rate": 0.0,
        "sources": [
            "https://developers.openai.com/api/docs/models/gpt-5.4-nano",
        ],
        "notes": "List rates are planning snapshots; refresh pricing_snapshot on live runs.",
    },
    "openrouter_gpt": {
        "provider": "openrouter",
        "platform_fee_rate": 0.055,
        "sources": [
            "https://openrouter.ai/pricing",
        ],
        "notes": "Per-model rates stored on ComparisonModel; fee applies to prepaid credits.",
    },
    "openrouter_gpt_5_4_nano": {
        "provider": "openrouter",
        "model": "gpt-5.4-nano-2026-03-17",
        "request_model": "openai/gpt-5.4-nano",
        "input_usd_per_mtok": 0.20,
        "output_usd_per_mtok": 1.25,
        "platform_fee_rate": 0.055,
        "sources": [
            "https://developers.openai.com/api/docs/models/gpt-5.4-nano",
            "https://openrouter.ai/pricing",
        ],
    },
    "openrouter_gpt_4_1_nano": {
        "provider": "openrouter",
        "model": "gpt-4.1-nano-2025-04-14",
        "request_model": "openai/gpt-4.1-nano-2025-04-14",
        "input_usd_per_mtok": 0.10,
        "output_usd_per_mtok": 0.40,
        "platform_fee_rate": 0.055,
        "sources": [
            "https://openrouter.ai/pricing",
        ],
    },
    "openrouter_gpt_4o_mini": {
        "provider": "openrouter",
        "model": "gpt-4o-mini-2024-07-18",
        "request_model": "openai/gpt-4o-mini-2024-07-18",
        "input_usd_per_mtok": 0.15,
        "output_usd_per_mtok": 0.60,
        "platform_fee_rate": 0.055,
        "sources": [
            "https://openrouter.ai/pricing",
        ],
    },
    "openrouter_gpt_luna": {
        "provider": "openrouter",
        "model": "gpt-5.6-luna",
        "request_model": "openai/gpt-5.6-luna",
        "input_usd_per_mtok": 0.20,
        "output_usd_per_mtok": 1.20,
        "platform_fee_rate": 0.055,
        "sources": [
            "https://developers.openai.com/api/docs/models/gpt-5.6-luna",
            "https://openrouter.ai/openai/gpt-5.6-luna",
        ],
    },
}


class ProviderError(Exception):
    """Provider probe or configuration failure."""


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _redact_auth(headers: Mapping[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in headers.items():
        if key.lower() in {"authorization", "x-api-key"}:
            out[key] = "Bearer ***"
        else:
            out[key] = value
    return out


def effective_input_cost_usd(
    *,
    input_tokens: int,
    input_usd_per_mtok: float,
    platform_fee_rate: float = 0.0,
) -> dict[str, float]:
    """Split list-price inference cost from platform credit fees."""
    if input_tokens < 0:
        raise ProviderError("input_tokens must be nonnegative")
    list_price = (input_tokens / 1_000_000.0) * input_usd_per_mtok
    fee = list_price * platform_fee_rate
    return {
        "list_price_inference_usd": list_price,
        "platform_fee_usd": fee,
        "effective_cash_if_prepaid_credits_usd": list_price + fee,
    }


def estimate_workload_cost(
    *,
    n_bugs: int,
    mean_candidates: float,
    mean_input_tokens_per_call: float,
    route: str,
) -> dict[str, Any]:
    """Rough development/evaluation spend from measured probe tokens."""
    rates = PUBLISHED_RATES[route]
    if rates.get("input_usd_per_mtok") is None:
        return {
            "route": route,
            "estimable": False,
            "reason": "published input rate unavailable (dashboard-only)",
        }
    calls = n_bugs * mean_candidates
    tokens = calls * mean_input_tokens_per_call
    costs = effective_input_cost_usd(
        input_tokens=int(math.ceil(tokens)),
        input_usd_per_mtok=float(rates["input_usd_per_mtok"]),
        platform_fee_rate=float(rates.get("platform_fee_rate") or 0.0),
    )
    return {
        "route": route,
        "estimable": True,
        "n_bugs": n_bugs,
        "mean_candidates": mean_candidates,
        "mean_input_tokens_per_call": mean_input_tokens_per_call,
        "estimated_calls": calls,
        "estimated_input_tokens": tokens,
        **costs,
        "input_usd_per_mtok": rates["input_usd_per_mtok"],
        "platform_fee_rate": rates.get("platform_fee_rate") or 0.0,
    }


def build_pricing_snapshot(*, decision_date: str | None = None) -> dict[str, Any]:
    """Dated published-price snapshot (not historical cash outlay)."""
    when = decision_date or _utcnow()[:10]
    return {
        "snapshot_date": when,
        "created_at": _utcnow(),
        "currency": "USD",
        "notes": (
            "Published list prices from primary docs on snapshot_date. "
            "Confirm account-specific rates before paid scoring. "
            "Separate list-price inference, platform fees, and promotional cash."
        ),
        "jev": {
            "openrouter_request_model": OPENROUTER_JEV_MODEL,
            "typesafe_direct_model": JEV_TYPESAFE_PINNED_MODEL_ID,
            "forbidden_eval_aliases": list(JEV_ALIAS_FORBIDDEN_FOR_EVAL),
            "routes": {
                "typesafe_direct": PUBLISHED_RATES["typesafe_direct"],
                "openrouter": PUBLISHED_RATES["openrouter"],
                "cloudflare": PUBLISHED_RATES["cloudflare"],
            },
        },
        "openai": {
            "embedding": PUBLISHED_RATES["openai_embedding"],
            "gpt": PUBLISHED_RATES["openai_gpt"],
        },
        "workload_estimates": {
            "assumptions": {
                "development_bugs": 25,
                "evaluation_bugs": 125,
                "mean_candidates_per_bug": 150.0,
                "mean_input_tokens_per_jev_call": 800.0,
                "note": "Replace mean_input_tokens with measured probe usage when available.",
            },
            "development": {
                "typesafe_direct": estimate_workload_cost(
                    n_bugs=25,
                    mean_candidates=150.0,
                    mean_input_tokens_per_call=800.0,
                    route="typesafe_direct",
                ),
                "openrouter": estimate_workload_cost(
                    n_bugs=25,
                    mean_candidates=150.0,
                    mean_input_tokens_per_call=800.0,
                    route="openrouter",
                ),
                "cloudflare": estimate_workload_cost(
                    n_bugs=25,
                    mean_candidates=150.0,
                    mean_input_tokens_per_call=800.0,
                    route="cloudflare",
                ),
            },
            "evaluation": {
                "typesafe_direct": estimate_workload_cost(
                    n_bugs=125,
                    mean_candidates=150.0,
                    mean_input_tokens_per_call=800.0,
                    route="typesafe_direct",
                ),
                "openrouter": estimate_workload_cost(
                    n_bugs=125,
                    mean_candidates=150.0,
                    mean_input_tokens_per_call=800.0,
                    route="openrouter",
                ),
            },
        },
    }


def build_decision_record(*, probe: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Provider comparison + selected route for Phase 5/6 freeze."""
    probe = probe or {}
    typesafe_ok = bool((probe.get("typesafe_direct") or {}).get("ok"))
    openrouter_ok = bool((probe.get("openrouter") or {}).get("ok"))
    openrouter_probe = probe.get("openrouter") or {}

    if typesafe_ok:
        selected_provider = "typesafe_direct"
        selected_endpoint = f"{TYPESAFE_BASE_URL}{TYPESAFE_SYSTEMONE_PATH}"
        selected_model = JEV_TYPESAFE_PINNED_MODEL_ID
        observed = (probe.get("typesafe_direct") or {}).get("observed_model")
        rationale_extra = "TypeSafe direct account available; preferred (no platform fee)."
    else:
        selected_provider = "openrouter"
        selected_endpoint = f"{OPENROUTER_BASE_URL}{OPENROUTER_SYSTEMONE_PATH}"
        selected_model = OPENROUTER_JEV_MODEL
        observed = openrouter_probe.get("observed_model")
        rationale_extra = (
            "TypeSafe direct unavailable (cannot join / no API key). "
            "OpenRouter is the next-best verified route with Noul + usage."
        )

    return {
        "decision_date": _utcnow()[:10],
        "created_at": _utcnow(),
        "selected_provider": selected_provider,
        "selected_endpoint": selected_endpoint,
        "selected_model_id": selected_model,
        "observed_model_id": observed,
        "selected_model_alias_policy": (
            f"Request {selected_model}; never {list(JEV_ALIAS_FORBIDDEN_FOR_EVAL)} "
            "for evaluation; record response.model snapshot each run"
        ),
        "rationale": [
            rationale_extra,
            "Published input rate $0.042/MTok with free output on TypeSafe and OpenRouter.",
            "OpenRouter standard credits add 5.5% platform fee on prepaid cash.",
            "Cloudflare catalog id typesafe/jev does not document an immutable pin API; "
            "dashboard-only pricing; rejected for evaluation until both are verified.",
        ],
        "unavailable_preferred": {
            "provider": "typesafe_direct",
            "reason": "account access blocked / waitlist; no TYPESAFE_API_KEY",
        }
        if not typesafe_ok
        else None,
        "fallback_provider": "openrouter" if typesafe_ok else None,
        "cloudflare_status": "rejected_for_evaluation_until_pin_and_price_verified",
        "do_not_claim": [
            "Cloudflare Jev inference is free because AI Gateway or Workers AI has free tiers",
        ],
        "live_probe_required_before_scoring": not (typesafe_ok or openrouter_ok),
        "probe_summary": {
            "typesafe_direct_ok": typesafe_ok,
            "openrouter_ok": openrouter_ok,
            "cloudflare_ok": bool((probe.get("cloudflare") or {}).get("ok")),
        },
        "primary_sources": [
            "https://typesafe.ai/blog/introducing-system-one-models-and-jev",
            "https://api.typesafe.ai/docs",
            "https://api.typesafe.ai/openapi.json",
            "https://openrouter.ai/typesafe/jev-1.13/api",
            "https://openrouter.ai/docs/guides/community/typesafe-sdk",
            "https://openrouter.ai/pricing",
            "https://developers.cloudflare.com/ai/models/typesafe/jev/",
            "https://developers.cloudflare.com/ai-gateway/features/unified-billing/",
        ],
    }


def _http_json(
    method: str,
    url: str,
    *,
    headers: Mapping[str, str],
    body: Mapping[str, Any] | None = None,
    timeout_s: float = 60.0,
) -> tuple[int, dict[str, Any] | list[Any] | str]:
    data = None
    req_headers = dict(headers)
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        req_headers.setdefault("Content-Type", "application/json")
    request = urllib.request.Request(url, data=data, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as resp:
            raw = resp.read().decode("utf-8")
            status = getattr(resp, "status", 200)
            try:
                return status, json.loads(raw)
            except json.JSONDecodeError:
                return status, raw
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload: dict[str, Any] | list[Any] | str = json.loads(raw)
        except json.JSONDecodeError:
            payload = raw
        return int(exc.code), payload
    except urllib.error.URLError as exc:
        raise ProviderError(f"network error calling {url}: {exc}") from exc


def _validate_noul_systemone_response(
    resp: Mapping[str, Any],
    *,
    requested_model: str,
) -> dict[str, Any]:
    answers = resp.get("answers") or {}
    answer = answers.get(PROBE_QUESTION_ID) or {}
    noul = answer.get("noul")
    usage = resp.get("usage") or {}
    observed_model = resp.get("model")
    if answer.get("type") != "noul":
        raise ProviderError(f"expected noul answer, got {answer!r}")
    if not isinstance(noul, (int, float)) or not math.isfinite(float(noul)):
        raise ProviderError(f"noul not finite: {noul!r}")
    if not (0.0 <= float(noul) <= 1.0):
        raise ProviderError(f"noul out of [0,1]: {noul}")
    if not isinstance(usage.get("input_tokens"), int):
        raise ProviderError(f"missing usage.input_tokens: {usage!r}")
    observed_ok = isinstance(observed_model, str) and (
        "jev-1.13" in observed_model or observed_model == requested_model
    )
    return {
        "observed_model": observed_model,
        "requested_model": requested_model,
        "noul": float(noul),
        "usage": usage,
        "provider_response_id": resp.get("id"),
        "upstream_provider": resp.get("provider"),
        "response_model_pinned_ok": observed_ok,
    }


def probe_typesafe_direct(*, api_key: str) -> dict[str, Any]:
    """Development-only models list + one Noul probe on TypeSafe direct."""
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    models_url = f"{TYPESAFE_BASE_URL}{TYPESAFE_MODELS_PATH}"
    status, models_body = _http_json("GET", models_url, headers=headers)
    result: dict[str, Any] = {
        "provider": "typesafe_direct",
        "ok": False,
        "models_http_status": status,
        "request_headers_redacted": _redact_auth(headers),
    }
    if status != 200 or not isinstance(models_body, dict):
        result["error"] = f"GET /v1/models failed: status={status} body={models_body!r}"
        return result

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    atomic_write_json(TYPESAFE_MODELS_PATH_OUT, models_body)
    result["models_path"] = str(TYPESAFE_MODELS_PATH_OUT.relative_to(WORKSPACE))
    result["models"] = models_body

    body = {
        "model": JEV_TYPESAFE_PINNED_MODEL_ID,
        "state": PROBE_STATE,
        "questions": {PROBE_QUESTION_ID: PROBE_NOUL},
    }
    result["preflight_cost_estimate_usd"] = effective_input_cost_usd(
        input_tokens=200,
        input_usd_per_mtok=0.042,
        platform_fee_rate=0.0,
    )

    sys_url = f"{TYPESAFE_BASE_URL}{TYPESAFE_SYSTEMONE_PATH}"
    status2, resp = _http_json("POST", sys_url, headers=headers, body=body)
    result["systemone_http_status"] = status2
    if status2 != 200 or not isinstance(resp, dict):
        result["error"] = f"POST /v1/systemone failed: status={status2} body={resp!r}"
        return result
    try:
        validated = _validate_noul_systemone_response(
            resp, requested_model=JEV_TYPESAFE_PINNED_MODEL_ID
        )
    except ProviderError as exc:
        result["error"] = str(exc)
        return result
    result.update({"ok": True, **validated})
    return result


def probe_openrouter(*, api_key: str) -> dict[str, Any]:
    """Development-only Noul probe via OpenRouter System One API."""
    if not api_key:
        return {
            "provider": "openrouter",
            "ok": False,
            "skipped": True,
            "reason": "OPENROUTER_API_KEY not set",
            "api_key_present": False,
        }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "HTTP-Referer": "https://github.com/jev-ci-test-selection",
        "X-OpenRouter-Title": "jev-ci",
    }
    result: dict[str, Any] = {
        "provider": "openrouter",
        "ok": False,
        "request_headers_redacted": _redact_auth(headers),
        "endpoint": f"{OPENROUTER_BASE_URL}{OPENROUTER_SYSTEMONE_PATH}",
    }
    result["preflight_cost_estimate_usd"] = effective_input_cost_usd(
        input_tokens=200,
        input_usd_per_mtok=0.042,
        platform_fee_rate=0.055,
    )

    body = {
        "model": OPENROUTER_JEV_MODEL,
        "state": PROBE_STATE,
        "questions": {PROBE_QUESTION_ID: PROBE_NOUL},
    }
    status, resp = _http_json(
        "POST",
        f"{OPENROUTER_BASE_URL}{OPENROUTER_SYSTEMONE_PATH}",
        headers=headers,
        body=body,
    )
    result["systemone_http_status"] = status
    if status != 200 or not isinstance(resp, dict):
        result["error"] = (
            f"POST /api/v1/systemone failed: status={status} body={resp!r}"
        )
        return result

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        OPENROUTER_PROBE_PATH_OUT,
        {
            "fetched_at": _utcnow(),
            "requested_model": OPENROUTER_JEV_MODEL,
            "response": resp,
        },
    )
    result["probe_path"] = str(OPENROUTER_PROBE_PATH_OUT.relative_to(WORKSPACE))

    try:
        validated = _validate_noul_systemone_response(
            resp, requested_model=OPENROUTER_JEV_MODEL
        )
    except ProviderError as exc:
        result["error"] = str(exc)
        return result
    result.update({"ok": True, **validated})
    return result


def probe_cloudflare(*, api_token: str, account_id: str) -> dict[str, Any]:
    return {
        "provider": "cloudflare",
        "ok": False,
        "skipped": True,
        "reason": (
            "Rejected for evaluation until dashboard Jev price and immutable underlying "
            f"model pin for {CLOUDFLARE_CATALOG_ID} are verified on-account. "
            "Do not infer free inference from free Gateway features."
        ),
        "api_token_present": bool(api_token),
        "account_id_present": bool(account_id),
    }


def run_provider_verification(*, allow_paid_probe: bool = True) -> dict[str, Any]:
    """Compare routes, write pricing/decision artifacts, optionally live-probe."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    pricing = build_pricing_snapshot()
    atomic_write_json(PRICING_SNAPSHOT_PATH, pricing)

    typesafe_key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    openrouter_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    cf_token = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
    cf_account = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()

    probes: dict[str, Any] = {}
    if allow_paid_probe and typesafe_key:
        probes["typesafe_direct"] = probe_typesafe_direct(api_key=typesafe_key)
    else:
        probes["typesafe_direct"] = {
            "provider": "typesafe_direct",
            "ok": False,
            "skipped": True,
            "reason": (
                "TYPESAFE_API_KEY not set / TypeSafe direct unavailable "
                "(waitlist or no account access)"
            ),
        }

    if allow_paid_probe and openrouter_key:
        probes["openrouter"] = probe_openrouter(api_key=openrouter_key)
    else:
        probes["openrouter"] = probe_openrouter(api_key="")

    probes["cloudflare"] = probe_cloudflare(api_token=cf_token, account_id=cf_account)

    decision = build_decision_record(probe=probes)
    atomic_write_json(DECISION_PATH, decision)

    selected = decision["selected_provider"]
    ready = bool((probes.get(selected) or {}).get("ok"))

    report = {
        "created_at": _utcnow(),
        "pricing_snapshot": str(PRICING_SNAPSHOT_PATH.relative_to(WORKSPACE)),
        "decision": str(DECISION_PATH.relative_to(WORKSPACE)),
        "typesafe_models": str(TYPESAFE_MODELS_PATH_OUT.relative_to(WORKSPACE))
        if TYPESAFE_MODELS_PATH_OUT.is_file()
        else None,
        "openrouter_probe": str(OPENROUTER_PROBE_PATH_OUT.relative_to(WORKSPACE))
        if OPENROUTER_PROBE_PATH_OUT.is_file()
        else None,
        "probes": probes,
        "selected_provider": selected,
        "selected_model_id": decision["selected_model_id"],
        "observed_model_id": decision.get("observed_model_id"),
        "ready_for_scoring": ready,
    }
    atomic_write_json(PROBE_REPORT_PATH, report)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify Jev provider routes and write pricing/decision artifacts (P5-01)",
    )
    parser.add_argument(
        "--no-paid-probe",
        action="store_true",
        help="Only write pricing/decision from published sources (no live API calls)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = run_provider_verification(allow_paid_probe=not args.no_paid_probe)
    except ProviderError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(
        f"jev providers: selected={report['selected_provider']} "
        f"model={report['selected_model_id']} "
        f"observed={report.get('observed_model_id')} "
        f"ready_for_scoring={report['ready_for_scoring']} "
        f"decision={report['decision']}",
        flush=True,
    )
    selected = report["selected_provider"]
    probe = report["probes"].get(selected) or {}
    if probe.get("skipped"):
        print(f"  {selected} probe skipped: {probe.get('reason')}", flush=True)
        return 0
    if not probe.get("ok"):
        print(f"  {selected} probe failed: {probe.get('error')}", file=sys.stderr)
        return 1
    print(
        f"  {selected} probe ok: observed_model={probe.get('observed_model')} "
        f"noul={probe.get('noul')} usage={probe.get('usage')}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
