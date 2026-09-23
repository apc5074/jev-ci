"""One-pair Jev decision client (Phase 5 / P5-05).

Scores exactly one patch/test-class pair per request:

    state = {"code_change": <Phase 3 patch text>, "candidate_test": <Phase 3 test text>}
    question id = would_detect_regression (Noul)
    score = answer.noul ∈ [0, 1]  (no threshold / no substitute fields)

Selected route (P5-01): OpenRouter ``typesafe/jev-1.13`` with observed snapshot
recorded per response. TypeSafe direct remains available as an adapter when a
key exists. Reject ``jev-latest`` / unverified aliases for evaluation.

Secrets are runtime-only; Authorization values are redacted from logs/errors.
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
from src.jev_providers import (
    JEV_ALIAS_FORBIDDEN_FOR_EVAL,
    JEV_TYPESAFE_PINNED_MODEL_ID,
    OPENROUTER_BASE_URL,
    OPENROUTER_JEV_MODEL,
    OPENROUTER_SYSTEMONE_PATH,
    TYPESAFE_BASE_URL,
    TYPESAFE_SYSTEMONE_PATH,
)
from src.semantic_cache import (
    JEV_PROMPT_VERSION,
    JEV_QUESTION_ID,
    append_usage_ledger,
    build_failure_entry,
    build_jev_question,
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
DECISION_PATH = RESULTS_DIR / "jev_provider_decision.json"
CAPTURED_REQUEST_PATH = RESULTS_DIR / "jev_captured_request.json"
JEV_RANKER_VERSION = "jev-ranker-v1"


class JevRankerError(Exception):
    """Jev one-pair scoring failure."""


@dataclass(frozen=True)
class JevRoute:
    provider: str
    request_model: str
    endpoint: str
    price_route: str
    api_key_env: str


@dataclass(frozen=True)
class JevScoreResult:
    score: float
    cache_key: str
    provider: str
    model_id: str
    observed_model_id: str | None
    usage: Mapping[str, Any]
    latency_ms: float | None
    provider_request_id: str | None
    from_cache: bool
    entry: Mapping[str, Any]


def redact_secrets(text: str) -> str:
    out = text
    for env_name in (
        "OPENROUTER_API_KEY",
        "TYPESAFE_API_KEY",
        "OPENAI_API_KEY",
        "CLOUDFLARE_API_TOKEN",
    ):
        val = os.environ.get(env_name)
        if val and val in out:
            out = out.replace(val, "[REDACTED]")
    # Also scrub common bearer shapes if present without env match.
    if "Bearer " in out:
        parts = out.split("Bearer ")
        rebuilt = [parts[0]]
        for chunk in parts[1:]:
            token, sep, rest = chunk.partition(" ")
            if len(token) > 8:
                rebuilt.append(f"Bearer [REDACTED]{sep}{rest}")
            else:
                rebuilt.append(f"Bearer {chunk}")
        out = "".join(rebuilt) if len(parts) > 1 else out
    return out


def assert_model_allowed_for_eval(model_id: str) -> None:
    lowered = model_id.strip().lower()
    for alias in JEV_ALIAS_FORBIDDEN_FOR_EVAL:
        if lowered == alias.lower() or lowered.endswith("/" + alias.lower()):
            raise JevRankerError(
                f"forbidden Jev alias for evaluation: {model_id!r}"
            )
    if "latest" in lowered and "jev" in lowered:
        raise JevRankerError(
            f"refusing unverified moving Jev alias: {model_id!r}"
        )


def load_selected_route(
    *,
    prefer: str | None = None,
    decision_path: Path | None = None,
) -> JevRoute:
    """Resolve the P5-01 selected route (OpenRouter) or an explicit override."""
    choice = (prefer or "").strip().lower()
    path = decision_path or DECISION_PATH
    decision: dict[str, Any] = {}
    if path.is_file():
        decision = json.loads(path.read_text(encoding="utf-8"))

    selected = choice or str(decision.get("selected_provider") or "openrouter")
    if selected in {"", "auto"}:
        selected = str(decision.get("selected_provider") or "openrouter")

    if selected == "openrouter":
        if not os.environ.get("OPENROUTER_API_KEY"):
            raise JevRankerError("OPENROUTER_API_KEY not set")
        model = str(decision.get("selected_model_id") or OPENROUTER_JEV_MODEL)
        assert_model_allowed_for_eval(model)
        return JevRoute(
            provider="openrouter",
            request_model=model,
            endpoint=f"{OPENROUTER_BASE_URL}{OPENROUTER_SYSTEMONE_PATH}",
            price_route="openrouter",
            api_key_env="OPENROUTER_API_KEY",
        )
    if selected == "typesafe_direct":
        if not os.environ.get("TYPESAFE_API_KEY"):
            raise JevRankerError("TYPESAFE_API_KEY not set")
        model = JEV_TYPESAFE_PINNED_MODEL_ID
        assert_model_allowed_for_eval(model)
        return JevRoute(
            provider="typesafe_direct",
            request_model=model,
            endpoint=f"{TYPESAFE_BASE_URL}{TYPESAFE_SYSTEMONE_PATH}",
            price_route="typesafe_direct",
            api_key_env="TYPESAFE_API_KEY",
        )
    raise JevRankerError(f"unsupported Jev provider {selected!r}")


def transport_question(question: Mapping[str, Any]) -> dict[str, Any]:
    """Provider body question value (id is the map key, not repeated)."""
    return {
        "type": question["type"],
        "instructions": question["instructions"],
        "criteria": dict(question["criteria"]),
    }


def build_systemone_body(
    *,
    route: JevRoute,
    state: Mapping[str, str],
    question: Mapping[str, Any],
) -> dict[str, Any]:
    qid = str(question["id"])
    return {
        "model": route.request_model,
        "state": {
            "code_change": state["code_change"],
            "candidate_test": state["candidate_test"],
        },
        "questions": {qid: transport_question(question)},
    }


def assert_one_pair_request(
    *,
    body: Mapping[str, Any],
    code_change: str,
    candidate_test: str,
) -> None:
    """Prove exactly one pair is sent and no pipeline-injected label leakage."""
    state = body.get("state") or {}
    if set(state.keys()) != {"code_change", "candidate_test"}:
        raise JevRankerError(
            f"state keys must be exactly code_change/candidate_test, got {sorted(state)}"
        )
    if state.get("code_change") != code_change:
        raise JevRankerError("state.code_change does not match patch representation bytes")
    if state.get("candidate_test") != candidate_test:
        raise JevRankerError(
            "state.candidate_test does not match test representation bytes"
        )
    questions = body.get("questions") or {}
    if list(questions.keys()) != [JEV_QUESTION_ID]:
        raise JevRankerError(
            f"expected single question {JEV_QUESTION_ID!r}, got {list(questions)}"
        )
    # Pipeline must not inject private label fields into the wire body.
    blob = json.dumps(body, sort_keys=True)
    for field in PRIVATE_LABEL_FIELDS:
        if f'"{field}"' in blob:
            raise JevRankerError(f"private label field {field!r} present in request")
    # Bug-status tokens must not be *added* by the pipeline envelope (outside
    # the representation strings themselves).
    envelope_without_payloads = {
        "model": body.get("model"),
        "questions": body.get("questions"),
        "state_keys": sorted(state.keys()),
    }
    envelope_text = json.dumps(envelope_without_payloads).lower()
    for token in FORBIDDEN_MODEL_TOKENS:
        if token.lower() in envelope_text:
            raise JevRankerError(
                f"forbidden pipeline token {token!r} in request envelope"
            )


def parse_noul_score(
    response: Mapping[str, Any],
    *,
    question_id: str = JEV_QUESTION_ID,
) -> dict[str, Any]:
    """Extract and validate ``answer.noul`` as the ranking score."""
    answers = response.get("answers") or {}
    answer = answers.get(question_id) or {}
    if answer.get("type") != "noul":
        raise JevRankerError(f"expected noul answer type, got {answer!r}")
    noul = answer.get("noul")
    if not isinstance(noul, (int, float)) or isinstance(noul, bool):
        raise JevRankerError(f"noul missing or not numeric: {noul!r}")
    score = float(noul)
    if not math.isfinite(score):
        raise JevRankerError(f"noul not finite: {noul!r}")
    if not (0.0 <= score <= 1.0):
        raise JevRankerError(f"noul out of [0,1]: {score}")
    # Do not fall back to unrelated confidence fields.
    usage = response.get("usage") or {}
    if not isinstance(usage.get("input_tokens"), int) or usage["input_tokens"] < 0:
        raise JevRankerError(f"bad usage.input_tokens: {usage!r}")
    return {
        "score": score,
        "usage": {
            "input_tokens": int(usage["input_tokens"]),
            "output_tokens": int(usage.get("output_tokens") or 0),
            "cached_input_tokens": usage.get("cached_input_tokens"),
            "cost": usage.get("cost"),
        },
        "observed_model_id": response.get("model"),
        "provider_request_id": response.get("id"),
        "upstream_provider": response.get("provider"),
    }


def _http_json_post(
    *,
    url: str,
    headers: Mapping[str, str],
    body: Mapping[str, Any],
    timeout_s: float = 120.0,
) -> tuple[int, dict[str, Any] | Any, float, str | None]:
    payload = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        url, data=payload, headers=dict(headers), method="POST"
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
        err_body = exc.read().decode("utf-8", errors="replace")
        redacted = redact_secrets(err_body)
        message = f"Jev HTTP {exc.code}: {redacted[:500]}"
        retry_after = None
        # Prefer header, then body text.
        raw_ra = exc.headers.get("Retry-After") if exc.headers else None
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
        raise JevRankerError(message) from None
    except urllib.error.URLError as exc:
        message = f"Jev transport error: {redact_secrets(str(exc.reason))}"
        raise RetryableError(message) from None
    latency_ms = (time.perf_counter() - started) * 1000.0
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise JevRankerError(f"invalid Jev JSON: {exc}") from exc
    return status, data, latency_ms, request_id


def call_jev_systemone(
    *,
    route: JevRoute,
    state: Mapping[str, str],
    question: Mapping[str, Any],
    timeout_s: float = 120.0,
) -> tuple[dict[str, Any], dict[str, Any], float]:
    """POST one System One decision; return (wire_body, parsed_score, latency_ms)."""
    api_key = os.environ.get(route.api_key_env)
    if not api_key:
        raise JevRankerError(f"{route.api_key_env} not set")

    body = build_systemone_body(route=route, state=state, question=question)
    assert_one_pair_request(
        body=body,
        code_change=state["code_change"],
        candidate_test=state["candidate_test"],
    )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if route.provider == "openrouter":
        headers["HTTP-Referer"] = "https://github.com/jev-ci-test-selection"
        headers["X-OpenRouter-Title"] = "jev-ci"

    status, resp, latency_ms, _hdr_id = _http_json_post(
        url=route.endpoint,
        headers=headers,
        body=body,
        timeout_s=timeout_s,
    )
    if status != 200 or not isinstance(resp, dict):
        raise JevRankerError(
            f"Jev call failed: status={status} body={redact_secrets(str(resp))[:400]}"
        )
    parsed = parse_noul_score(resp)
    observed = parsed.get("observed_model_id")
    if isinstance(observed, str) and observed:
        assert_model_allowed_for_eval(observed)
        if "jev-1.13" not in observed and observed != route.request_model:
            raise JevRankerError(
                f"unexpected observed Jev model {observed!r} "
                f"(requested {route.request_model!r})"
            )
    return body, parsed, latency_ms


def get_or_score_pair(
    *,
    code_change: str,
    candidate_test: str,
    route: JevRoute | None = None,
    cache_root: Path | None = None,
    ledger_path: Path | None = None,
    metadata: Mapping[str, Any] | None = None,
    capture_path: Path | None = None,
    call_fn: Callable[..., tuple[dict[str, Any], dict[str, Any], float]] | None = None,
    max_retries: int = 3,
) -> JevScoreResult:
    """Cache-first one-pair Jev score. Never invents a default score on failure."""
    resolved = route or load_selected_route()
    assert_model_allowed_for_eval(resolved.request_model)

    state = build_jev_state(code_change=code_change, candidate_test=candidate_test)
    question = build_jev_question()
    cache_key = semantic_cache_key(
        provider=resolved.provider,
        model_id=resolved.request_model,
        prompt_version=JEV_PROMPT_VERSION,
        state=state,
        question=question,
    )

    cached = load_score_cache(cache_key, kind="jev", cache_root=cache_root)
    if cached is not None:
        return JevScoreResult(
            score=float(cached["score"]),
            cache_key=cache_key,
            provider=str(cached["provider"]),
            model_id=str(cached["model_id"]),
            observed_model_id=cached.get("observed_model_id"),
            usage=cached.get("usage") or {},
            latency_ms=cached.get("latency_ms"),
            provider_request_id=cached.get("provider_request_id"),
            from_cache=True,
            entry=cached,
        )

    caller = call_fn or (
        lambda: call_jev_systemone(route=resolved, state=state, question=question)
    )
    try:
        body, parsed, latency_ms = with_retries(caller, max_retries=max_retries)
    except Exception as exc:  # noqa: BLE001 — persist final failure only
        failure = build_failure_entry(
            cache_key=cache_key,
            kind="jev",
            provider=resolved.provider,
            model_id=resolved.request_model,
            prompt_version=JEV_PROMPT_VERSION,
            error=redact_secrets(str(exc)),
            metadata=dict(metadata or {}),
        )
        write_cache_entry(failure, kind="failure", cache_root=cache_root)
        if isinstance(exc, RetryableError):
            raise
        raise JevRankerError(redact_secrets(str(exc))) from None

    if capture_path is not None:
        capture_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(
            capture_path,
            {
                "schema_version": "jev-captured-request-v1",
                "ranker_version": JEV_RANKER_VERSION,
                "prompt_version": JEV_PROMPT_VERSION,
                "provider": resolved.provider,
                "endpoint": resolved.endpoint,
                "request_model": resolved.request_model,
                "observed_model_id": parsed.get("observed_model_id"),
                "request_body": body,
                "response_score": parsed["score"],
                "response_usage": parsed["usage"],
                "provider_request_id": parsed.get("provider_request_id"),
                "metadata": dict(metadata or {}),
                "checks": {
                    "one_question": True,
                    "state_keys": sorted(body["state"].keys()),
                    "code_change_chars": len(code_change),
                    "candidate_test_chars": len(candidate_test),
                    "private_label_fields_absent": True,
                },
            },
        )

    price_basis = default_price_basis(route=resolved.price_route)
    entry = build_success_score_entry(
        cache_key=cache_key,
        provider=resolved.provider,
        model_id=resolved.request_model,
        observed_model_id=parsed.get("observed_model_id"),
        prompt_version=JEV_PROMPT_VERSION,
        state=state,
        question=question,
        score=float(parsed["score"]),
        usage=parsed["usage"],
        latency_ms=latency_ms,
        provider_request_id=parsed.get("provider_request_id"),
        price_basis=price_basis,
        metadata=dict(metadata or {}),
    )
    write_cache_entry(entry, kind="jev", cache_root=cache_root)
    costs = cost_breakdown_from_usage(
        input_tokens=int(parsed["usage"]["input_tokens"]),
        output_tokens=parsed["usage"].get("output_tokens", 0),
        price_basis=price_basis,
        provider_reported_cost_usd=parsed["usage"].get("cost"),
    )
    append_usage_ledger(
        {
            "schema_version": "jev-usage-ledger-v1",
            "kind": "jev",
            "provider": resolved.provider,
            "model_id": resolved.request_model,
            "cache_key": cache_key,
            "attempt_id": cache_key,
            "input_tokens": int(parsed["usage"]["input_tokens"]),
            "output_tokens": int(parsed["usage"].get("output_tokens") or 0),
            **costs,
            "metadata": dict(metadata or {}),
        },
        ledger_path=ledger_path,
    )
    return JevScoreResult(
        score=float(parsed["score"]),
        cache_key=cache_key,
        provider=resolved.provider,
        model_id=resolved.request_model,
        observed_model_id=parsed.get("observed_model_id"),
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
    split: str = "development",
    manifest: Mapping[str, Any] | None = None,
    data_root: Path | None = None,
    route: JevRoute | None = None,
    cache_root: Path | None = None,
    ledger_path: Path | None = None,
    capture_path: Path | None = None,
    call_fn: Callable[..., tuple[dict[str, Any], dict[str, Any], float]] | None = None,
    max_retries: int = 3,
) -> JevScoreResult:
    """Score one inventory/shortlist class for a locked example."""
    ex = example if isinstance(example, ExampleId) else ExampleId.parse(example)
    data = manifest if manifest is not None else load_manifest()
    require_manifest_membership(
        ex, manifest=data, allow_evaluation=(split == "evaluation")
    )
    patch = load_patch_representation_text(ex, data_root=data_root)
    pairs = dict(load_test_representation_texts(ex, data_root=data_root))
    if test_class not in pairs:
        raise JevRankerError(
            f"{ex.qualified}: test class {test_class!r} not in representations"
        )
    return get_or_score_pair(
        code_change=patch,
        candidate_test=pairs[test_class],
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
    split: str = "development",
    limit: int | None = None,
    manifest: Mapping[str, Any] | None = None,
    data_root: Path | None = None,
    route: JevRoute | None = None,
    cache_root: Path | None = None,
    ledger_path: Path | None = None,
    capture_first: bool = False,
    max_concurrency: int = MAX_CONCURRENCY,
    max_rpm: int | None = None,
    spend_ceiling_usd: float | None = None,
    estimate_tokens_per_call: int = 2500,
) -> list[dict[str, Any]]:
    """Score BM25 shortlist with ≤16-way concurrency, retries, and spend gate."""
    ex = example if isinstance(example, ExampleId) else ExampleId.parse(example)
    resolved = route or load_selected_route()
    candidates = load_candidates(ex, data_root=data_root)
    ids = list(candidates["candidate_ids"])
    if limit is not None:
        ids = ids[: max(0, limit)]

    patch = load_patch_representation_text(ex, data_root=data_root)
    pairs = dict(load_test_representation_texts(ex, data_root=data_root))
    question = build_jev_question()
    price = default_price_basis(route=resolved.price_route)
    input_rate = float(price.get("input_usd_per_mtok") or 0.0)
    fee = float(price.get("platform_fee_rate") or 0.0)

    jobs: list[ScoreJob] = []
    for test_class in ids:
        if test_class not in pairs:
            raise JevRankerError(
                f"{ex.qualified}: missing representation for {test_class}"
            )
        state = build_jev_state(
            code_change=patch, candidate_test=pairs[test_class]
        )
        cache_key = semantic_cache_key(
            provider=resolved.provider,
            model_id=resolved.request_model,
            prompt_version=JEV_PROMPT_VERSION,
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
                metadata={"qualified_id": ex.qualified},
            )
        )

    cached_keys = {
        j.cache_key
        for j in jobs
        if load_score_cache(j.cache_key, kind="jev", cache_root=cache_root) is not None
    }
    _ = estimate_spend(
        jobs, cached_keys=cached_keys, spend_ceiling_usd=spend_ceiling_usd
    )
    spend = SpendController(ceiling_usd=spend_ceiling_usd)
    captured = {"done": False}

    def _is_cached(job: ScoreJob) -> bool:
        return (
            load_score_cache(job.cache_key, kind="jev", cache_root=cache_root)
            is not None
        )

    def _worker(job: ScoreJob) -> JevScoreResult:
        capture = None
        if capture_first and not captured["done"] and job.job_id == ids[0]:
            capture = CAPTURED_REQUEST_PATH
            captured["done"] = True
        return score_example_candidate(
            ex,
            job.job_id,
            split=split,
            manifest=manifest,
            data_root=data_root,
            route=resolved,
            cache_root=cache_root,
            ledger_path=ledger_path,
            capture_path=capture,
            max_retries=0,
        )

    def _record_spend(result: JevScoreResult) -> float | None:
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
                "observed_model_id": result.observed_model_id,
                "input_tokens": (result.usage or {}).get("input_tokens"),
                "attempts": outcome.attempts,
            }
        )
    return rows


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Score one Jev patch/test-class pair (or a shortlist prefix)."
    )
    parser.add_argument("example_id", help="Qualified id, e.g. Cli-30")
    parser.add_argument(
        "--candidate",
        default=None,
        help="FQCN to score (default: first BM25 shortlist class)",
    )
    parser.add_argument(
        "--shortlist",
        action="store_true",
        help="Score the full BM25 shortlist sequentially",
    )
    parser.add_argument("--limit", type=int, default=None, help="Cap shortlist size")
    parser.add_argument(
        "--split",
        choices=("development", "evaluation"),
        default="development",
    )
    parser.add_argument("--allow-evaluation", action="store_true")
    parser.add_argument(
        "--provider",
        choices=("auto", "openrouter", "typesafe_direct"),
        default="auto",
    )
    parser.add_argument(
        "--capture",
        action="store_true",
        help=f"Write captured request to {CAPTURED_REQUEST_PATH.name}",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.split == "evaluation" and not args.allow_evaluation:
        raise SystemExit(
            "--split evaluation requires --allow-evaluation "
            "(reserved until the Phase 6 design freeze)"
        )

    prefer = None if args.provider == "auto" else args.provider
    route = load_selected_route(prefer=prefer)
    ex = ExampleId.parse(args.example_id)

    if args.shortlist:
        rows = score_shortlist(
            ex,
            split=args.split,
            limit=args.limit,
            route=route,
            capture_first=args.capture,
        )
        print(
            json.dumps(
                {
                    "qualified_id": ex.qualified,
                    "provider": route.provider,
                    "model_id": route.request_model,
                    "count": len(rows),
                    "scores": rows,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    test_class = args.candidate
    if not test_class:
        test_class = load_candidates(ex)["candidate_ids"][0]

    result = score_example_candidate(
        ex,
        test_class,
        split=args.split,
        route=route,
        capture_path=CAPTURED_REQUEST_PATH if args.capture else None,
    )
    print(
        json.dumps(
            {
                "qualified_id": ex.qualified,
                "test_class": test_class,
                "score": result.score,
                "from_cache": result.from_cache,
                "provider": result.provider,
                "model_id": result.model_id,
                "observed_model_id": result.observed_model_id,
                "usage": dict(result.usage),
                "cache_key": result.cache_key,
                "captured_request": (
                    str(CAPTURED_REQUEST_PATH.relative_to(WORKSPACE))
                    if args.capture
                    else None
                ),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
