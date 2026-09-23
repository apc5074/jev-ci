"""Assemble full-suite semantic rankings from one shared BM25 shortlist (P5-08).

Jev and every GPT comparison model must consume the **same** saved Phase-4
``candidate_ids`` / ``shortlist_sha256``. Assembly:

1. Require a valid cached score for every shortlisted class.
2. Reorder the shortlist by score ↓, original BM25 rank ↑.
3. Append BM25 ranks ``K+1..N`` unchanged (byte-for-byte tail order).

Missing / non-finite scores, shortlist drift, or model/prompt mismatch fail
closed — no invented scores, no independent candidate regeneration.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.candidates import (
    load_candidates,
    load_ranking,
    shortlist_content_hash,
    verify_shortlist_is_ranking_prefix,
)
from src.embeddings import (
    load_patch_representation_text,
    load_test_representation_texts,
)
from src.example_contract import (
    WORKSPACE,
    ExampleId,
    PRIVATE_LABEL_FIELDS,
    assert_no_private_fields,
    atomic_write_json,
    development_example_ids,
    load_manifest,
    require_manifest_membership,
)
from src.gpt_ranker import (
    COMPARISON_MODELS,
    ComparisonModel,
    get_comparison_model,
    primary_comparison_model,
)
from src.semantic_cache import (
    GPT_PROMPT_VERSION,
    JEV_PROMPT_VERSION,
    build_gpt_question,
    build_jev_question,
    build_jev_state,
    load_score_cache,
    semantic_cache_key,
)

SEMANTIC_ROOT = WORKSPACE / "results" / "semantic"
ASSEMBLY_SCHEMA_VERSION = "jev-semantic-ranking-v1"
ASSEMBLY_VERSION = "jev-semantic-assemble-v1"


class AssembleError(Exception):
    """Semantic ranking assembly failed (fail closed)."""


@dataclass(frozen=True)
class AssembledRanking:
    method: str
    path: Path
    document: dict[str, Any]


def _slug_method(method: str) -> str:
    return (
        method.lower()
        .replace(" ", "_")
        .replace(".", "_")
        .replace("-", "_")
    )


def semantic_ranking_path(
    example: ExampleId | str,
    *,
    method: str,
    results_root: Path | None = None,
) -> Path:
    ex = example if isinstance(example, ExampleId) else ExampleId.parse(example)
    root = results_root if results_root is not None else SEMANTIC_ROOT
    return root / _slug_method(method) / f"{ex.slug}.json"


def bm25_rank_index(ranking_doc: Mapping[str, Any]) -> dict[str, int]:
    """Map test_class → 1-based BM25 rank (stable original order)."""
    entries = ranking_doc.get("ranking") or []
    out: dict[str, int] = {}
    for i, entry in enumerate(entries, start=1):
        cls = entry.get("test_class")
        if not isinstance(cls, str) or not cls:
            raise AssembleError(f"BM25 ranking entry {i} missing test_class")
        if cls in out:
            raise AssembleError(f"duplicate BM25 class {cls}")
        stored_rank = entry.get("rank")
        if stored_rank is not None and int(stored_rank) != i:
            raise AssembleError(
                f"BM25 rank field {stored_rank} != position {i} for {cls}"
            )
        out[cls] = i
    return out


def assemble_from_scores(
    *,
    example: ExampleId | str,
    method: str,
    scores: Mapping[str, float],
    candidates: Mapping[str, Any],
    bm25_ranking: Mapping[str, Any],
    provenance: Mapping[str, Any],
) -> dict[str, Any]:
    """Build one full-suite ranking document from shortlist scores + BM25 tail."""
    ex = example if isinstance(example, ExampleId) else ExampleId.parse(example)
    verify_shortlist_is_ranking_prefix(
        candidates=candidates, ranking=bm25_ranking
    )
    candidate_ids = list(candidates["candidate_ids"])
    k = int(candidates["K"])
    n = int(candidates["N"])
    if k != len(candidate_ids):
        raise AssembleError(f"{ex.qualified}: K={k} != len(shortlist)")
    digest = shortlist_content_hash(candidate_ids)
    if candidates.get("shortlist_sha256") != digest:
        raise AssembleError(f"{ex.qualified}: shortlist_sha256 mismatch")
    if bm25_ranking.get("shortlist_sha256") != digest:
        raise AssembleError(
            f"{ex.qualified}: BM25 ranking shortlist_sha256 diverges from candidates"
        )

    bm25_ids = [e["test_class"] for e in bm25_ranking["ranking"]]
    if len(bm25_ids) != n or len(set(bm25_ids)) != n:
        raise AssembleError(f"{ex.qualified}: BM25 ranking is not a permutation of N")
    if candidate_ids != bm25_ids[:k]:
        raise AssembleError(
            f"{ex.qualified}: candidate_ids are not the BM25 prefix"
        )

    bm25_rank = bm25_rank_index(bm25_ranking)

    # Require every shortlist ID; reject extras.
    missing = [c for c in candidate_ids if c not in scores]
    if missing:
        raise AssembleError(
            f"{ex.qualified}: missing scores for {len(missing)} shortlist "
            f"classes (e.g. {missing[:3]})"
        )
    extra = sorted(set(scores) - set(candidate_ids))
    if extra:
        raise AssembleError(
            f"{ex.qualified}: scores include non-shortlist classes: {extra[:5]}"
        )

    scored_prefix: list[tuple[float, int, str]] = []
    for cls in candidate_ids:
        score = scores[cls]
        if not isinstance(score, (int, float)) or isinstance(score, bool):
            raise AssembleError(f"{ex.qualified}: non-numeric score for {cls}")
        value = float(score)
        if not math.isfinite(value) or not (0.0 <= value <= 1.0):
            raise AssembleError(
                f"{ex.qualified}: score out of [0,1] or non-finite for {cls}: {value}"
            )
        scored_prefix.append((value, bm25_rank[cls], cls))

    # score ↓, original BM25 rank ↑
    scored_prefix.sort(key=lambda t: (-t[0], t[1]))
    prefix_ids = [cls for _, _, cls in scored_prefix]
    tail_ids = bm25_ids[k:]
    full_ids = prefix_ids + tail_ids
    if len(full_ids) != n or set(full_ids) != set(bm25_ids):
        raise AssembleError(
            f"{ex.qualified}: assembled ranking is not a full-suite permutation"
        )
    if full_ids[k:] != bm25_ids[k:]:
        raise AssembleError(
            f"{ex.qualified}: BM25 tail order was altered during assembly"
        )

    ranking_entries: list[dict[str, Any]] = []
    for rank, cls in enumerate(full_ids, start=1):
        entry: dict[str, Any] = {
            "test_class": cls,
            "rank": rank,
            "bm25_rank": bm25_rank[cls],
        }
        if cls in scores:
            entry["score"] = float(scores[cls])
            entry["scored"] = True
        else:
            entry["score"] = None
            entry["scored"] = False
        ranking_entries.append(entry)

    doc = {
        "schema_version": ASSEMBLY_SCHEMA_VERSION,
        "assembly_version": ASSEMBLY_VERSION,
        "example_id": ex.slug,
        "qualified_id": ex.qualified,
        "split": candidates.get("split") or bm25_ranking.get("split"),
        "method": method,
        "N": n,
        "K": k,
        "k_cap": candidates.get("k_cap"),
        "shortlist_sha256": digest,
        "candidate_ids": candidate_ids,
        "ranked_ids": full_ids,
        "ranking": ranking_entries,
        "prefix_order": prefix_ids,
        "tail_ids": tail_ids,
        "settings": {
            "shortlist_source": "data/candidates (Phase 4)",
            "prefix_sort": "score_desc_bm25_rank_asc",
            "tail": "bm25_order_unchanged",
            "regenerates_candidates": False,
        },
        "provenance": dict(provenance),
    }
    assert_no_private_fields(doc, context=f"semantic ranking {ex.qualified}")
    leaked = PRIVATE_LABEL_FIELDS.intersection(doc.keys())
    if leaked:
        raise AssembleError(f"private fields in ranking doc: {sorted(leaked)}")
    return doc


def _jev_route_identity(
    *,
    decision_path: Path | None = None,
) -> tuple[str, str]:
    """Provider + request model for cache lookup (no API key required)."""
    path = decision_path or (WORKSPACE / "results" / "jev_provider_decision.json")
    decision: dict[str, Any] = {}
    if path.is_file():
        decision = json.loads(path.read_text(encoding="utf-8"))
    provider = str(decision.get("selected_provider") or "openrouter")
    if provider in {"", "auto"}:
        provider = "openrouter"
    if provider == "openrouter":
        from src.jev_providers import OPENROUTER_JEV_MODEL

        model = str(decision.get("selected_model_id") or OPENROUTER_JEV_MODEL)
        return provider, model
    if provider == "typesafe_direct":
        from src.jev_ranker import JEV_TYPESAFE_PINNED_MODEL_ID

        return provider, JEV_TYPESAFE_PINNED_MODEL_ID
    raise AssembleError(f"unsupported Jev provider in decision: {provider!r}")


def _gpt_route_provider() -> str:
    """Provider used when GPT scores were cached (prefer OpenRouter if present)."""
    # Match resolve_gpt_route preference without requiring keys: use decision /
    # existing cache convention (OpenRouter for this study).
    decision_path = WORKSPACE / "results" / "gpt_comparison_models.json"
    if decision_path.is_file():
        doc = json.loads(decision_path.read_text(encoding="utf-8"))
        pref = doc.get("preferred_provider") or doc.get("provider")
        if isinstance(pref, str) and pref:
            return pref
    return "openrouter"


def load_jev_shortlist_scores(
    example: ExampleId | str,
    *,
    candidate_ids: Sequence[str],
    data_root: Path | None = None,
    cache_root: Path | None = None,
    require_model_id: str | None = None,
    require_provider: str | None = None,
) -> tuple[dict[str, float], dict[str, Any]]:
    """Load one Jev cache score per shortlist class (fail closed)."""
    ex = example if isinstance(example, ExampleId) else ExampleId.parse(example)
    provider, model_id = _jev_route_identity()
    if require_provider:
        provider = require_provider
    if require_model_id:
        model_id = require_model_id
    patch = load_patch_representation_text(ex, data_root=data_root)
    pairs = dict(load_test_representation_texts(ex, data_root=data_root))
    question = build_jev_question()
    scores: dict[str, float] = {}
    observed: set[str] = set()
    providers: set[str] = set()
    for cls in candidate_ids:
        if cls not in pairs:
            raise AssembleError(f"{ex.qualified}: no representation for {cls}")
        state = build_jev_state(code_change=patch, candidate_test=pairs[cls])
        key = semantic_cache_key(
            provider=provider,
            model_id=model_id,
            prompt_version=JEV_PROMPT_VERSION,
            state=state,
            question=question,
        )
        entry = load_score_cache(key, kind="jev", cache_root=cache_root)
        if entry is None:
            raise AssembleError(
                f"{ex.qualified}: missing Jev cache for {cls} (key={key[:12]}…)"
            )
        if entry.get("model_id") != model_id:
            raise AssembleError(
                f"{ex.qualified}: Jev model_id {entry.get('model_id')!r} "
                f"!= required {model_id!r}"
            )
        if entry.get("provider") != provider:
            raise AssembleError(
                f"{ex.qualified}: Jev provider {entry.get('provider')!r} "
                f"!= required {provider!r}"
            )
        if entry.get("prompt_version") != JEV_PROMPT_VERSION:
            raise AssembleError(
                f"{ex.qualified}: Jev prompt_version mismatch for {cls}"
            )
        score = entry.get("score")
        if not isinstance(score, (int, float)) or not math.isfinite(float(score)):
            raise AssembleError(f"{ex.qualified}: bad Jev score for {cls}")
        scores[cls] = float(score)
        observed_id = entry.get("observed_model_id")
        if not isinstance(observed_id, str) or not observed_id.strip():
            raise AssembleError(f"{ex.qualified}: missing observed model identity for {cls}")
        observed.add(observed_id)
        providers.add(str(entry.get("provider")))
    if len(observed) > 1:
        raise AssembleError(
            f"{ex.qualified}: mixed observed Jev models in shortlist: {sorted(observed)}"
        )
    provenance = {
        "kind": "jev",
        "provider": provider,
        "model_id": model_id,
        "observed_model_id": next(iter(observed), None),
        "prompt_version": JEV_PROMPT_VERSION,
        "ranking_name": "Jev",
    }
    return scores, provenance


def load_gpt_shortlist_scores(
    example: ExampleId | str,
    *,
    candidate_ids: Sequence[str],
    model: ComparisonModel | str,
    data_root: Path | None = None,
    cache_root: Path | None = None,
    require_provider: str | None = None,
) -> tuple[dict[str, float], dict[str, Any]]:
    """Load one GPT cache score per shortlist class for a comparison model."""
    ex = example if isinstance(example, ExampleId) else ExampleId.parse(example)
    resolved = (
        model
        if isinstance(model, ComparisonModel)
        else get_comparison_model(model)
    )
    provider = require_provider or _gpt_route_provider()
    patch = load_patch_representation_text(ex, data_root=data_root)
    pairs = dict(load_test_representation_texts(ex, data_root=data_root))
    question = build_gpt_question()
    scores: dict[str, float] = {}
    observed: set[str] = set()
    for cls in candidate_ids:
        if cls not in pairs:
            raise AssembleError(f"{ex.qualified}: no representation for {cls}")
        state = build_jev_state(code_change=patch, candidate_test=pairs[cls])
        key = semantic_cache_key(
            provider=provider,
            model_id=resolved.canonical_model_id,
            prompt_version=GPT_PROMPT_VERSION,
            state=state,
            question=question,
        )
        entry = load_score_cache(key, kind="gpt", cache_root=cache_root)
        if entry is None:
            raise AssembleError(
                f"{ex.qualified}: missing GPT cache for {cls} "
                f"model={resolved.key} (key={key[:12]}…)"
            )
        if entry.get("model_id") != resolved.canonical_model_id:
            raise AssembleError(
                f"{ex.qualified}: GPT model_id {entry.get('model_id')!r} "
                f"!= {resolved.canonical_model_id!r}"
            )
        if entry.get("provider") != provider:
            raise AssembleError(
                f"{ex.qualified}: GPT provider {entry.get('provider')!r} "
                f"!= {provider!r}"
            )
        if entry.get("prompt_version") != GPT_PROMPT_VERSION:
            raise AssembleError(
                f"{ex.qualified}: GPT prompt_version mismatch for {cls}"
            )
        score = entry.get("score")
        if not isinstance(score, (int, float)) or not math.isfinite(float(score)):
            raise AssembleError(f"{ex.qualified}: bad GPT score for {cls}")
        scores[cls] = float(score)
        observed_id = entry.get("observed_model_id")
        if not isinstance(observed_id, str) or not observed_id.strip():
            raise AssembleError(f"{ex.qualified}: missing observed model identity for {cls}")
        observed.add(observed_id)
    if len(observed) > 1:
        raise AssembleError(
            f"{ex.qualified}: mixed observed GPT models for {resolved.key}: "
            f"{sorted(observed)}"
        )
    provenance = {
        "kind": "gpt",
        "provider": provider,
        "model_id": resolved.canonical_model_id,
        "comparison_model_key": resolved.key,
        "observed_model_id": next(iter(observed), None),
        "prompt_version": GPT_PROMPT_VERSION,
        "ranking_name": resolved.ranking_name,
        "reasoning_effort": resolved.reasoning_effort,
        "is_primary": resolved.is_primary,
    }
    return scores, provenance


def assemble_jev_ranking(
    example: ExampleId | str,
    *,
    data_root: Path | None = None,
    results_root: Path | None = None,
    rankings_root: Path | None = None,
    cache_root: Path | None = None,
    write: bool = True,
) -> AssembledRanking:
    ex = example if isinstance(example, ExampleId) else ExampleId.parse(example)
    candidates = load_candidates(ex, data_root=data_root)
    bm25 = load_ranking(ex, results_root=rankings_root)
    scores, provenance = load_jev_shortlist_scores(
        ex,
        candidate_ids=list(candidates["candidate_ids"]),
        data_root=data_root,
        cache_root=cache_root,
    )
    doc = assemble_from_scores(
        example=ex,
        method="Jev",
        scores=scores,
        candidates=candidates,
        bm25_ranking=bm25,
        provenance=provenance,
    )
    path = semantic_ranking_path(ex, method="Jev", results_root=results_root)
    if write:
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(path, doc)
    return AssembledRanking(method="Jev", path=path, document=doc)


def assemble_gpt_ranking(
    example: ExampleId | str,
    *,
    model: ComparisonModel | str | None = None,
    data_root: Path | None = None,
    results_root: Path | None = None,
    rankings_root: Path | None = None,
    cache_root: Path | None = None,
    write: bool = True,
) -> AssembledRanking:
    ex = example if isinstance(example, ExampleId) else ExampleId.parse(example)
    resolved = (
        primary_comparison_model()
        if model is None
        else model
        if isinstance(model, ComparisonModel)
        else get_comparison_model(model)
    )
    candidates = load_candidates(ex, data_root=data_root)
    bm25 = load_ranking(ex, results_root=rankings_root)
    scores, provenance = load_gpt_shortlist_scores(
        ex,
        candidate_ids=list(candidates["candidate_ids"]),
        model=resolved,
        data_root=data_root,
        cache_root=cache_root,
    )
    doc = assemble_from_scores(
        example=ex,
        method=resolved.ranking_name,
        scores=scores,
        candidates=candidates,
        bm25_ranking=bm25,
        provenance=provenance,
    )
    path = semantic_ranking_path(
        ex, method=resolved.ranking_name, results_root=results_root
    )
    if write:
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(path, doc)
    return AssembledRanking(
        method=resolved.ranking_name, path=path, document=doc
    )


def verify_five_systems_present(
    example: ExampleId | str,
    *,
    require_semantic: Sequence[str] = ("Jev", "GPT-Nano"),
) -> dict[str, bool]:
    """Check Random / BM25 / Embedding / required semantic rankings exist."""
    ex = example if isinstance(example, ExampleId) else ExampleId.parse(example)
    checks = {
        "BM25": (WORKSPACE / "results" / "rankings" / f"{ex.slug}.json").is_file(),
        "Embedding": (
            WORKSPACE / "results" / "embeddings" / f"{ex.slug}.json"
        ).is_file(),
        "Random": (WORKSPACE / "results" / "random" / f"{ex.slug}.json").is_file(),
    }
    for method in require_semantic:
        checks[method] = semantic_ranking_path(ex, method=method).is_file()
    return checks


def assemble_development_bug(
    example: ExampleId | str,
    *,
    gpt_models: Sequence[str] | None = None,
    data_root: Path | None = None,
) -> dict[str, Any]:
    """Assemble Jev + selected GPT rankings for one development bug."""
    ex = example if isinstance(example, ExampleId) else ExampleId.parse(example)
    require_manifest_membership(ex, allow_evaluation=False)
    out: dict[str, Any] = {"qualified_id": ex.qualified, "assembled": [], "errors": []}
    try:
        jev = assemble_jev_ranking(ex, data_root=data_root)
        out["assembled"].append(
            {
                "method": jev.method,
                "path": str(jev.path.relative_to(WORKSPACE)),
                "N": jev.document["N"],
                "K": jev.document["K"],
            }
        )
    except Exception as exc:  # noqa: BLE001
        out["errors"].append({"method": "Jev", "error": str(exc)})

    keys = (
        list(gpt_models)
        if gpt_models is not None
        else [m.key for m in COMPARISON_MODELS]
    )
    for key in keys:
        try:
            gpt = assemble_gpt_ranking(ex, model=key, data_root=data_root)
            out["assembled"].append(
                {
                    "method": gpt.method,
                    "path": str(gpt.path.relative_to(WORKSPACE)),
                    "N": gpt.document["N"],
                    "K": gpt.document["K"],
                }
            )
        except Exception as exc:  # noqa: BLE001
            out["errors"].append({"method": key, "error": str(exc)})
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Assemble Jev/GPT full-suite rankings from shared shortlists."
    )
    parser.add_argument(
        "example_id",
        nargs="?",
        default=None,
        help="Qualified id (default: all development bugs with scores)",
    )
    parser.add_argument(
        "--gpt-models",
        nargs="*",
        default=None,
        help="GPT comparison keys (default: all registered)",
    )
    parser.add_argument(
        "--only-primary-gpt",
        action="store_true",
        help="Assemble only GPT-Nano (primary) among GPT models",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    gpt_models = args.gpt_models
    if args.only_primary_gpt:
        gpt_models = [primary_comparison_model().key]

    if args.example_id:
        targets = [ExampleId.parse(args.example_id)]
    else:
        targets = list(development_example_ids(load_manifest()))

    summaries = []
    failures = 0
    for ex in targets:
        summary = assemble_development_bug(ex, gpt_models=gpt_models)
        summaries.append(summary)
        if summary["errors"]:
            failures += 1
        status = "ok" if not summary["errors"] else "partial"
        print(
            f"{ex.qualified}: {status} "
            f"assembled={len(summary['assembled'])} errors={len(summary['errors'])}"
        )
        for err in summary["errors"]:
            print(f"  ! {err['method']}: {err['error']}", file=sys.stderr)

    out_path = WORKSPACE / "results" / "semantic_assembly_summary.json"
    atomic_write_json(
        out_path,
        {
            "schema_version": "jev-semantic-assembly-summary-v1",
            "count": len(targets),
            "bugs": summaries,
        },
    )
    print(f"summary: {out_path.relative_to(WORKSPACE)}")
    return 0 if summaries and failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
