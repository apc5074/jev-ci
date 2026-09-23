"""Shared semantic request cache and usage ledger (Phase 5 / P5-02).

Cache keys are SHA-256 over a canonical JSON envelope so provider, model,
prompt version, state, and question cannot collide across ambiguous string
concatenation. Successful scores live under ``cache/jev`` and ``cache/gpt``;
embeddings under ``cache/embeddings``. Failures are stored separately and are
never treated as scores.

Bug ID and test class appear only in metadata — never inside model-visible
``state`` / ``question`` payloads.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.example_contract import WORKSPACE, atomic_write_json, read_json
from src.jev_providers import OPENROUTER_JEV_MODEL, PUBLISHED_RATES, effective_input_cost_usd

CACHE_ROOT = WORKSPACE / "cache"
JEV_CACHE_DIR = CACHE_ROOT / "jev"
GPT_CACHE_DIR = CACHE_ROOT / "gpt"
EMBEDDING_CACHE_DIR = CACHE_ROOT / "embeddings"
FAILURE_CACHE_DIR = CACHE_ROOT / "failures"
USAGE_LEDGER_PATH = WORKSPACE / "results" / "usage_ledger.jsonl"

CACHE_SCHEMA_VERSION = "jev-semantic-cache-v1"
LEDGER_SCHEMA_VERSION = "jev-usage-ledger-v1"

# Prompt versions (bump when instruction/criteria text changes).
JEV_PROMPT_VERSION = "jev-would_detect_regression-v1"
GPT_PROMPT_VERSION = "gpt-would_detect_regression-v1"

JEV_QUESTION_ID = "would_detect_regression"

JEV_INSTRUCTIONS = (
    "A code change is proposed against a working codebase.\n"
    "\n"
    "The candidate test class already exists in the codebase.\n"
    "\n"
    "Would this test class be likely to expose an incorrect behavioral\n"
    "regression caused by the proposed code change if such a regression\n"
    "exists?\n"
    "\n"
    "Answer YES when the test exercises behavior affected by the changed\n"
    "code and its assertions could plausibly fail because of an incorrect\n"
    "change.\n"
    "\n"
    "This includes indirect behavioral relationships across methods or\n"
    "classes.\n"
    "\n"
    "Do not require exact identifier or filename overlap.\n"
    "\n"
    "Answer NO when the test is merely in the same project or discusses\n"
    "similar vocabulary but is unlikely to execute or validate behavior\n"
    "affected by this change."
)

JEV_CRITERIA = {
    "true": (
        "The test exercises and checks behavior that could be affected by the "
        "proposed code change, so an incorrect implementation could cause this "
        "test to fail."
    ),
    "false": (
        "The test does not meaningfully exercise or validate behavior affected "
        "by the proposed change, even if names or vocabulary overlap."
    ),
}


class CacheError(Exception):
    """Invalid cache / ledger state."""


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def canonical_json(value: Any) -> str:
    """Deterministic JSON for hashing (sorted keys, compact separators)."""
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_jev_state(*, code_change: str, candidate_test: str) -> dict[str, str]:
    """Model-visible Jev/GPT state (no bug id / labels)."""
    if not isinstance(code_change, str) or not isinstance(candidate_test, str):
        raise CacheError("code_change and candidate_test must be strings")
    return {
        "code_change": code_change,
        "candidate_test": candidate_test,
    }


def build_jev_question() -> dict[str, Any]:
    """Canonical Noul question object for would_detect_regression (v1)."""
    return {
        "id": JEV_QUESTION_ID,
        "type": "noul",
        "instructions": JEV_INSTRUCTIONS,
        "criteria": dict(JEV_CRITERIA),
    }


def build_gpt_question() -> dict[str, Any]:
    """Canonical GPT structured-output question envelope (same rubric, v1)."""
    return {
        "id": JEV_QUESTION_ID,
        "type": "probability",
        "instructions": JEV_INSTRUCTIONS,
        "criteria": dict(JEV_CRITERIA),
        "response_schema": {"probability": "number in [0,1]"},
    }


def semantic_cache_key(
    *,
    provider: str,
    model_id: str,
    prompt_version: str,
    state: Mapping[str, Any] | str,
    question: Mapping[str, Any] | str,
) -> str:
    """SHA-256 of a structured envelope (provider/model/prompt/state/question)."""
    envelope = {
        "provider": provider,
        "model_id": model_id,
        "prompt_version": prompt_version,
        "state": state if isinstance(state, str) else json.loads(canonical_json(state)),
        "question": question
        if isinstance(question, str)
        else json.loads(canonical_json(question)),
    }
    return sha256_text(canonical_json(envelope))


def embedding_cache_key(*, model_id: str, input_text: str) -> str:
    envelope = {"kind": "embedding", "model_id": model_id, "input_text": input_text}
    return sha256_text(canonical_json(envelope))


def cache_path_for(
    *,
    kind: str,
    cache_key: str,
    cache_root: Path | None = None,
) -> Path:
    root = cache_root or CACHE_ROOT
    if kind == "jev":
        base = root / "jev"
    elif kind == "gpt":
        base = root / "gpt"
    elif kind == "embedding":
        base = root / "embeddings"
    elif kind == "failure":
        base = root / "failures"
    else:
        raise CacheError(f"unknown cache kind {kind!r}")
    return base / f"{cache_key}.json"


def validate_score_entry(entry: Mapping[str, Any]) -> None:
    """Reject corrupt / incomplete successful cache records."""
    if entry.get("schema_version") != CACHE_SCHEMA_VERSION:
        raise CacheError(
            f"unsupported cache schema {entry.get('schema_version')!r}"
        )
    if entry.get("status") != "success":
        raise CacheError(f"not a success entry: status={entry.get('status')!r}")
    score = entry.get("score")
    if not isinstance(score, (int, float)) or not math.isfinite(float(score)):
        raise CacheError(f"non-finite score: {score!r}")
    if not (0.0 <= float(score) <= 1.0):
        raise CacheError(f"score out of [0,1]: {score}")
    usage = entry.get("usage") or {}
    if not isinstance(usage.get("input_tokens"), int) or usage["input_tokens"] < 0:
        raise CacheError(f"bad usage.input_tokens: {usage!r}")
    if entry.get("cache_key") != semantic_cache_key(
        provider=str(entry.get("provider")),
        model_id=str(entry.get("model_id")),
        prompt_version=str(entry.get("prompt_version")),
        state=entry.get("state") or {},
        question=entry.get("question") or {},
    ):
        # Recompute from stored state/question; mismatch → corrupt.
        raise CacheError("cache_key does not match stored state/question envelope")


def validate_embedding_entry(entry: Mapping[str, Any]) -> None:
    if entry.get("schema_version") != CACHE_SCHEMA_VERSION:
        raise CacheError(
            f"unsupported cache schema {entry.get('schema_version')!r}"
        )
    if entry.get("status") != "success":
        raise CacheError(f"not a success entry: status={entry.get('status')!r}")
    vector = entry.get("vector")
    if not isinstance(vector, list) or not vector:
        raise CacheError("embedding vector missing or empty")
    if not all(isinstance(x, (int, float)) and math.isfinite(float(x)) for x in vector):
        raise CacheError("embedding vector has non-finite values")
    usage = entry.get("usage") or {}
    if not isinstance(usage.get("input_tokens"), int) or usage["input_tokens"] < 0:
        raise CacheError(f"bad usage.input_tokens: {usage!r}")
    expected = embedding_cache_key(
        model_id=str(entry.get("model_id")),
        input_text=str(entry.get("input_text")),
    )
    if entry.get("cache_key") != expected:
        raise CacheError("embedding cache_key mismatch")


def load_score_cache(
    cache_key: str,
    *,
    kind: str,
    cache_root: Path | None = None,
) -> dict[str, Any] | None:
    """Return a validated success entry, or None if missing."""
    path = cache_path_for(kind=kind, cache_key=cache_key, cache_root=cache_root)
    if not path.is_file():
        return None
    try:
        entry = read_json(path)
    except Exception as exc:  # noqa: BLE001
        raise CacheError(f"unreadable cache file {path}: {exc}") from exc
    if kind in {"jev", "gpt"}:
        validate_score_entry(entry)
    else:
        raise CacheError(f"load_score_cache does not support kind={kind!r}")
    if entry.get("cache_key") != cache_key:
        raise CacheError("cache filename key mismatch")
    return entry


def load_embedding_cache(
    cache_key: str,
    *,
    cache_root: Path | None = None,
) -> dict[str, Any] | None:
    path = cache_path_for(kind="embedding", cache_key=cache_key, cache_root=cache_root)
    if not path.is_file():
        return None
    try:
        entry = read_json(path)
    except Exception as exc:  # noqa: BLE001
        raise CacheError(f"unreadable embedding cache {path}: {exc}") from exc
    validate_embedding_entry(entry)
    if entry.get("cache_key") != cache_key:
        raise CacheError("cache filename key mismatch")
    return entry


def build_success_score_entry(
    *,
    cache_key: str,
    provider: str,
    model_id: str,
    observed_model_id: str | None,
    prompt_version: str,
    state: Mapping[str, Any],
    question: Mapping[str, Any],
    score: float,
    usage: Mapping[str, Any],
    latency_ms: float | None,
    provider_request_id: str | None,
    price_basis: Mapping[str, Any],
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble a success record (does not write). Metadata may hold bug/class."""
    meta = dict(metadata or {})
    # Guard: never put private label fields into state.
    for forbidden in ("positive_classes", "trigger_methods", "tests_trigger_raw"):
        if forbidden in state or forbidden in question:
            raise CacheError(f"private field {forbidden} in model-visible payload")
    entry = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "status": "success",
        "cache_key": cache_key,
        "provider": provider,
        "model_id": model_id,
        "observed_model_id": observed_model_id,
        "prompt_version": prompt_version,
        "state": json.loads(canonical_json(state)),
        "question": json.loads(canonical_json(question)),
        "score": float(score),
        "usage": {
            "input_tokens": int(usage["input_tokens"]),
            "output_tokens": int(usage.get("output_tokens") or 0),
            "cached_input_tokens": usage.get("cached_input_tokens"),
            "provider_cost_usd": usage.get("cost"),
        },
        "latency_ms": latency_ms,
        "provider_request_id": provider_request_id,
        "timestamp": _utcnow(),
        "price_basis": dict(price_basis),
        "metadata": meta,
    }
    validate_score_entry(entry)
    return entry


