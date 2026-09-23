"""Full-suite Embedding baseline (Phase 5 / P5-04).

Embed the Phase 3 patch ``representation.txt`` and **every** compact test
representation with ``text-embedding-3-small``. Rank all inventory classes by
cosine similarity (descending) with FQCN ascending as the sole tie-break.

No BM25 scores or candidate shortlists enter the ranking. Vectors are cached
under ``cache/embeddings/`` keyed by model + exact input text (P5-02).

Over-limit rule (preregistered; do not change after Phase 6 freeze):
**fail closed — never truncate.** If an input exceeds the provider's
``8192``-token embedding context (API context-length / max-tokens error),
record a failure cache entry and abort that bug's Embedding ranking. Do not
chunk, truncate, or average partial windows during evaluation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.example_contract import (
    WORKSPACE,
    ExampleContractError,
    ExampleId,
    PRIVATE_LABEL_FIELDS,
    assert_no_private_fields,
    atomic_write_json,
    example_paths,
    load_manifest,
    read_json,
    require_manifest_membership,
)
from src.jev_providers import OPENROUTER_BASE_URL, PUBLISHED_RATES
from src.semantic_cache import (
    append_usage_ledger,
    build_failure_entry,
    build_success_embedding_entry,
    cost_breakdown_from_usage,
    default_price_basis,
    embedding_cache_key,
    load_embedding_cache,
    write_cache_entry,
)

# --- Preregistered constants ---

EMBEDDING_MODEL_ID = "text-embedding-3-small"
OPENROUTER_EMBEDDING_REQUEST_MODEL = "openai/text-embedding-3-small"
OPENAI_EMBEDDINGS_URL = "https://api.openai.com/v1/embeddings"
OPENROUTER_EMBEDDINGS_URL = f"{OPENROUTER_BASE_URL}/embeddings"

# OpenAI docs: max 8192 tokens per input for embedding models.
EMBEDDING_MAX_INPUT_TOKENS = 8192
EXPECTED_DIMENSIONS = 1536

# Fail-closed over-limit policy id (recorded on rankings).
OVER_LIMIT_RULE = "fail_closed_no_truncate_v1"

EMBEDDING_BASELINE_VERSION = "jev-embedding-baseline-v1"
RANKING_SCHEMA_VERSION = "jev-embedding-ranking-v1"

EMBEDDING_RANKINGS_ROOT = WORKSPACE / "results" / "embeddings"

# Batch uncached texts per HTTP call (under provider item/token caps).
DEFAULT_BATCH_SIZE = 32


class EmbeddingError(Exception):
    """Embedding client or ranking failure."""


class EmbeddingLimitError(EmbeddingError):
    """Input exceeded the provider context limit (no truncation applied)."""


class SaveOutcome(str, Enum):
    WRITTEN = "written"
    REUSED = "reused"
    REGENERATED = "regenerated"


@dataclass(frozen=True)
class EmbeddingRoute:
    provider: str
    request_model: str
    canonical_model_id: str
    price_route: str
    url: str
    api_key_env: str


def resolve_embedding_route(
    *,
    prefer: str | None = None,
) -> EmbeddingRoute:
    """Prefer OpenAI direct when keyed; otherwise OpenRouter (same underlying model)."""
    openai_key = bool(os.environ.get("OPENAI_API_KEY"))
    openrouter_key = bool(os.environ.get("OPENROUTER_API_KEY"))
    choice = (prefer or "").strip().lower()
    if choice in {"", "auto"}:
        if openai_key:
            choice = "openai"
        elif openrouter_key:
            choice = "openrouter"
        else:
            raise EmbeddingError(
                "need OPENAI_API_KEY or OPENROUTER_API_KEY for embeddings"
            )
    if choice == "openai":
        if not openai_key:
            raise EmbeddingError("OPENAI_API_KEY not set")
        if "openai_embedding" not in PUBLISHED_RATES:
            raise EmbeddingError("missing openai_embedding published rates")
        # Ensure platform fee field exists for ledger helpers.
        return EmbeddingRoute(
            provider="openai",
            request_model=EMBEDDING_MODEL_ID,
            canonical_model_id=EMBEDDING_MODEL_ID,
            price_route="openai_embedding",
            url=OPENAI_EMBEDDINGS_URL,
            api_key_env="OPENAI_API_KEY",
        )
    if choice == "openrouter":
        if not openrouter_key:
            raise EmbeddingError("OPENROUTER_API_KEY not set")
        return EmbeddingRoute(
            provider="openrouter",
            request_model=OPENROUTER_EMBEDDING_REQUEST_MODEL,
            canonical_model_id=EMBEDDING_MODEL_ID,
            price_route="openrouter_embedding",
            url=OPENROUTER_EMBEDDINGS_URL,
            api_key_env="OPENROUTER_API_KEY",
        )
    raise EmbeddingError(f"unknown embedding route prefer={prefer!r}")


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b):
        raise EmbeddingError(f"vector length mismatch {len(a)} != {len(b)}")
    if not a:
        raise EmbeddingError("empty vectors")
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        fx = float(x)
        fy = float(y)
        if not math.isfinite(fx) or not math.isfinite(fy):
            raise EmbeddingError("non-finite vector component")
        dot += fx * fy
        na += fx * fx
        nb += fy * fy
    if na <= 0.0 or nb <= 0.0:
        raise EmbeddingError("zero-norm embedding vector")
    score = dot / (math.sqrt(na) * math.sqrt(nb))
    if not math.isfinite(score):
        raise EmbeddingError(f"non-finite cosine score: {score}")
    return score


def rank_by_cosine(
    *,
    query: Sequence[float],
    documents: Mapping[str, Sequence[float]],
) -> list[dict[str, Any]]:
    """Rank test classes by cosine desc, FQCN asc. No BM25 features."""
    scored: list[tuple[float, str]] = []
    for test_class, vector in documents.items():
        score = cosine_similarity(query, vector)
        scored.append((score, test_class))
    scored.sort(key=lambda t: (-t[0], t[1]))
    out: list[dict[str, Any]] = []
    for rank, (score, test_class) in enumerate(scored, start=1):
        out.append(
            {
                "test_class": test_class,
                "score": score,
                "rank": rank,
            }
        )
    return out


def _redact_auth(message: str) -> str:
    # Never echo bearer tokens from urllib errors.
    lowered = message
    for env_name in ("OPENAI_API_KEY", "OPENROUTER_API_KEY"):
        val = os.environ.get(env_name)
        if val and val in lowered:
            lowered = lowered.replace(val, "[REDACTED]")
    return lowered


def _is_context_length_error(status: int, body: str) -> bool:
    if status != 400:
        return False
    text = body.lower()
    needles = (
        "maximum context length",
        "max input tokens",
        "too many tokens",
        "context_length",
        "8192",
    )
    return any(n in text for n in needles)


def _http_embeddings(
    *,
    route: EmbeddingRoute,
    inputs: Sequence[str],
    timeout_s: float = 120.0,
) -> tuple[list[list[float]], dict[str, Any], str | None, float]:
    """POST one embedding batch; return vectors (input order), usage, request id, latency_ms."""
    if not inputs:
        raise EmbeddingError("empty embedding batch")
    for text in inputs:
        if not isinstance(text, str) or text == "":
            raise EmbeddingError("embedding input must be a non-empty string")

    api_key = os.environ.get(route.api_key_env)
    if not api_key:
        raise EmbeddingError(f"{route.api_key_env} not set")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if route.provider == "openrouter":
        headers["HTTP-Referer"] = "https://github.com/jev-ci-test-selection"
        headers["X-Title"] = "jev-ci embedding baseline"

    body = {
        "model": route.request_model,
        "input": list(inputs) if len(inputs) > 1 else inputs[0],
        "encoding_format": "float",
    }
    payload = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        route.url, data=payload, headers=headers, method="POST"
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as resp:
            raw = resp.read().decode("utf-8")
            request_id = resp.headers.get("x-request-id") or resp.headers.get(
                "X-Request-Id"
            )
            status = getattr(resp, "status", 200)
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        latency_ms = (time.perf_counter() - started) * 1000.0
        redacted = _redact_auth(err_body)
        if _is_context_length_error(exc.code, err_body):
            raise EmbeddingLimitError(
                f"input exceeded {EMBEDDING_MAX_INPUT_TOKENS}-token embedding limit "
                f"(HTTP {exc.code}); over-limit rule={OVER_LIMIT_RULE}; "
                f"body={redacted[:400]}"
            ) from None
        raise EmbeddingError(
            f"embedding HTTP {exc.code}: {redacted[:500]}"
        ) from None
    except urllib.error.URLError as exc:
        raise EmbeddingError(
            f"embedding transport error: {_redact_auth(str(exc.reason))}"
        ) from None

    latency_ms = (time.perf_counter() - started) * 1000.0
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise EmbeddingError(f"invalid embedding JSON: {exc}") from exc

    rows = data.get("data")
    if not isinstance(rows, list) or len(rows) != len(inputs):
        raise EmbeddingError(
            f"expected {len(inputs)} embedding rows, got "
            f"{len(rows) if isinstance(rows, list) else type(rows)}"
        )
    # Validate a permutation before associating vectors with input texts.
    indices = [r.get("index") for r in rows]
    if any(type(i) is not int for i in indices) or sorted(indices) != list(range(len(inputs))):
        raise EmbeddingError("embedding response indices are not a permutation of inputs")
    ordered = sorted(rows, key=lambda r: r["index"])
    vectors: list[list[float]] = []
    for row in ordered:
        emb = row.get("embedding")
        if not isinstance(emb, list) or not emb:
            raise EmbeddingError("missing embedding vector in response")
        if len(emb) != EXPECTED_DIMENSIONS:
            raise EmbeddingError(
                f"unexpected dimensions {len(emb)} (expected {EXPECTED_DIMENSIONS})"
            )
        if not all(
            isinstance(x, (int, float)) and math.isfinite(float(x)) for x in emb
        ):
            raise EmbeddingError("non-finite embedding components")
        vectors.append([float(x) for x in emb])

    usage_raw = data.get("usage") or {}
    prompt_tokens = usage_raw.get("prompt_tokens")
    if prompt_tokens is None:
        prompt_tokens = usage_raw.get("total_tokens")
    if not isinstance(prompt_tokens, int) or prompt_tokens < 0:
        raise EmbeddingError(f"bad embedding usage: {usage_raw!r}")
    usage = {
        "input_tokens": prompt_tokens,
        "output_tokens": 0,
        "cost": usage_raw.get("cost"),
    }
    returned_model = data.get("model")
    if isinstance(returned_model, str) and returned_model:
        # Accept aliases that still name the canonical model.
        if EMBEDDING_MODEL_ID not in returned_model and returned_model != route.request_model:
            raise EmbeddingError(
                f"unexpected embedding model {returned_model!r}"
            )
    _ = status  # unused; success path
    return vectors, usage, request_id, latency_ms


def get_or_embed_texts(
    texts: Sequence[str],
    *,
    route: EmbeddingRoute | None = None,
    cache_root: Path | None = None,
    ledger_path: Path | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    metadata: Mapping[str, Any] | None = None,
    embed_batch: Callable[..., tuple[list[list[float]], dict[str, Any], str | None, float]]
    | None = None,
) -> list[dict[str, Any]]:
    """Return validated embedding cache entries for each text (cache-first)."""
    if type(batch_size) is not int or batch_size < 1:
        raise EmbeddingError("batch_size must be a positive integer")
    resolved = route or resolve_embedding_route()
    price_basis = default_price_basis(route=resolved.price_route)

    entries: list[dict[str, Any] | None] = [None] * len(texts)
    misses: list[tuple[int, str, str]] = []  # index, text, cache_key
    positions: dict[str, list[int]] = {}

    for i, text in enumerate(texts):
        if not isinstance(text, str) or text == "":
            raise EmbeddingError(f"texts[{i}] must be a non-empty string")
        key = embedding_cache_key(
            model_id=resolved.canonical_model_id, input_text=text
        )
        if key in positions:
            positions[key].append(i)
            continue
        positions[key] = [i]
        cached = load_embedding_cache(key, cache_root=cache_root)
        if cached is not None:
            if cached.get("dimensions") != EXPECTED_DIMENSIONS:
                raise EmbeddingError(
                    f"cached embedding dims {cached.get('dimensions')} "
                    f"!= {EXPECTED_DIMENSIONS}"
                )
            entries[i] = cached
        else:
            misses.append((i, text, key))

    caller = embed_batch or (
        lambda inputs: _http_embeddings(route=resolved, inputs=inputs)
    )

    for start in range(0, len(misses), batch_size):
        chunk = misses[start : start + batch_size]
        chunk_texts = [t for _, t, _ in chunk]
        try:
            vectors, usage, request_id, latency_ms = caller(chunk_texts)
        except EmbeddingLimitError as exc:
            # Record failure for first offending key; re-raise (fail closed).
            _, text0, key0 = chunk[0]
            failure = build_failure_entry(
                cache_key=key0,
                kind="embedding",
                provider=resolved.provider,
                model_id=resolved.canonical_model_id,
                prompt_version=None,
                error=str(exc),
                http_status=400,
                metadata={
                    **dict(metadata or {}),
                    "over_limit_rule": OVER_LIMIT_RULE,
                    "max_input_tokens": EMBEDDING_MAX_INPUT_TOKENS,
                },
            )
            write_cache_entry(failure, kind="failure", cache_root=cache_root)
            raise

        # Usage is batch-level; attribute tokens proportionally by char length.
        total_chars = sum(max(1, len(t)) for t in chunk_texts)
        batch_tokens = int(usage["input_tokens"])
        batch_cost = usage.get("cost")
        # Cumulative integer allocation preserves the measured batch total.
        allocated_tokens = 0
        consumed_chars = 0

        for offset, (idx, text, key) in enumerate(chunk):
            share = max(1, len(text)) / total_chars
            consumed_chars += max(1, len(text))
            cumulative_tokens = batch_tokens * consumed_chars // total_chars
            item_tokens = cumulative_tokens - allocated_tokens
            allocated_tokens = cumulative_tokens
            item_cost = None
            if isinstance(batch_cost, (int, float)):
                item_cost = float(batch_cost) * share if len(chunk) > 1 else float(batch_cost)
            item_usage = {
                "input_tokens": item_tokens,
                "output_tokens": 0,
                "cost": item_cost,
            }
            entry = build_success_embedding_entry(
                cache_key=key,
                model_id=resolved.canonical_model_id,
                input_text=text,
                vector=vectors[offset],
                usage=item_usage,
                latency_ms=latency_ms / max(1, len(chunk)),
                provider_request_id=request_id,
                price_basis=price_basis,
                metadata={
                    **dict(metadata or {}),
                    "provider": resolved.provider,
                    "request_model": resolved.request_model,
                    "token_attribution": "proportional_characters_preserving_batch_total",
                    "batch_input_tokens": batch_tokens,
                },
            )
            write_cache_entry(entry, kind="embedding", cache_root=cache_root)
            costs = cost_breakdown_from_usage(
                input_tokens=item_tokens,
                price_basis=price_basis,
                provider_reported_cost_usd=item_cost,
            )
            append_usage_ledger(
                {
                    "schema_version": "jev-usage-ledger-v1",
                    "kind": "embedding",
                    "provider": resolved.provider,
                    "model_id": resolved.canonical_model_id,
                    "cache_key": key,
                    "attempt_id": key,
                    "input_tokens": item_tokens,
                    "output_tokens": 0,
                    **costs,
                    "metadata": dict(metadata or {}),
                },
                ledger_path=ledger_path,
            )
            entries[idx] = entry

    for indices in positions.values():
        for index in indices[1:]:
            entries[index] = entries[indices[0]]
    assert all(e is not None for e in entries)
    return [e for e in entries if e is not None]


def _resolve_workspace_path(
    relative: str,
    *,
    data_root: Path | None = None,
) -> Path:
    """Resolve a workspace-relative artifact path under Docker or a host checkout."""
    direct = Path(relative)
    if direct.is_file():
        return direct
    under_workspace = WORKSPACE / relative
    if under_workspace.is_file():
        return under_workspace
    under_repo = _REPO_ROOT / relative
    if under_repo.is_file():
        return under_repo
    if data_root is not None:
        # relative often starts with ``data/...``; data_root is ``.../data``.
        parts = Path(relative).parts
        if parts and parts[0] == "data":
            candidate = data_root.joinpath(*parts[1:])
            if candidate.is_file():
                return candidate
        candidate = data_root / relative
        if candidate.is_file():
            return candidate
    return under_workspace


def load_patch_representation_text(
    example: ExampleId | str,
    *,
    data_root: Path | None = None,
) -> str:
    ex = example if isinstance(example, ExampleId) else ExampleId.parse(example)
    path = example_paths(ex, data_root=data_root)["patch_representation"]
    if not path.is_file():
        raise EmbeddingError(f"missing patch representation: {path}")
    text = path.read_text(encoding="utf-8")
    if not text:
        raise EmbeddingError(f"empty patch representation: {path}")
    return text


def load_test_representation_texts(
    example: ExampleId | str,
    *,
    data_root: Path | None = None,
) -> list[tuple[str, str]]:
    """Return (test_class, representation_text) in inventory order."""
    ex = example if isinstance(example, ExampleId) else ExampleId.parse(example)
    paths = example_paths(ex, data_root=data_root)
    inventory = read_json(paths["test_inventory"])
    assert_no_private_fields(inventory, context=f"{ex.qualified} inventory")
    leaked = PRIVATE_LABEL_FIELDS.intersection(inventory.keys())
    if leaked:
        raise EmbeddingError(
            f"{ex.qualified}: private fields in inventory: {sorted(leaked)}"
        )
    test_classes = inventory.get("test_classes")
    if not isinstance(test_classes, list) or not test_classes:
        raise EmbeddingError(f"{ex.qualified}: inventory.test_classes missing")

    index = read_json(paths["representations_index"])
    by_class: dict[str, str] = {}
    for entry in index.get("representations") or []:
        cls = entry.get("test_class")
        text_path = entry.get("text_path")
        if not isinstance(cls, str) or not isinstance(text_path, str):
            continue
        full = _resolve_workspace_path(text_path, data_root=data_root)
        if not full.is_file():
            # Fallback: conventional path beside inventory.
            full = (
                paths["representations_dir"] / f"{cls}.txt"
            )
        if not full.is_file():
            raise EmbeddingError(
                f"{ex.qualified}: missing test representation text for {cls}: {full}"
            )
        by_class[cls] = full.read_text(encoding="utf-8")

    ordered: list[tuple[str, str]] = []
    for cls in test_classes:
        if cls not in by_class:
            raise EmbeddingError(
                f"{ex.qualified}: no representation text for inventory class {cls}"
            )
        text = by_class[cls]
        if not text:
            raise EmbeddingError(
                f"{ex.qualified}: empty representation text for {cls}"
            )
        ordered.append((cls, text))
    return ordered


def ranking_path(
    example: ExampleId | str,
    *,
    results_root: Path | None = None,
) -> Path:
    ex = example if isinstance(example, ExampleId) else ExampleId.parse(example)
    root = results_root if results_root is not None else EMBEDDING_RANKINGS_ROOT
    return root / f"{ex.slug}.json"


def build_ranking_document(
    *,
    example: ExampleId,
    split: str,
    ranked: Sequence[Mapping[str, Any]],
    patch_cache_key: str,
    test_cache_keys: Mapping[str, str],
    route: EmbeddingRoute,
    input_hashes: Mapping[str, str],
    total_input_tokens: int,
) -> dict[str, Any]:
    n = len(ranked)
    ids = [r["test_class"] for r in ranked]
    if len(ids) != len(set(ids)):
        raise EmbeddingError(f"{example.qualified}: duplicate classes in ranking")
    return {
        "schema_version": RANKING_SCHEMA_VERSION,
        "embedding_baseline_version": EMBEDDING_BASELINE_VERSION,
        "example_id": example.slug,
        "qualified_id": example.qualified,
        "split": split,
        "N": n,
        "method": "Embedding",
        "model_id": route.canonical_model_id,
        "provider": route.provider,
        "request_model": route.request_model,
        "dimensions": EXPECTED_DIMENSIONS,
        "over_limit_rule": OVER_LIMIT_RULE,
        "max_input_tokens": EMBEDDING_MAX_INPUT_TOKENS,
        "ranking": [
            {
                "test_class": r["test_class"],
                "score": float(r["score"]),
                "rank": int(r["rank"]),
            }
            for r in ranked
        ],
        "ranked_ids": ids,
        "patch_cache_key": patch_cache_key,
        "test_cache_keys": dict(test_cache_keys),
        "total_input_tokens": total_input_tokens,
        "input_hashes": dict(input_hashes),
        "settings": {
            "similarity": "cosine",
            "tie_break": "fqcn_asc",
            "uses_bm25": False,
            "shortlist_restricted": False,
            "stores_vectors_in_ranking": False,
            "vector_cache": "cache/embeddings/<sha256>.json",
        },
    }


def generate_embedding_ranking(
    example: ExampleId | str,
    *,
    split: str = "development",
    manifest: Mapping[str, Any] | None = None,
    data_root: Path | None = None,
    results_root: Path | None = None,
    cache_root: Path | None = None,
    ledger_path: Path | None = None,
    route: EmbeddingRoute | None = None,
    force: bool = False,
    embed_batch: Callable[..., tuple[list[list[float]], dict[str, Any], str | None, float]]
    | None = None,
) -> tuple[dict[str, Any], SaveOutcome]:
    """Embed full suite and write ``results/embeddings/<slug>.json``."""
    ex = example if isinstance(example, ExampleId) else ExampleId.parse(example)
    data = manifest if manifest is not None else load_manifest()
    require_manifest_membership(
        ex,
        manifest=data,
        allow_evaluation=(split == "evaluation"),
    )
    resolved = route or resolve_embedding_route()

    patch_text = load_patch_representation_text(ex, data_root=data_root)
    test_pairs = load_test_representation_texts(ex, data_root=data_root)
    test_classes = [c for c, _ in test_pairs]
    test_texts = [t for _, t in test_pairs]

    input_hashes = {
        "patch_representation_sha256": hashlib.sha256(
            patch_text.encode("utf-8")
        ).hexdigest(),
        "test_class_ids_sha256": hashlib.sha256(
            "\n".join(test_classes).encode("utf-8")
        ).hexdigest(),
        "test_representations_sha256": hashlib.sha256(
            "\0".join(test_texts).encode("utf-8")
        ).hexdigest(),
    }

    path = ranking_path(ex, results_root=results_root)
    if path.is_file() and not force:
        existing = read_json(path)
        if (
            existing.get("schema_version") == RANKING_SCHEMA_VERSION
            and existing.get("model_id") == EMBEDDING_MODEL_ID
            and existing.get("input_hashes") == input_hashes
            and existing.get("N") == len(test_classes)
            and set(existing.get("ranked_ids") or []) == set(test_classes)
            and existing.get("settings", {}).get("uses_bm25") is False
        ):
            return existing, SaveOutcome.REUSED

    meta = {"qualified_id": ex.qualified, "split": split}
    all_texts = [patch_text, *test_texts]
    entries = get_or_embed_texts(
        all_texts,
        route=resolved,
        cache_root=cache_root,
        ledger_path=ledger_path,
        metadata=meta,
        embed_batch=embed_batch,
    )
    patch_entry = entries[0]
    doc_entries = entries[1:]
    query_vec = patch_entry["vector"]
    documents = {
        cls: ent["vector"] for cls, ent in zip(test_classes, doc_entries)
    }
    ranked = rank_by_cosine(query=query_vec, documents=documents)
    if {r["test_class"] for r in ranked} != set(test_classes):
        raise EmbeddingError(f"{ex.qualified}: ranking is not a full-suite permutation")

    test_keys = {
        cls: ent["cache_key"] for cls, ent in zip(test_classes, doc_entries)
    }
    total_tokens = sum(int(e["usage"]["input_tokens"]) for e in entries)
    doc = build_ranking_document(
        example=ex,
        split=split,
        ranked=ranked,
        patch_cache_key=str(patch_entry["cache_key"]),
        test_cache_keys=test_keys,
        route=resolved,
        input_hashes=input_hashes,
        total_input_tokens=total_tokens,
    )
    assert_no_private_fields(doc, context=f"embedding ranking {ex.qualified}")
    if doc["settings"].get("uses_bm25") is not False:
        raise EmbeddingError("uses_bm25 must be false")

    path.parent.mkdir(parents=True, exist_ok=True)
    outcome = SaveOutcome.REGENERATED if path.is_file() else SaveOutcome.WRITTEN
    atomic_write_json(path, doc)
    return doc, outcome


def load_embedding_ranking(
    example: ExampleId | str,
    *,
    results_root: Path | None = None,
) -> dict[str, Any]:
    path = ranking_path(example, results_root=results_root)
    if not path.is_file():
        raise EmbeddingError(f"missing embedding ranking: {path}")
    doc = read_json(path)
    assert_no_private_fields(doc, context=f"embedding ranking {path.name}")
    if doc.get("settings", {}).get("uses_bm25") is not False:
        raise EmbeddingError("embedding ranking must not use BM25")
    return doc


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate the Embedding baseline ranking for one bug."
    )
    parser.add_argument("example_id", help="Qualified id, e.g. Cli-30")
    parser.add_argument(
        "--split",
        choices=("development", "evaluation"),
        default="development",
    )
    parser.add_argument("--allow-evaluation", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--provider",
        choices=("auto", "openai", "openrouter"),
        default="auto",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.split == "evaluation" and not args.allow_evaluation:
        raise SystemExit(
            "--split evaluation requires --allow-evaluation "
            "(reserved until the Phase 6 design freeze)"
        )

    route = resolve_embedding_route(prefer=args.provider)
    ex = ExampleId.parse(args.example_id)
    doc, outcome = generate_embedding_ranking(
        ex,
        split=args.split,
        route=route,
        force=args.force,
    )
    print(
        json.dumps(
            {
                "qualified_id": ex.qualified,
                "outcome": outcome.value,
                "N": doc["N"],
                "provider": doc["provider"],
                "model_id": doc["model_id"],
                "total_input_tokens": doc["total_input_tokens"],
                "path": str(ranking_path(ex).relative_to(WORKSPACE)),
                "top3": [
                    {"test_class": r["test_class"], "score": r["score"]}
                    for r in doc["ranking"][:3]
                ],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
