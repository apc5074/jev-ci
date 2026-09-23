"""Generative LLM comparison clients (Phase 5 / P5-06).

Preregistered primary baseline (overall.md §20):

    gpt-5.4-nano-2026-03-17  +  reasoning.effort=none  → ranking name GPT-Nano

Additional Phase-5 comparison models (same prompt/schema/state; separate
cache keys and ranking names for Phase 6 review):

    gpt-4.1-nano-2025-04-14  → GPT-4.1-Nano
    gpt-4o-mini-2024-07-18   → GPT-4o-mini
    gpt-5.6-luna             → GPT-Luna

One request per BM25-shortlisted test class. Patch/test strings match Jev
byte-for-byte. Structured output is ``{"probability": <float in [0,1]>}``.
No chain-of-thought is requested or stored. Malformed / out-of-range values
are rejected (never coerced).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.candidates import load_candidates
from src.embeddings import (
    load_patch_representation_text,
    load_test_representation_texts,
)
from src.example_contract import (
    WORKSPACE,
    ExampleId,
    FORBIDDEN_MODEL_TOKENS,
    PRIVATE_LABEL_FIELDS,
    atomic_write_json,
    load_manifest,
    require_manifest_membership,
)
from src.jev_providers import OPENROUTER_BASE_URL, PUBLISHED_RATES
from src.jev_ranker import redact_secrets
from src.semantic_cache import (
    GPT_PROMPT_VERSION,
    GPT_RESPONSE_JSON_SCHEMA,
    GPT_TASK_INSTRUCTION,
    append_usage_ledger,
    build_failure_entry,
    build_gpt_question,
    build_jev_state,
    build_success_score_entry,
    cost_breakdown_from_usage,
    default_price_basis,
    load_score_cache,
    semantic_cache_key,
    write_cache_entry,
)
from src.semantic_scheduler import (
    MAX_CONCURRENCY,
    RETRYABLE_HTTP_STATUSES,
    RetryableError,
    ScoreJob,
    SpendController,
    estimate_spend,
    parse_retry_after_seconds,
    run_score_batch,
    with_retries,
)

RESULTS_DIR = WORKSPACE / "results"
CAPTURED_REQUEST_PATH = RESULTS_DIR / "gpt_captured_request.json"
COMPARISON_MODELS_PATH = RESULTS_DIR / "gpt_comparison_models.json"
GPT_RANKER_VERSION = "gpt-ranker-v1"

OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"
OPENROUTER_CHAT_URL = f"{OPENROUTER_BASE_URL}/chat/completions"


@dataclass(frozen=True)
class ComparisonModel:
    """One generative comparison model under the shared GPT prompt contract."""

    key: str
    canonical_model_id: str
    openrouter_request_model: str
    openai_request_model: str
    ranking_name: str
    price_route: str
    reasoning_effort: str | None
    is_primary: bool
    notes: str = ""


# Locked Phase-5 comparison set. Primary remains overall.md GPT-Nano.
COMPARISON_MODELS: tuple[ComparisonModel, ...] = (
    ComparisonModel(
        key="gpt-5.4-nano",
        canonical_model_id="gpt-5.4-nano-2026-03-17",
        openrouter_request_model="openai/gpt-5.4-nano",
        openai_request_model="gpt-5.4-nano-2026-03-17",
        ranking_name="GPT-Nano",
        price_route="openrouter_gpt_5_4_nano",
        reasoning_effort="none",
        is_primary=True,
        notes=(
            "Preregistered baseline (overall.md §20). OpenRouter slug lacks the "
            "dated snapshot id; record response.model each call."
        ),
    ),
    ComparisonModel(
        key="gpt-4.1-nano",
        canonical_model_id="gpt-4.1-nano-2025-04-14",
        openrouter_request_model="openai/gpt-4.1-nano-2025-04-14",
        openai_request_model="gpt-4.1-nano-2025-04-14",
        ranking_name="GPT-4.1-Nano",
        price_route="openrouter_gpt_4_1_nano",
        reasoning_effort=None,
        is_primary=False,
        notes="Additional cheap nano-class comparator (pinned snapshot).",
    ),
    ComparisonModel(
        key="gpt-4o-mini",
        canonical_model_id="gpt-4o-mini-2024-07-18",
        openrouter_request_model="openai/gpt-4o-mini-2024-07-18",
        openai_request_model="gpt-4o-mini-2024-07-18",
        ranking_name="GPT-4o-mini",
        price_route="openrouter_gpt_4o_mini",
        reasoning_effort=None,
        is_primary=False,
        notes="Additional small generative comparator (pinned snapshot).",
    ),
    ComparisonModel(
        key="gpt-luna",
        canonical_model_id="gpt-5.6-luna",
        openrouter_request_model="openai/gpt-5.6-luna",
        openai_request_model="gpt-5.6-luna",
        ranking_name="GPT-Luna",
        price_route="openrouter_gpt_luna",
        reasoning_effort="none",
        is_primary=False,
        notes=(
            "GPT-5.6 Luna (nano-tier successor). Do not use ~openai/gpt-luna-latest; "
            "record response.model each call."
        ),
    ),
)


class GptRankerError(Exception):
    """GPT comparison scoring failure."""


@dataclass(frozen=True)
class GptRoute:
    provider: str
    chat_url: str
    api_key_env: str


@dataclass(frozen=True)
class GptScoreResult:
    score: float
    cache_key: str
    provider: str
    model_id: str
    request_model: str
    observed_model_id: str | None
    ranking_name: str
    usage: Mapping[str, Any]
    latency_ms: float | None
    provider_request_id: str | None
    from_cache: bool
    entry: Mapping[str, Any]


def primary_comparison_model() -> ComparisonModel:
    for model in COMPARISON_MODELS:
        if model.is_primary:
            return model
    raise GptRankerError("no primary comparison model configured")


def get_comparison_model(key: str) -> ComparisonModel:
    for model in COMPARISON_MODELS:
        if model.key == key or model.canonical_model_id == key:
            return model
    raise GptRankerError(
        f"unknown comparison model {key!r}; "
        f"choose from {[m.key for m in COMPARISON_MODELS]}"
    )


def resolve_gpt_route(*, prefer: str | None = None) -> GptRoute:
    choice = (prefer or "auto").strip().lower()
    openai_key = bool(os.environ.get("OPENAI_API_KEY"))
    openrouter_key = bool(os.environ.get("OPENROUTER_API_KEY"))
    if choice in {"", "auto"}:
        if openai_key:
            choice = "openai"
        elif openrouter_key:
            choice = "openrouter"
        else:
            raise GptRankerError("need OPENAI_API_KEY or OPENROUTER_API_KEY")
    if choice == "openai":
        if not openai_key:
            raise GptRankerError("OPENAI_API_KEY not set")
        return GptRoute(
            provider="openai",
            chat_url=OPENAI_CHAT_URL,
            api_key_env="OPENAI_API_KEY",
        )
    if choice == "openrouter":
        if not openrouter_key:
            raise GptRankerError("OPENROUTER_API_KEY not set")
        return GptRoute(
            provider="openrouter",
            chat_url=OPENROUTER_CHAT_URL,
            api_key_env="OPENROUTER_API_KEY",
        )
    raise GptRankerError(f"unknown GPT provider prefer={prefer!r}")


def request_model_for(model: ComparisonModel, route: GptRoute) -> str:
    if route.provider == "openai":
        return model.openai_request_model
    return model.openrouter_request_model


def price_route_for(model: ComparisonModel, route: GptRoute) -> str:
    if route.provider == "openai" and model.is_primary:
        return "openai_gpt"
    return model.price_route


def build_gpt_messages(
    *,
    code_change: str,
    candidate_test: str,
    question: Mapping[str, Any] | None = None,
) -> list[dict[str, str]]:
    """Chat messages. Patch/test payloads are exact Phase-3 representation strings."""
    q = question or build_gpt_question()
    rubric = (
        "RUBRIC INSTRUCTIONS:\n"
        f"{q['instructions']}\n\n"
        "RUBRIC CRITERIA (true):\n"
        f"{q['criteria']['true']}\n\n"
        "RUBRIC CRITERIA (false):\n"
        f"{q['criteria']['false']}"
    )
    system = (
        f"{q.get('task_instruction') or GPT_TASK_INSTRUCTION}\n\n"
        f"{rubric}\n\n"
        "Do not include chain-of-thought. Return only the structured probability object."
    )
    user = (
        "CODE_CHANGE:\n"
        f"{code_change}\n\n"
        "CANDIDATE_TEST:\n"
        f"{candidate_test}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def build_chat_body(
    *,
    model: ComparisonModel,
    route: GptRoute,
    code_change: str,
    candidate_test: str,
) -> dict[str, Any]:
    messages = build_gpt_messages(
        code_change=code_change, candidate_test=candidate_test
    )
    body: dict[str, Any] = {
        "model": request_model_for(model, route),
        "messages": messages,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "would_detect_regression_probability",
                "strict": True,
                "schema": dict(GPT_RESPONSE_JSON_SCHEMA),
            },
        },
        "temperature": 0,
    }
    if model.reasoning_effort is not None:
        # OpenRouter / OpenAI chat: reasoning.effort=none for GPT-5.4 nano.
        body["reasoning"] = {"effort": model.reasoning_effort}
    return body


def assert_gpt_request_contract(
    *,
    body: Mapping[str, Any],
    code_change: str,
    candidate_test: str,
) -> None:
    messages = body.get("messages") or []
    if len(messages) != 2:
        raise GptRankerError(f"expected 2 chat messages, got {len(messages)}")
    user = messages[1].get("content") or ""
    if code_change not in user or candidate_test not in user:
        raise GptRankerError(
            "request user message missing exact patch/test representation bytes"
        )
    # Ensure only one pair of payloads (no second candidate block).
    if user.count("CODE_CHANGE:\n") != 1 or user.count("CANDIDATE_TEST:\n") != 1:
        raise GptRankerError("request must contain exactly one CODE_CHANGE/CANDIDATE_TEST pair")
    blob = json.dumps({"model": body.get("model"), "roles": [m.get("role") for m in messages]})
    for field in PRIVATE_LABEL_FIELDS:
        if f'"{field}"' in blob:
            raise GptRankerError(f"private label field {field!r} in request envelope")
    for token in FORBIDDEN_MODEL_TOKENS:
        if token.lower() in blob.lower():
            raise GptRankerError(f"forbidden pipeline token {token!r} in request envelope")
    # No CoT request fields.
    if body.get("reasoning") and body["reasoning"].get("effort") not in {None, "none"}:
        raise GptRankerError("refusing non-none reasoning effort for comparison scoring")


def parse_probability(response: Mapping[str, Any]) -> dict[str, Any]:
    choices = response.get("choices") or []
    if not choices:
        raise GptRankerError(f"no choices in GPT response: {response!r}")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if message.get("refusal"):
        raise GptRankerError(f"model refused: {message.get('refusal')!r}")
    if not isinstance(content, str) or not content.strip():
        raise GptRankerError(f"empty GPT content: {message!r}")
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise GptRankerError(
            f"GPT content is not JSON (no coerce): {content[:200]!r}"
        ) from exc
    if not isinstance(parsed, dict) or set(parsed.keys()) != {"probability"}:
        raise GptRankerError(
            f"expected sole key probability, got {parsed!r}"
        )
    prob = parsed.get("probability")
    if not isinstance(prob, (int, float)) or isinstance(prob, bool):
        raise GptRankerError(f"probability not numeric: {prob!r}")
    score = float(prob)
    if not math.isfinite(score) or not (0.0 <= score <= 1.0):
        raise GptRankerError(f"probability out of [0,1] or non-finite: {score}")

    usage_raw = response.get("usage") or {}
    input_tokens = usage_raw.get("prompt_tokens")
    output_tokens = usage_raw.get("completion_tokens")
    if type(input_tokens) is not int or input_tokens < 0:
        raise GptRankerError(f"bad usage.prompt_tokens: {usage_raw!r}")
    if type(output_tokens) is not int or output_tokens < 0:
        raise GptRankerError(f"bad usage.completion_tokens: {usage_raw!r}")
    details = usage_raw.get("prompt_tokens_details") or {}
    cached = details.get("cached_tokens")
    return {
        "score": score,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cached_input_tokens": cached if isinstance(cached, int) else None,
            "cost": usage_raw.get("cost"),
        },
        "observed_model_id": response.get("model"),
        "provider_request_id": response.get("id"),
    }


def _http_chat(
    *,
    route: GptRoute,
    body: Mapping[str, Any],
    timeout_s: float = 120.0,
) -> tuple[dict[str, Any], float, str | None]:
    api_key = os.environ.get(route.api_key_env)
    if not api_key:
        raise GptRankerError(f"{route.api_key_env} not set")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if route.provider == "openrouter":
        headers["HTTP-Referer"] = "https://github.com/jev-ci-test-selection"
        headers["X-OpenRouter-Title"] = "jev-ci"

    payload = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        route.chat_url, data=payload, headers=headers, method="POST"
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as resp:
            raw = resp.read().decode("utf-8")
            request_id = resp.headers.get("x-request-id") or resp.headers.get(
                "X-Request-Id"
            )
            status = int(getattr(resp, "status", 200))
    except urllib.error.HTTPError as exc:
        err = exc.read().decode("utf-8", errors="replace")
        redacted = redact_secrets(err)
        message = f"GPT HTTP {exc.code}: {redacted[:500]}"
        raw_ra = exc.headers.get("Retry-After") if exc.headers else None
        retry_after = None
        if raw_ra:
            try:
                retry_after = float(raw_ra)
            except ValueError:
                retry_after = parse_retry_after_seconds(redacted)
        else:
            retry_after = parse_retry_after_seconds(redacted)
        if int(exc.code) in RETRYABLE_HTTP_STATUSES:
            raise RetryableError(
                message, http_status=int(exc.code), retry_after_s=retry_after
            ) from None
        raise GptRankerError(message) from None
    except urllib.error.URLError as exc:
        raise RetryableError(
            f"GPT transport error: {redact_secrets(str(exc.reason))}"
        ) from None
    latency_ms = (time.perf_counter() - started) * 1000.0
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GptRankerError(f"invalid GPT JSON: {exc}") from exc
    if status != 200 or not isinstance(data, dict):
        raise GptRankerError(
            f"GPT call failed: status={status} body={redact_secrets(str(data))[:400]}"
        )
    return data, latency_ms, request_id


def call_gpt_chat(
    *,
    model: ComparisonModel,
    route: GptRoute,
    code_change: str,
    candidate_test: str,
) -> tuple[dict[str, Any], dict[str, Any], float]:
    body = build_chat_body(
        model=model,
        route=route,
        code_change=code_change,
        candidate_test=candidate_test,
    )
    assert_gpt_request_contract(
        body=body, code_change=code_change, candidate_test=candidate_test
    )
    resp, latency_ms, _ = _http_chat(route=route, body=body)
    parsed = parse_probability(resp)
    return body, parsed, latency_ms


def get_or_score_pair(
    *,
    code_change: str,
    candidate_test: str,
    model: ComparisonModel | str | None = None,
    route: GptRoute | None = None,
    cache_root: Path | None = None,
    ledger_path: Path | None = None,
    metadata: Mapping[str, Any] | None = None,
    capture_path: Path | None = None,
    call_fn: Callable[..., tuple[dict[str, Any], dict[str, Any], float]] | None = None,
    max_retries: int = 3,
) -> GptScoreResult:
    resolved_model = (
        primary_comparison_model()
        if model is None
        else model
        if isinstance(model, ComparisonModel)
        else get_comparison_model(model)
    )
    resolved_route = route or resolve_gpt_route()
    req_model = request_model_for(resolved_model, resolved_route)
    # Cache by canonical snapshot id so OpenAI/OpenRouter share semantic identity
    # only when the same provider is used (provider is part of the key).
    cache_model_id = resolved_model.canonical_model_id

    state = build_jev_state(code_change=code_change, candidate_test=candidate_test)
    question = build_gpt_question()
    cache_key = semantic_cache_key(
        provider=resolved_route.provider,
        model_id=cache_model_id,
        prompt_version=GPT_PROMPT_VERSION,
        state=state,
        question=question,
    )

    cached = load_score_cache(cache_key, kind="gpt", cache_root=cache_root)
    if cached is not None:
        return GptScoreResult(
            score=float(cached["score"]),
            cache_key=cache_key,
            provider=str(cached["provider"]),
            model_id=str(cached["model_id"]),
            request_model=req_model,
            observed_model_id=cached.get("observed_model_id"),
            ranking_name=resolved_model.ranking_name,
            usage=cached.get("usage") or {},
            latency_ms=cached.get("latency_ms"),
            provider_request_id=cached.get("provider_request_id"),
            from_cache=True,
            entry=cached,
        )

    caller = call_fn or (
        lambda: call_gpt_chat(
            model=resolved_model,
            route=resolved_route,
            code_change=code_change,
            candidate_test=candidate_test,
        )
    )
    try:
        body, parsed, latency_ms = with_retries(caller, max_retries=max_retries)
    except Exception as exc:  # noqa: BLE001
        failure = build_failure_entry(
            cache_key=cache_key,
            kind="gpt",
            provider=resolved_route.provider,
            model_id=cache_model_id,
            prompt_version=GPT_PROMPT_VERSION,
            error=redact_secrets(str(exc)),
            metadata={
                **dict(metadata or {}),
                "ranking_name": resolved_model.ranking_name,
                "request_model": req_model,
            },
        )
        write_cache_entry(failure, kind="failure", cache_root=cache_root)
        if isinstance(exc, RetryableError):
            raise
        raise GptRankerError(redact_secrets(str(exc))) from None

    if capture_path is not None:
        capture_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(
            capture_path,
            {
                "schema_version": "gpt-captured-request-v1",
                "ranker_version": GPT_RANKER_VERSION,
                "prompt_version": GPT_PROMPT_VERSION,
                "provider": resolved_route.provider,
                "comparison_model_key": resolved_model.key,
                "canonical_model_id": resolved_model.canonical_model_id,
                "request_model": req_model,
                "ranking_name": resolved_model.ranking_name,
                "reasoning_effort": resolved_model.reasoning_effort,
                "observed_model_id": parsed.get("observed_model_id"),
                "request_body": {
                    "model": body.get("model"),
                    "temperature": body.get("temperature"),
                    "reasoning": body.get("reasoning"),
                    "response_format": body.get("response_format"),
                    "messages": [
                        {
                            "role": m["role"],
                            # Keep full payloads for acceptance proof.
                            "content": m["content"],
                        }
                        for m in body.get("messages") or []
                    ],
                },
                "response_score": parsed["score"],
                "response_usage": parsed["usage"],
                "provider_request_id": parsed.get("provider_request_id"),
                "metadata": dict(metadata or {}),
                "checks": {
                    "one_pair": True,
                    "code_change_chars": len(code_change),
                    "candidate_test_chars": len(candidate_test),
                    "no_chain_of_thought": True,
                    "probability_in_unit_interval": True,
                },
            },
        )

    price_key = price_route_for(resolved_model, resolved_route)
    if price_key not in PUBLISHED_RATES:
        raise GptRankerError(f"missing price route {price_key!r}")
    price_basis = default_price_basis(route=price_key)
    entry = build_success_score_entry(
        cache_key=cache_key,
        provider=resolved_route.provider,
        model_id=cache_model_id,
        observed_model_id=parsed.get("observed_model_id"),
        prompt_version=GPT_PROMPT_VERSION,
        state=state,
        question=question,
        score=float(parsed["score"]),
        usage=parsed["usage"],
        latency_ms=latency_ms,
        provider_request_id=parsed.get("provider_request_id"),
        price_basis=price_basis,
        metadata={
            **dict(metadata or {}),
            "ranking_name": resolved_model.ranking_name,
            "request_model": req_model,
            "comparison_model_key": resolved_model.key,
            "is_primary": resolved_model.is_primary,
            "reasoning_effort": resolved_model.reasoning_effort,
        },
    )
    write_cache_entry(entry, kind="gpt", cache_root=cache_root)
    costs = cost_breakdown_from_usage(
        input_tokens=int(parsed["usage"]["input_tokens"]),
        output_tokens=parsed["usage"].get("output_tokens", 0),
        price_basis=price_basis,
        provider_reported_cost_usd=parsed["usage"].get("cost"),
    )
    append_usage_ledger(
        {
            "schema_version": "jev-usage-ledger-v1",
            "kind": "gpt",
            "provider": resolved_route.provider,
            "model_id": cache_model_id,
            "cache_key": cache_key,
            "attempt_id": cache_key,
            "input_tokens": int(parsed["usage"]["input_tokens"]),
            "output_tokens": int(parsed["usage"].get("output_tokens") or 0),
            **costs,
            "metadata": {
                **dict(metadata or {}),
                "ranking_name": resolved_model.ranking_name,
            },
        },
        ledger_path=ledger_path,
    )
    return GptScoreResult(
        score=float(parsed["score"]),
        cache_key=cache_key,
        provider=resolved_route.provider,
        model_id=cache_model_id,
        request_model=req_model,
        observed_model_id=parsed.get("observed_model_id"),
        ranking_name=resolved_model.ranking_name,
        usage=parsed["usage"],
        latency_ms=latency_ms,
        provider_request_id=parsed.get("provider_request_id"),
        from_cache=False,
        entry=entry,
    )


def score_example_candidate(
    example: ExampleId | str,
    test_class: str,
    *,
    model: ComparisonModel | str | None = None,
    split: str = "development",
    manifest: Mapping[str, Any] | None = None,
    data_root: Path | None = None,
    route: GptRoute | None = None,
    cache_root: Path | None = None,
    ledger_path: Path | None = None,
    capture_path: Path | None = None,
    call_fn: Callable[..., tuple[dict[str, Any], dict[str, Any], float]] | None = None,
    max_retries: int = 3,
) -> GptScoreResult:
    ex = example if isinstance(example, ExampleId) else ExampleId.parse(example)
    data = manifest if manifest is not None else load_manifest()
    require_manifest_membership(
        ex, manifest=data, allow_evaluation=(split == "evaluation")
    )
    patch = load_patch_representation_text(ex, data_root=data_root)
    pairs = dict(load_test_representation_texts(ex, data_root=data_root))
    if test_class not in pairs:
        raise GptRankerError(
            f"{ex.qualified}: test class {test_class!r} not in representations"
        )
    resolved_model = (
        primary_comparison_model()
        if model is None
        else model
        if isinstance(model, ComparisonModel)
        else get_comparison_model(model)
    )
    return get_or_score_pair(
        code_change=patch,
        candidate_test=pairs[test_class],
        model=resolved_model,
        route=route,
        cache_root=cache_root,
        ledger_path=ledger_path,
        capture_path=capture_path,
        call_fn=call_fn,
        max_retries=max_retries,
        metadata={
            "qualified_id": ex.qualified,
            "test_class": test_class,
            "split": split,
        },
    )


def score_shortlist(
    example: ExampleId | str,
    *,
    model: ComparisonModel | str | None = None,
    split: str = "development",
    limit: int | None = None,
    manifest: Mapping[str, Any] | None = None,
    data_root: Path | None = None,
    route: GptRoute | None = None,
    cache_root: Path | None = None,
    ledger_path: Path | None = None,
    capture_first: bool = False,
    max_concurrency: int = MAX_CONCURRENCY,
    max_rpm: int | None = None,
    spend_ceiling_usd: float | None = None,
    estimate_tokens_per_call: int = 2500,
) -> list[dict[str, Any]]:
    ex = example if isinstance(example, ExampleId) else ExampleId.parse(example)
    resolved_model = (
        primary_comparison_model()
        if model is None
        else model
        if isinstance(model, ComparisonModel)
        else get_comparison_model(model)
    )
    resolved_route = route or resolve_gpt_route()
    candidates = load_candidates(ex, data_root=data_root)
    ids = list(candidates["candidate_ids"])
    if limit is not None:
        ids = ids[: max(0, limit)]

    patch = load_patch_representation_text(ex, data_root=data_root)
    pairs = dict(load_test_representation_texts(ex, data_root=data_root))
    question = build_gpt_question()
    price = default_price_basis(
        route=price_route_for(resolved_model, resolved_route)
    )
    input_rate = float(price.get("input_usd_per_mtok") or 0.0)
    fee = float(price.get("platform_fee_rate") or 0.0)
    cache_model_id = resolved_model.canonical_model_id

    jobs: list[ScoreJob] = []
    for test_class in ids:
        if test_class not in pairs:
            raise GptRankerError(
                f"{ex.qualified}: missing representation for {test_class}"
            )
        state = build_jev_state(
            code_change=patch, candidate_test=pairs[test_class]
        )
        cache_key = semantic_cache_key(
            provider=resolved_route.provider,
            model_id=cache_model_id,
            prompt_version=GPT_PROMPT_VERSION,
            state=state,
            question=question,
        )
        est_cost = (estimate_tokens_per_call / 1_000_000.0) * input_rate * (1.0 + fee)
        jobs.append(
            ScoreJob(
                job_id=test_class,
                cache_key=cache_key,
                estimate_input_tokens=estimate_tokens_per_call,
                estimate_cost_usd=est_cost,
            )
        )

    cached_keys = {
        j.cache_key
        for j in jobs
        if load_score_cache(j.cache_key, kind="gpt", cache_root=cache_root) is not None
    }
    _ = estimate_spend(
        jobs, cached_keys=cached_keys, spend_ceiling_usd=spend_ceiling_usd
    )
    spend = SpendController(ceiling_usd=spend_ceiling_usd)
    captured = {"done": False}

    def _is_cached(job: ScoreJob) -> bool:
        return (
            load_score_cache(job.cache_key, kind="gpt", cache_root=cache_root)
            is not None
        )

    def _worker(job: ScoreJob) -> GptScoreResult:
        capture = None
        if (
            capture_first
            and not captured["done"]
            and resolved_model.is_primary
            and job.job_id == ids[0]
        ):
            capture = CAPTURED_REQUEST_PATH
            captured["done"] = True
        return score_example_candidate(
            ex,
            job.job_id,
            model=resolved_model,
            split=split,
            manifest=manifest,
            data_root=data_root,
            route=resolved_route,
            cache_root=cache_root,
            ledger_path=ledger_path,
            capture_path=capture,
            max_retries=0,
        )

    def _record_spend(result: GptScoreResult) -> float | None:
        if result.from_cache:
            return 0.0
        usage = result.usage or {}
        costs = cost_breakdown_from_usage(
            input_tokens=usage["input_tokens"],
            output_tokens=usage.get("output_tokens", 0),
            price_basis=result.entry["price_basis"],
        )
        return costs["effective_prepaid_credits_usd"]

    outcomes = run_score_batch(
        jobs,
        worker=_worker,
        is_cached=_is_cached,
        max_concurrency=max_concurrency,
        max_rpm=max_rpm,
        spend=spend,
        max_retries=3,
        record_spend=_record_spend,
    )

    rows: list[dict[str, Any]] = []
    for outcome in outcomes:
        if not outcome.ok or outcome.result is None:
            rows.append(
                {
                    "test_class": outcome.job_id,
                    "score": None,
                    "from_cache": outcome.from_cache,
                    "cache_key": outcome.cache_key,
                    "model_id": cache_model_id,
                    "ranking_name": resolved_model.ranking_name,
                    "error": outcome.error,
                    "skipped_spend_ceiling": outcome.skipped_spend_ceiling,
                    "attempts": outcome.attempts,
                }
            )
            continue
        result = outcome.result
        rows.append(
            {
                "test_class": outcome.job_id,
                "score": result.score,
                "from_cache": result.from_cache,
                "cache_key": result.cache_key,
                "model_id": result.model_id,
                "ranking_name": result.ranking_name,
                "observed_model_id": result.observed_model_id,
                "input_tokens": (result.usage or {}).get("input_tokens"),
                "output_tokens": (result.usage or {}).get("output_tokens"),
                "cached_input_tokens": (result.usage or {}).get("cached_input_tokens"),
                "attempts": outcome.attempts,
            }
        )
    return rows


def write_comparison_models_registry(*, path: Path | None = None) -> Path:
    out = path or COMPARISON_MODELS_PATH
    doc = {
        "schema_version": "gpt-comparison-models-v1",
        "prompt_version": GPT_PROMPT_VERSION,
        "ranker_version": GPT_RANKER_VERSION,
        "primary_key": primary_comparison_model().key,
        "models": [
            {
                "key": m.key,
                "canonical_model_id": m.canonical_model_id,
                "openrouter_request_model": m.openrouter_request_model,
                "openai_request_model": m.openai_request_model,
                "ranking_name": m.ranking_name,
                "reasoning_effort": m.reasoning_effort,
                "is_primary": m.is_primary,
                "price_route": m.price_route,
                "notes": m.notes,
            }
            for m in COMPARISON_MODELS
        ],
        "shared_contract": {
            "state_keys": ["code_change", "candidate_test"],
            "matches_jev_representations_byte_for_byte": True,
            "structured_output": {"probability": "[0,1]"},
            "no_chain_of_thought": True,
        },
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(out, doc)
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Score GPT comparison model(s) on one patch/test pair or shortlist."
    )
    parser.add_argument("example_id", help="Qualified id, e.g. Cli-30")
    parser.add_argument(
        "--model",
        default="primary",
        help=(
            "Comparison model key, 'primary', or 'all' "
            f"(keys: {[m.key for m in COMPARISON_MODELS]})"
        ),
    )
    parser.add_argument("--candidate", default=None)
    parser.add_argument("--shortlist", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--split",
        choices=("development", "evaluation"),
        default="development",
    )
    parser.add_argument("--allow-evaluation", action="store_true")
    parser.add_argument(
        "--provider",
        choices=("auto", "openai", "openrouter"),
        default="auto",
    )
    parser.add_argument("--capture", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.split == "evaluation" and not args.allow_evaluation:
        raise SystemExit(
            "--split evaluation requires --allow-evaluation "
            "(reserved until the Phase 6 design freeze)"
        )

    write_comparison_models_registry()
    route = resolve_gpt_route(prefer=args.provider)
    ex = ExampleId.parse(args.example_id)

    if args.model == "all":
        models: list[ComparisonModel] = list(COMPARISON_MODELS)
    elif args.model == "primary":
        models = [primary_comparison_model()]
    else:
        models = [get_comparison_model(args.model)]

    if args.shortlist:
        by_model: dict[str, Any] = {}
        for i, model in enumerate(models):
            rows = score_shortlist(
                ex,
                model=model,
                split=args.split,
                limit=args.limit,
                route=route,
                capture_first=bool(args.capture and i == 0),
            )
            by_model[model.key] = {
                "ranking_name": model.ranking_name,
                "canonical_model_id": model.canonical_model_id,
                "is_primary": model.is_primary,
                "count": len(rows),
                "scores": rows,
            }
        print(json.dumps({"qualified_id": ex.qualified, "models": by_model}, indent=2, sort_keys=True))
        return 0

    test_class = args.candidate or load_candidates(ex)["candidate_ids"][0]
    results = []
    for i, model in enumerate(models):
        capture = CAPTURED_REQUEST_PATH if (args.capture and i == 0) else None
        result = score_example_candidate(
            ex,
            test_class,
            model=model,
            split=args.split,
            route=route,
            capture_path=capture,
        )
        results.append(
            {
                "comparison_model_key": model.key,
                "ranking_name": result.ranking_name,
                "is_primary": model.is_primary,
                "test_class": test_class,
                "score": result.score,
                "from_cache": result.from_cache,
                "provider": result.provider,
                "model_id": result.model_id,
                "request_model": result.request_model,
                "observed_model_id": result.observed_model_id,
                "reasoning_effort": model.reasoning_effort,
                "usage": dict(result.usage),
                "cache_key": result.cache_key,
            }
        )
    print(
        json.dumps(
            {
                "qualified_id": ex.qualified,
                "test_class": test_class,
                "results": results,
                "captured_request": (
                    str(CAPTURED_REQUEST_PATH.relative_to(WORKSPACE))
                    if args.capture
                    else None
                ),
                "registry": str(COMPARISON_MODELS_PATH.relative_to(WORKSPACE)),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