def build_success_embedding_entry(
    *,
    cache_key: str,
    model_id: str,
    input_text: str,
    vector: Sequence[float],
    usage: Mapping[str, Any],
    latency_ms: float | None,
    provider_request_id: str | None,
    price_basis: Mapping[str, Any],
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    entry = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "status": "success",
        "cache_key": cache_key,
        "kind": "embedding",
        "model_id": model_id,
        "input_text": input_text,
        "vector": [float(x) for x in vector],
        "dimensions": len(vector),
        "usage": {
            "input_tokens": int(usage["input_tokens"]),
            "output_tokens": int(usage.get("output_tokens") or 0),
            "provider_cost_usd": usage.get("cost"),
        },
        "latency_ms": latency_ms,
        "provider_request_id": provider_request_id,
        "timestamp": _utcnow(),
        "price_basis": dict(price_basis),
        "metadata": dict(metadata or {}),
    }
    validate_embedding_entry(entry)
    return entry


def build_failure_entry(
    *,
    cache_key: str,
    kind: str,
    provider: str,
    model_id: str,
    prompt_version: str | None,
    error: str,
    http_status: int | None = None,
    retry_count: int = 0,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": CACHE_SCHEMA_VERSION,
        "status": "failure",
        "cache_key": cache_key,
        "kind": kind,
        "provider": provider,
        "model_id": model_id,
        "prompt_version": prompt_version,
        "error": error,
        "http_status": http_status,
        "retry_count": retry_count,
        "timestamp": _utcnow(),
        "metadata": dict(metadata or {}),
    }


