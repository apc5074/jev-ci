"""Export normalized evaluation predictions + hashed raw-result index (P7-08).

Reads sealed ranking / cache artifacts only — no provider calls. Known trigger
labels stay in ``data/tests/*/labels.json`` and are never written here.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.assemble_rankings import (
    _gpt_route_provider,
    _jev_route_identity,
    semantic_ranking_path,
)
from src.embeddings import (
    load_patch_representation_text,
    load_test_representation_texts,
    ranking_path as embedding_ranking_path,
)
from src.example_contract import (
    WORKSPACE,
    ExampleId,
    PRIVATE_LABEL_FIELDS,
    assert_no_private_fields,
    atomic_write_json,
    load_manifest,
    read_json,
    sha256_file,
)
from src.gpt_ranker import primary_comparison_model
from src.random_baseline import evaluation_example_ids
from src.semantic_cache import (
    GPT_PROMPT_VERSION,
    JEV_PROMPT_VERSION,
    build_gpt_question,
    build_jev_question,
    build_jev_state,
    load_embedding_cache,
    load_score_cache,
    semantic_cache_key,
)

PREDICTIONS_SCHEMA_VERSION = "jev-predictions-v1"
INDEX_SCHEMA_VERSION = "jev-raw-result-index-v1"
PREDICTIONS_PATH = WORKSPACE / "results" / "predictions.jsonl"
INDEX_PATH = WORKSPACE / "results" / "phase7" / "raw_result_index.json"
SUMMARY_PATH = WORKSPACE / "results" / "phase7" / "predictions_export.json"

METHOD_ORDER = ("BM25", "Embedding", "Jev", "GPT-Nano")

# Same 12 evaluation WAF gaps as scripts/assemble_evaluation.py (no invented scores).
ACCEPTED_JEV_GAPS: dict[str, str] = {
    "Jsoup-33": "org.jsoup.integration.UrlConnectTest",
    "Jsoup-54": "org.jsoup.integration.UrlConnectTest",
    "Jsoup-40": "org.jsoup.integration.UrlConnectTest",
    "Jsoup-47": "org.jsoup.integration.UrlConnectTest",
    "Jsoup-78": "org.jsoup.integration.ConnectTest",
    "Jsoup-81": "org.jsoup.integration.ConnectTest",
    "Jsoup-86": "org.jsoup.integration.ConnectTest",
    "Jsoup-69": "org.jsoup.integration.ConnectTest",
    "Jsoup-75": "org.jsoup.integration.ConnectTest",
    "Jsoup-85": "org.jsoup.integration.ConnectTest",
    "Jsoup-72": "org.jsoup.integration.ConnectTest",
    "Jsoup-84": "org.jsoup.integration.ConnectTest",
}


class ExportError(Exception):
    """Prediction export or validation failed."""


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(WORKSPACE.resolve()))
    except ValueError:
        return str(path)


def _dump_line(row: Mapping[str, Any]) -> str:
    assert_no_private_fields(row, context="predictions.jsonl row")
    leaked = PRIVATE_LABEL_FIELDS.intersection(row.keys())
    if leaked:
        raise ExportError(f"private fields in prediction row: {sorted(leaked)}")
    return json.dumps(row, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _require_finite_score(score: Any, *, context: str) -> float:
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        raise ExportError(f"{context}: non-numeric score {score!r}")
    value = float(score)
    if not math.isfinite(value):
        raise ExportError(f"{context}: non-finite score {value!r}")
    return value


def _scores_agree(a: float, b: float, *, context: str) -> None:
    if abs(a - b) > 1e-12 and a != b:
        raise ExportError(f"{context}: ranking score {a} != cache score {b}")


def _usage_block(entry: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if entry is None:
        return None
    return {
        "cache_key": entry.get("cache_key"),
        "provider": entry.get("provider"),
        "model_id": entry.get("model_id"),
        "observed_model_id": entry.get("observed_model_id"),
        "prompt_version": entry.get("prompt_version"),
        "usage": entry.get("usage"),
        "latency_ms": entry.get("latency_ms"),
        "price_basis": entry.get("price_basis"),
        "provider_request_id": entry.get("provider_request_id"),
    }


def _base_row(
    *,
    ex: ExampleId,
    method: str,
    test_class: str,
    rank: int,
    score: float | None,
    score_applicable: bool,
    experiment_commit: str | None,
    run_id: str | None,
    ranking_path: str,
    bm25_rank: int | None = None,
    source_missing: bool | None = None,
    cache: Mapping[str, Any] | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "schema_version": PREDICTIONS_SCHEMA_VERSION,
        "qualified_id": ex.qualified,
        "example_id": ex.slug,
        "split": "evaluation",
        "method": method,
        "test_class": test_class,
        "rank": int(rank),
        "score": score,
        "score_applicable": bool(score_applicable),
        "bm25_rank": bm25_rank,
        "source_missing": source_missing,
        "experiment_commit": experiment_commit,
        "run_id": run_id,
        "ranking_path": ranking_path,
    }
    block = _usage_block(cache)
    if block:
        row.update(block)
    else:
        row.update(
            {
                "cache_key": None,
                "provider": None,
                "model_id": None,
                "observed_model_id": None,
                "prompt_version": None,
                "usage": None,
                "latency_ms": None,
                "price_basis": None,
                "provider_request_id": None,
            }
        )
    if extra:
        row.update(extra)
    return row


def _load_run_meta() -> tuple[str, str]:
    run_path = WORKSPACE / "results" / "phase7" / "run.json"
    if not run_path.is_file():
        raise ExportError(f"missing phase7 run record: {run_path}")
    run = read_json(run_path)
    commit = run.get("experiment_commit")
    run_id = run.get("run_id")
    if not isinstance(commit, str) or not commit:
        raise ExportError("phase7 run.json missing experiment_commit")
    if not isinstance(run_id, str) or not run_id:
        raise ExportError("phase7 run.json missing run_id")
    return commit, run_id


def _bm25_path(ex: ExampleId) -> Path:
    return WORKSPACE / "results" / "rankings" / f"{ex.slug}.json"


def _random_path(ex: ExampleId) -> Path:
    return WORKSPACE / "results" / "random" / f"{ex.slug}.json"


def _candidates_path(ex: ExampleId) -> Path:
    return WORKSPACE / "data" / "candidates" / f"{ex.slug}.json"


def iter_bm25_rows(
    ex: ExampleId,
    *,
    experiment_commit: str,
    run_id: str,
) -> Iterator[dict[str, Any]]:
    path = _bm25_path(ex)
    if not path.is_file():
        raise ExportError(f"missing BM25 ranking: {path}")
    doc = read_json(path)
    if doc.get("split") != "evaluation":
        raise ExportError(f"{ex.qualified}: BM25 ranking split != evaluation")
    if doc.get("qualified_id") != ex.qualified:
        raise ExportError(f"{ex.qualified}: BM25 qualified_id mismatch")
    rel = _rel(path)
    commit = doc.get("experiment_commit") or experiment_commit
    rid = doc.get("run_id") or run_id
    for entry in doc["ranking"]:
        cls = entry["test_class"]
        score = _require_finite_score(entry["score"], context=f"BM25 {ex.qualified} {cls}")
        yield _base_row(
            ex=ex,
            method="BM25",
            test_class=cls,
            rank=int(entry["rank"]),
            score=score,
            score_applicable=True,
            experiment_commit=commit,
            run_id=rid,
            ranking_path=rel,
            source_missing=bool(entry.get("source_missing", False)),
            extra={
                "provider": None,
                "model_id": None,
                "tokenizer_version": (doc.get("provenance") or {}).get(
                    "tokenizer_version"
                ),
                "bm25_version": (doc.get("provenance") or {}).get("bm25_version"),
            },
        )


def iter_embedding_rows(
    ex: ExampleId,
    *,
    experiment_commit: str,
    run_id: str,
) -> Iterator[dict[str, Any]]:
    path = embedding_ranking_path(ex)
    if not path.is_file():
        raise ExportError(f"missing Embedding ranking: {path}")
    doc = read_json(path)
    if doc.get("split") != "evaluation":
        raise ExportError(f"{ex.qualified}: Embedding ranking split != evaluation")
    if doc.get("method") != "Embedding":
        raise ExportError(f"{ex.qualified}: unexpected embedding method {doc.get('method')!r}")
    test_keys = doc.get("test_cache_keys") or {}
    if not isinstance(test_keys, dict) or len(test_keys) != int(doc["N"]):
        raise ExportError(f"{ex.qualified}: embedding test_cache_keys incomplete")
    rel = _rel(path)
    commit = doc.get("experiment_commit") or experiment_commit
    rid = doc.get("run_id") or run_id
    for entry in doc["ranking"]:
        cls = entry["test_class"]
        score = _require_finite_score(
            entry["score"], context=f"Embedding {ex.qualified} {cls}"
        )
        key = test_keys.get(cls)
        if not isinstance(key, str) or not key:
            raise ExportError(f"{ex.qualified}: missing embedding cache key for {cls}")
        cache = load_embedding_cache(key)
        if cache is None:
            raise ExportError(f"{ex.qualified}: missing embedding cache {key[:12]}…")
        yield _base_row(
            ex=ex,
            method="Embedding",
            test_class=cls,
            rank=int(entry["rank"]),
            score=score,
            score_applicable=True,
            experiment_commit=commit,
            run_id=rid,
            ranking_path=rel,
            cache={
                "cache_key": key,
                "provider": doc.get("provider") or cache.get("metadata", {}).get("provider"),
                "model_id": doc.get("model_id") or cache.get("model_id"),
                "observed_model_id": None,
                "prompt_version": None,
                "usage": cache.get("usage"),
                "latency_ms": cache.get("latency_ms"),
                "price_basis": cache.get("price_basis"),
                "provider_request_id": cache.get("provider_request_id"),
            },
            extra={
                "request_model": doc.get("request_model"),
                "patch_cache_key": doc.get("patch_cache_key"),
                "dimensions": doc.get("dimensions"),
            },
        )


def _semantic_cache_for_class(
    *,
    kind: str,
    provider: str,
    model_id: str,
    prompt_version: str,
    patch: str,
    test_text: str,
) -> dict[str, Any]:
    if kind == "jev":
        state = build_jev_state(code_change=patch, candidate_test=test_text)
        question = build_jev_question()
    elif kind == "gpt":
        # GPT state mirrors Jev code_change + candidate_test envelope.
        state = build_jev_state(code_change=patch, candidate_test=test_text)
        question = build_gpt_question()
    else:
        raise ExportError(f"unknown semantic kind {kind!r}")
    key = semantic_cache_key(
        provider=provider,
        model_id=model_id,
        prompt_version=prompt_version,
        state=state,
        question=question,
    )
    entry = load_score_cache(key, kind=kind)
    if entry is None:
        raise ExportError(f"missing {kind} cache key={key[:12]}…")
    return entry


def iter_semantic_rows(
    ex: ExampleId,
    *,
    method: str,
    kind: str,
    experiment_commit: str,
    run_id: str,
    patch: str,
    test_texts: Mapping[str, str],
    provider: str,
    model_id: str,
    prompt_version: str,
) -> Iterator[dict[str, Any]]:
    path = semantic_ranking_path(ex, method=method)
    if not path.is_file():
        raise ExportError(f"missing {method} ranking: {path}")
    doc = read_json(path)
    if doc.get("split") != "evaluation":
        raise ExportError(f"{ex.qualified}: {method} ranking split != evaluation")
    if doc.get("method") != method:
        raise ExportError(
            f"{ex.qualified}: expected method {method!r}, got {doc.get('method')!r}"
        )
    if doc.get("qualified_id") != ex.qualified:
        raise ExportError(f"{ex.qualified}: {method} qualified_id mismatch")
    rel = _rel(path)
    commit = doc.get("experiment_commit") or experiment_commit
    rid = doc.get("run_id") or run_id
    candidate_ids = set(doc.get("candidate_ids") or [])
    provenance = doc.get("provenance") or {}

    for entry in doc["ranking"]:
        cls = entry["test_class"]
        scored = bool(entry.get("scored"))
        bm25_rank = entry.get("bm25_rank")
        if scored:
            if cls not in candidate_ids:
                raise ExportError(
                    f"{ex.qualified} {method}: scored class {cls} not in shortlist"
                )
            score = _require_finite_score(
                entry["score"], context=f"{method} {ex.qualified} {cls}"
            )
            if cls not in test_texts:
                raise ExportError(f"{ex.qualified}: missing representation for {cls}")
            cache = _semantic_cache_for_class(
                kind=kind,
                provider=provider,
                model_id=model_id,
                prompt_version=prompt_version,
                patch=patch,
                test_text=test_texts[cls],
            )
            _scores_agree(
                score,
                float(cache["score"]),
                context=f"{method} {ex.qualified} {cls}",
            )
            yield _base_row(
                ex=ex,
                method=method,
                test_class=cls,
                rank=int(entry["rank"]),
                score=score,
                score_applicable=True,
                experiment_commit=commit,
                run_id=rid,
                ranking_path=rel,
                bm25_rank=int(bm25_rank) if bm25_rank is not None else None,
                cache=cache,
                extra={
                    "shortlist_member": True,
                    "prompt_version": prompt_version,
                    "observed_model_id": cache.get("observed_model_id")
                    or provenance.get("observed_model_id"),
                },
            )
        else:
            if entry.get("score") is not None:
                raise ExportError(
                    f"{ex.qualified} {method}: unscored row has score for {cls}"
                )
            yield _base_row(
                ex=ex,
                method=method,
                test_class=cls,
                rank=int(entry["rank"]),
                score=None,
                score_applicable=False,
                experiment_commit=commit,
                run_id=rid,
                ranking_path=rel,
                bm25_rank=int(bm25_rank) if bm25_rank is not None else None,
                extra={
                    "shortlist_member": False,
                    "provider": provenance.get("provider"),
                    "model_id": provenance.get("model_id"),
                    "prompt_version": prompt_version,
                    "inapplicable_reason": "outside_bm25_shortlist",
                },
            )


def iter_bug_prediction_rows(
    ex: ExampleId,
    *,
    experiment_commit: str,
    run_id: str,
    jev_provider: str,
    jev_model_id: str,
    gpt_provider: str,
    gpt_model_id: str,
) -> Iterator[dict[str, Any]]:
    yield from iter_bm25_rows(ex, experiment_commit=experiment_commit, run_id=run_id)
    yield from iter_embedding_rows(
        ex, experiment_commit=experiment_commit, run_id=run_id
    )

    need_semantic = True
    gap = ACCEPTED_JEV_GAPS.get(ex.qualified)
    if gap is not None:
        # Still export GPT; skip Jev (no ranking, no invented scores).
        need_jev = False
    else:
        need_jev = True

    if need_semantic:
        patch = load_patch_representation_text(ex)
        test_texts = dict(load_test_representation_texts(ex))
        if need_jev:
            yield from iter_semantic_rows(
                ex,
                method="Jev",
                kind="jev",
                experiment_commit=experiment_commit,
                run_id=run_id,
                patch=patch,
                test_texts=test_texts,
                provider=jev_provider,
                model_id=jev_model_id,
                prompt_version=JEV_PROMPT_VERSION,
            )
        yield from iter_semantic_rows(
            ex,
            method="GPT-Nano",
            kind="gpt",
            experiment_commit=experiment_commit,
            run_id=run_id,
            patch=patch,
            test_texts=test_texts,
            provider=gpt_provider,
            model_id=gpt_model_id,
            prompt_version=GPT_PROMPT_VERSION,
        )


def validate_predictions(
    path: Path,
    *,
    example_ids: Sequence[ExampleId],
) -> dict[str, Any]:
    """Validate JSONL schema, uniqueness, and counts implied by rankings."""
    if not path.is_file():
        raise ExportError(f"missing predictions file: {path}")

    expected_keys: set[tuple[str, str, str]] = set()
    for ex in example_ids:
        bm25 = read_json(_bm25_path(ex))
        n = int(bm25["N"])
        for method in ("BM25", "Embedding", "GPT-Nano"):
            for entry in (
                bm25["ranking"]
                if method == "BM25"
                else read_json(
                    embedding_ranking_path(ex)
                    if method == "Embedding"
                    else semantic_ranking_path(ex, method=method)
                )["ranking"]
            ):
                expected_keys.add((ex.qualified, method, entry["test_class"]))
        if ex.qualified not in ACCEPTED_JEV_GAPS:
            jev = read_json(semantic_ranking_path(ex, method="Jev"))
            for entry in jev["ranking"]:
                expected_keys.add((ex.qualified, "Jev", entry["test_class"]))
        # Sanity: N classes for BM25
        if len(bm25["ranking"]) != n:
            raise ExportError(f"{ex.qualified}: BM25 ranking length != N")

    seen: set[tuple[str, str, str]] = set()
    line_count = 0
    applicable = 0
    inapplicable = 0
    by_method: dict[str, int] = {m: 0 for m in METHOD_ORDER}

    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                raise ExportError(f"blank line at {line_no}")
            row = json.loads(line)
            if row.get("schema_version") != PREDICTIONS_SCHEMA_VERSION:
                raise ExportError(f"line {line_no}: bad schema_version")
            key = (row["qualified_id"], row["method"], row["test_class"])
            if key in seen:
                raise ExportError(f"duplicate key {key}")
            seen.add(key)
            line_count += 1
            method = row["method"]
            if method not in by_method:
                raise ExportError(f"line {line_no}: unknown method {method!r}")
            by_method[method] += 1
            if row.get("score_applicable"):
                applicable += 1
                _require_finite_score(row.get("score"), context=f"line {line_no}")
            else:
                inapplicable += 1
                if row.get("score") is not None:
                    raise ExportError(f"line {line_no}: inapplicable score must be null")
            assert_no_private_fields(row, context=f"line {line_no}")

    missing = expected_keys - seen
    extra = seen - expected_keys
    if missing:
        sample = sorted(missing)[:5]
        raise ExportError(f"missing {len(missing)} prediction keys e.g. {sample}")
    if extra:
        sample = sorted(extra)[:5]
        raise ExportError(f"extra {len(extra)} prediction keys e.g. {sample}")

    return {
        "line_count": line_count,
        "unique_keys": len(seen),
        "score_applicable_rows": applicable,
        "score_inapplicable_rows": inapplicable,
        "by_method": by_method,
        "expected_keys": len(expected_keys),
        "accepted_jev_gap_bugs": len(ACCEPTED_JEV_GAPS),
    }


def _hash_if_exists(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return {
        "path": _rel(path),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
    }


def build_raw_result_index(
    *,
    example_ids: Sequence[ExampleId],
    predictions_path: Path,
    predictions_stats: Mapping[str, Any],
    experiment_commit: str,
    run_id: str,
) -> dict[str, Any]:
    artifacts: list[dict[str, Any]] = []

    def add(path: Path, *, kind: str, qualified_id: str | None = None) -> None:
        if not path.is_file():
            raise ExportError(f"missing required artifact ({kind}): {path}")
        entry = {
            "path": _rel(path),
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
            "kind": kind,
        }
        if qualified_id is not None:
            entry["qualified_id"] = qualified_id
        artifacts.append(entry)

    for ex in example_ids:
        add(_bm25_path(ex), kind="bm25_ranking", qualified_id=ex.qualified)
        add(embedding_ranking_path(ex), kind="embedding_ranking", qualified_id=ex.qualified)
        add(_random_path(ex), kind="random_baseline", qualified_id=ex.qualified)
        add(_candidates_path(ex), kind="candidates", qualified_id=ex.qualified)
        add(
            semantic_ranking_path(ex, method="GPT-Nano"),
            kind="gpt_nano_ranking",
            qualified_id=ex.qualified,
        )
        if ex.qualified in ACCEPTED_JEV_GAPS:
            jev_path = semantic_ranking_path(ex, method="Jev")
            if jev_path.is_file():
                raise ExportError(
                    f"{ex.qualified}: Jev ranking present despite accepted gap"
                )
        else:
            add(
                semantic_ranking_path(ex, method="Jev"),
                kind="jev_ranking",
                qualified_id=ex.qualified,
            )
        # Extraction / label sidecars (labels hashed but not embedded in predictions).
        labels = WORKSPACE / "data" / "tests" / ex.slug / "labels.json"
        inventory = WORKSPACE / "data" / "tests" / ex.slug / "inventory.json"
        example = WORKSPACE / "data" / "bugs" / ex.slug / "example.json"
        add(labels, kind="private_labels", qualified_id=ex.qualified)
        add(inventory, kind="test_inventory", qualified_id=ex.qualified)
        add(example, kind="example_status", qualified_id=ex.qualified)

    config_paths = [
        (WORKSPACE / "results" / "pricing_snapshot.json", "pricing_snapshot"),
        (WORKSPACE / "results" / "phase6" / "freeze_lock.json", "freeze_lock"),
        (WORKSPACE / "results" / "phase7" / "run.json", "phase7_run"),
        (WORKSPACE / "results" / "phase7" / "preflight.json", "phase7_preflight"),
        (WORKSPACE / "results" / "jev_provider_decision.json", "jev_provider_decision"),
        (WORKSPACE / "results" / "gpt_comparison_models.json", "gpt_comparison_models"),
        (WORKSPACE / "experiment.yaml", "experiment_yaml"),
        (WORKSPACE / "data" / "manifest.json", "manifest"),
        (WORKSPACE / "results" / "usage_ledger.jsonl", "usage_ledger"),
    ]
    config_refs: dict[str, Any] = {}
    for path, kind in config_paths:
        hashed = _hash_if_exists(path)
        if hashed is None:
            raise ExportError(f"missing config/ref artifact: {path}")
        hashed["kind"] = kind
        config_refs[kind] = hashed
        artifacts.append(hashed)

    pred_hash = sha256_file(predictions_path)
    index = {
        "schema_version": INDEX_SCHEMA_VERSION,
        "created_at": _utcnow(),
        "experiment_commit": experiment_commit,
        "run_id": run_id,
        "freeze_tag": "experiment-v1",
        "predictions": {
            "path": _rel(predictions_path),
            "sha256": pred_hash,
            "bytes": predictions_path.stat().st_size,
            "schema_version": PREDICTIONS_SCHEMA_VERSION,
            **dict(predictions_stats),
        },
        "counts": {
            "evaluation_bugs": len(example_ids),
            "bm25_rankings": len(example_ids),
            "embedding_rankings": len(example_ids),
            "gpt_nano_rankings": len(example_ids),
            "jev_rankings": len(example_ids) - len(ACCEPTED_JEV_GAPS),
            "random_baselines": len(example_ids),
            "accepted_jev_gaps": len(ACCEPTED_JEV_GAPS),
            "indexed_artifacts": len(artifacts) + 1,  # + predictions itself
        },
        "accepted_jev_gaps": {
            qid: {
                "test_class": cls,
                "reason": "OpenRouter WAF A-001 on file://etc/passwd",
                "jev_ranking": None,
            }
            for qid, cls in sorted(ACCEPTED_JEV_GAPS.items())
        },
        "config_refs": config_refs,
        "artifacts": artifacts,
        "notes": [
            "predictions.jsonl is derived from sealed rankings/caches only",
            "Random permutations regenerate from seed + inventory via generate_permutations",
            "Private trigger labels are hashed here but never copied into predictions",
            "Jev scores omitted for accepted A-001 gaps (no invented values)",
            "score_applicable=false marks semantic tail classes outside BM25 shortlist",
        ],
    }
    return index


def export_predictions(
    *,
    predictions_path: Path | None = None,
    index_path: Path | None = None,
    summary_path: Path | None = None,
) -> dict[str, Any]:
    out_pred = predictions_path or PREDICTIONS_PATH
    out_index = index_path or INDEX_PATH
    out_summary = summary_path or SUMMARY_PATH

    manifest = load_manifest()
    example_ids = evaluation_example_ids(manifest)
    experiment_commit, run_id = _load_run_meta()
    jev_provider, jev_model_id = _jev_route_identity()
    gpt_model = primary_comparison_model()
    gpt_provider = _gpt_route_provider()
    gpt_model_id = gpt_model.canonical_model_id

    out_pred.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_pred.with_name(out_pred.name + ".tmp")
    line_count = 0
    try:
        with tmp.open("w", encoding="utf-8") as handle:
            for ex in example_ids:
                for row in iter_bug_prediction_rows(
                    ex,
                    experiment_commit=experiment_commit,
                    run_id=run_id,
                    jev_provider=jev_provider,
                    jev_model_id=jev_model_id,
                    gpt_provider=gpt_provider,
                    gpt_model_id=gpt_model_id,
                ):
                    handle.write(_dump_line(row))
                    handle.write("\n")
                    line_count += 1
        tmp.replace(out_pred)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)

    stats = validate_predictions(out_pred, example_ids=example_ids)
    if stats["line_count"] != line_count:
        raise ExportError("written line_count != validated line_count")

    index = build_raw_result_index(
        example_ids=example_ids,
        predictions_path=out_pred,
        predictions_stats=stats,
        experiment_commit=experiment_commit,
        run_id=run_id,
    )
    atomic_write_json(out_index, index)

    summary = {
        "schema_version": "jev-predictions-export-summary-v1",
        "ok": True,
        "created_at": _utcnow(),
        "experiment_commit": experiment_commit,
        "run_id": run_id,
        "predictions_path": _rel(out_pred),
        "predictions_sha256": index["predictions"]["sha256"],
        "index_path": _rel(out_index),
        "index_sha256": sha256_file(out_index),
        "stats": stats,
        "accepted_jev_gaps": len(ACCEPTED_JEV_GAPS),
    }
    atomic_write_json(out_summary, summary)
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--predictions",
        type=Path,
        default=None,
        help="Override predictions.jsonl path",
    )
    parser.add_argument(
        "--index",
        type=Path,
        default=None,
        help="Override raw_result_index.json path",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        summary = export_predictions(
            predictions_path=args.predictions,
            index_path=args.index,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(
        f"OK predictions={summary['predictions_path']} "
        f"lines={summary['stats']['line_count']} "
        f"sha256={summary['predictions_sha256'][:16]}…"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