def write_cache_entry(
    entry: Mapping[str, Any],
    *,
    kind: str,
    cache_root: Path | None = None,
) -> Path:
    """Atomic write of a success or failure entry to the appropriate directory."""
    key = entry.get("cache_key")
    if not isinstance(key, str) or len(key) != 64:
        raise CacheError("cache_key must be a 64-char hex digest")
    status = entry.get("status")
    if status == "success":
        if kind == "embedding":
            validate_embedding_entry(entry)
        elif kind in {"jev", "gpt"}:
            validate_score_entry(entry)
        else:
            raise CacheError(f"cannot write success for kind={kind!r}")
        path = cache_path_for(kind=kind, cache_key=key, cache_root=cache_root)
    elif status == "failure":
        path = cache_path_for(kind="failure", cache_key=key, cache_root=cache_root)
    else:
        raise CacheError(f"unknown status {status!r}")
    atomic_write_json(path, entry)
    return path


def default_price_basis(*, route: str) -> dict[str, Any]:
    """List-price + platform fee basis for a known route (not promotional cash)."""
    rates = PUBLISHED_RATES.get(route)
    if not rates:
        raise CacheError(f"unknown price route {route!r}")
    return {
        "route": route,
        "input_usd_per_mtok": rates.get("input_usd_per_mtok"),
        "output_usd_per_mtok": rates.get("output_usd_per_mtok"),
        "platform_fee_rate": rates.get("platform_fee_rate") or 0.0,
        "source": "published_list_price",
        "notes": (
            "list_price_inference_usd excludes promotions; "
            "platform_fee_usd is credit-purchase fee estimate; "
            "actual_cash_usd recorded separately when known"
        ),
    }


def cost_breakdown_from_usage(
    *,
    input_tokens: int,
    price_basis: Mapping[str, Any],
    actual_cash_usd: float | None = None,
    provider_reported_cost_usd: float | None = None,
) -> dict[str, Any]:
    """Separate list-price inference, platform fees, and actual cash."""
    input_rate = price_basis.get("input_usd_per_mtok")
    fee_rate = float(price_basis.get("platform_fee_rate") or 0.0)
    if input_rate is None:
        return {
            "list_price_inference_usd": None,
            "platform_fee_usd": None,
            "effective_prepaid_credits_usd": None,
            "provider_reported_cost_usd": provider_reported_cost_usd,
            "actual_cash_usd": actual_cash_usd,
        }
    parts = effective_input_cost_usd(
        input_tokens=input_tokens,
        input_usd_per_mtok=float(input_rate),
        platform_fee_rate=fee_rate,
    )
    return {
        **parts,
        "provider_reported_cost_usd": provider_reported_cost_usd,
        "actual_cash_usd": actual_cash_usd,
    }


@dataclass(frozen=True)
class LedgerAppendResult:
    appended: bool
    path: Path
    reason: str


def append_usage_ledger(
    record: Mapping[str, Any],
    *,
    ledger_path: Path | None = None,
) -> LedgerAppendResult:
    """Append a usage event if this cache_key+attempt_id is not already present.

    Successful paid calls should use attempt_id == cache_key (one success per key).
    Retries / failures use distinct attempt_ids so they remain auditable without
    double-counting success spend.
    """
    path = ledger_path or USAGE_LEDGER_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    cache_key = record.get("cache_key")
    attempt_id = record.get("attempt_id") or cache_key
    if not cache_key or not attempt_id:
        raise CacheError("ledger record requires cache_key and attempt_id")

    existing_ids: set[str] = set()
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            aid = row.get("attempt_id") or row.get("cache_key")
            if isinstance(aid, str):
                existing_ids.add(aid)
    if attempt_id in existing_ids:
        return LedgerAppendResult(
            appended=False,
            path=path,
            reason="attempt_id already in ledger",
        )

    row = {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "timestamp": _utcnow(),
        **dict(record),
        "attempt_id": attempt_id,
    }
    line = canonical_json(row) + "\n"
    # Append atomically enough for single-writer experiment scripts: write to
    # temp sibling then concatenate via exclusive open+write of the new line.
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)
        handle.flush()
    return LedgerAppendResult(appended=True, path=path, reason="appended")


def read_usage_ledger(*, ledger_path: Path | None = None) -> list[dict[str, Any]]:
    path = ledger_path or USAGE_LEDGER_PATH
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    return rows


def get_or_none_score(
    *,
    kind: str,
    provider: str,
    model_id: str,
    prompt_version: str,
    state: Mapping[str, Any],
    question: Mapping[str, Any],
    cache_root: Path | None = None,
) -> tuple[str, dict[str, Any] | None]:
    """Compute key and load validated cache hit (None → caller may pay)."""
    key = semantic_cache_key(
        provider=provider,
        model_id=model_id,
        prompt_version=prompt_version,
        state=state,
        question=question,
    )
    return key, load_score_cache(key, kind=kind, cache_root=cache_root)


# Convenience defaults aligned with P5-01 OpenRouter selection.
DEFAULT_JEV_PROVIDER = "openrouter"
DEFAULT_JEV_MODEL_ID = OPENROUTER_JEV_MODEL
