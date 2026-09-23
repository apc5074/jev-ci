"""Persist BM25 full rankings and exact top-K candidate shortlists (Phase 4).

Layout:

- ``data/candidates/<project>_<bug>.json`` — ordered shortlist IDs (Phase 5 input)
- ``results/rankings/<project>_<bug>.json`` — full suite ranking with scores

``K = min(CANDIDATE_K_CAP, N)`` with ``CANDIDATE_K_CAP = 200`` (fixed). The
shortlist is always the exact prefix of the saved full ranking.

Safe reruns: reuse when provenance/input hashes and shortlist hash match;
otherwise regenerate intentionally. A ``.semantic_lock`` beside the candidate
file blocks overwrite while a semantic scoring run holds it.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.bm25 import BM25_B, BM25_K1, BM25_VERSION, bm25_provenance
from src.example_contract import (
    WORKSPACE,
    ExampleContractError,
    ExampleId,
    ExampleIncompleteError,
    PRIVATE_LABEL_FIELDS,
    assert_no_private_fields,
    atomic_write_json,
    load_manifest,
    read_json,
    require_manifest_membership,
)
from src.ranking import (
    LEXICAL_INPUT_CONTRACT_VERSION,
    QUERY_DIFF_SOURCE,
    SuiteRanking,
    build_lexical_inputs,
    rank_suite,
    cached_rank_suite,
)
from src.tokenize import TOKENIZER_VERSION, tokenizer_provenance

# Fixed shortlist cap (do not tune from development recall).
CANDIDATE_K_CAP = 200

CANDIDATES_ROOT = WORKSPACE / "data" / "candidates"
RANKINGS_ROOT = WORKSPACE / "results" / "rankings"
SEMANTIC_LOCK_SUFFIX = ".semantic_lock"

CANDIDATES_SCHEMA_VERSION = "jev-candidates-v1"
RANKING_SCHEMA_VERSION = "jev-bm25-ranking-v1"


class CandidatesError(Exception):
    """Candidate / ranking persistence failure."""


class SaveOutcome(str, Enum):
    WRITTEN = "written"
    REUSED = "reused"
    REGENERATED = "regenerated"


@dataclass(frozen=True)
class SaveResult:
    example_id: str
    qualified_id: str
    outcome: SaveOutcome
    n: int
    k: int
    candidate_path: Path
    ranking_path: Path
    shortlist_sha256: str
    detail: str = ""


def candidate_k(*, n: int, k_cap: int = CANDIDATE_K_CAP) -> int:
    if n < 0:
        raise CandidatesError(f"N must be nonnegative, got {n}")
    return min(k_cap, n)


def shortlist_content_hash(candidate_ids: Sequence[str]) -> str:
    """Content hash of the ordered shortlist (Phase 5 equality check)."""
    payload = "".join(f"{cid}\n" for cid in candidate_ids)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def candidates_dir(*, data_root: Path | None = None) -> Path:
    if data_root is None:
        return CANDIDATES_ROOT
    return data_root / "candidates"


def rankings_dir(*, results_root: Path | None = None) -> Path:
    if results_root is None:
        return RANKINGS_ROOT
    return results_root / "rankings"


def candidate_path(
    example: ExampleId | str,
    *,
    data_root: Path | None = None,
) -> Path:
    ex = example if isinstance(example, ExampleId) else ExampleId.parse(example)
    return candidates_dir(data_root=data_root) / f"{ex.slug}.json"


def ranking_path(
    example: ExampleId | str,
    *,
    results_root: Path | None = None,
) -> Path:
    ex = example if isinstance(example, ExampleId) else ExampleId.parse(example)
    return rankings_dir(results_root=results_root) / f"{ex.slug}.json"


def semantic_lock_path(
    example: ExampleId | str,
    *,
    data_root: Path | None = None,
) -> Path:
    path = candidate_path(example, data_root=data_root)
    return path.parent / f"{path.name}{SEMANTIC_LOCK_SUFFIX}"


def is_shortlist_locked(
    example: ExampleId | str,
    *,
    data_root: Path | None = None,
) -> bool:
    return semantic_lock_path(example, data_root=data_root).is_file()


def build_artifacts_from_ranking(
    ranking: SuiteRanking,
    *,
    split: str,
    manifest: Mapping[str, Any],
    source_missing_count: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build candidate shortlist + full ranking JSON payloads (no I/O)."""
    n = ranking.n_docs
    if n != len(ranking.ranked):
        raise CandidatesError(
            f"{ranking.qualified_id}: n_docs {n} != ranking length {len(ranking.ranked)}"
        )
    k = candidate_k(n=n)
    ordered_ids = [entry.test_class for entry in ranking.ranked]
    if len(ordered_ids) != len(set(ordered_ids)):
        raise CandidatesError(f"{ranking.qualified_id}: duplicate IDs in ranking")
    candidate_ids = ordered_ids[:k]
    shortlist_hash = shortlist_content_hash(candidate_ids)

    provenance = {
        "lexical_input_contract_version": LEXICAL_INPUT_CONTRACT_VERSION,
        "query_diff_source": QUERY_DIFF_SOURCE,
        "k_cap": CANDIDATE_K_CAP,
        "candidates_schema_version": CANDIDATES_SCHEMA_VERSION,
        "ranking_schema_version": RANKING_SCHEMA_VERSION,
        **tokenizer_provenance(),
        **bm25_provenance(),
    }
    if split == "evaluation":
        from src.freeze_guard import assert_evaluation_allowed

        lock = assert_evaluation_allowed()
        provenance["experiment_commit"] = lock.get("commit_sha")
        provenance["freeze_tag"] = lock.get("tag")
        try:
            from src.evaluation_preflight import load_preflight

            pre = load_preflight()
            if pre and pre.get("run_id"):
                provenance["run_id"] = pre["run_id"]
            if pre and pre.get("experiment_commit"):
                provenance["experiment_commit"] = pre["experiment_commit"]
        except Exception:  # noqa: BLE001
            pass

    input_hashes = dict(ranking.input_hashes)
    input_hashes.update(tokenizer_provenance())
    input_hashes.update(bm25_provenance())

    manifest_meta = {
        "selection_seed": manifest.get("selection_seed"),
        "defects4j_version": manifest.get("defects4j_version"),
        "defects4j_commit": manifest.get("defects4j_commit"),
        "manifest_created_at": manifest.get("created_at")
        or manifest.get("manifest_created_at"),
    }

    ranking_entries = [
        {
            "test_class": entry.test_class,
            "score": entry.score,
            "rank": entry.rank,
            "source_missing": entry.source_missing,
        }
        for entry in ranking.ranked
    ]

    ranking_doc: dict[str, Any] = {
        "schema_version": RANKING_SCHEMA_VERSION,
        "example_id": ranking.example_id,
        "qualified_id": ranking.qualified_id,
        "split": split,
        "N": n,
        "K": k,
        "k_cap": CANDIDATE_K_CAP,
        "avgdl": ranking.avgdl,
        "query_token_count": ranking.query_token_count,
        "distinct_query_terms": ranking.distinct_query_terms,
        "source_missing_count": source_missing_count,
        "candidate_ids": candidate_ids,
        "shortlist_sha256": shortlist_hash,
        "ranking": ranking_entries,
        "manifest": manifest_meta,
        "settings": {
            "bm25_version": BM25_VERSION,
            "bm25_k1": BM25_K1,
            "bm25_b": BM25_B,
            "tokenizer_version": TOKENIZER_VERSION,
            "lexical_input_contract_version": LEXICAL_INPUT_CONTRACT_VERSION,
            "query_diff_source": QUERY_DIFF_SOURCE,
        },
        "input_hashes": input_hashes,
        "provenance": provenance,
    }
    if provenance.get("experiment_commit"):
        ranking_doc["experiment_commit"] = provenance["experiment_commit"]
        ranking_doc["run_id"] = provenance.get("run_id")

    candidate_doc: dict[str, Any] = {
        "schema_version": CANDIDATES_SCHEMA_VERSION,
        "example_id": ranking.example_id,
        "qualified_id": ranking.qualified_id,
        "split": split,
        "N": n,
        "K": k,
        "k_cap": CANDIDATE_K_CAP,
        "candidate_ids": candidate_ids,
        "shortlist_sha256": shortlist_hash,
        "ranking_artifact": f"results/rankings/{ranking.example_id}.json",
        "manifest": manifest_meta,
        "settings": ranking_doc["settings"],
        "input_hashes": {
            # Subset sufficient for stale detection / Phase 5 checks.
            "lexical_input_contract_version": input_hashes.get(
                "lexical_input_contract_version"
            ),
            "query_diff_source": input_hashes.get("query_diff_source"),
            "test_class_ids_sha256": input_hashes.get("test_class_ids_sha256"),
            "query_sha256": input_hashes.get("query_sha256"),
            "documents_sha256": input_hashes.get("documents_sha256"),
            "inventory_sha256": input_hashes.get("inventory_sha256"),
            "patch_representation_sha256": input_hashes.get(
                "patch_representation_sha256"
            ),
            "tokenizer_version": input_hashes.get("tokenizer_version"),
            "tokenizer_config_sha256": input_hashes.get("tokenizer_config_sha256"),
            "bm25_version": input_hashes.get("bm25_version"),
            "bm25_k1": input_hashes.get("bm25_k1"),
            "bm25_b": input_hashes.get("bm25_b"),
        },
        "provenance": provenance,
    }
    if provenance.get("experiment_commit"):
        candidate_doc["experiment_commit"] = provenance["experiment_commit"]
        candidate_doc["run_id"] = provenance.get("run_id")

    for doc, label in ((candidate_doc, "candidates"), (ranking_doc, "ranking")):
        assert_no_private_fields(doc, context=label)
        bad = PRIVATE_LABEL_FIELDS.intersection(doc.keys())
        if bad:
            raise CandidatesError(f"{label} contains private fields: {sorted(bad)}")

    return candidate_doc, ranking_doc


def _artifacts_match_existing(
    *,
    candidate_doc: Mapping[str, Any],
    ranking_doc: Mapping[str, Any],
    cand_path: Path,
    rank_path: Path,
) -> bool:
    """True when on-disk artifacts match the newly built provenance and IDs.

    Score floats are not compared element-wise (JSON round-trip); matching
    ``input_hashes`` / settings / ordered IDs is sufficient for reuse.
    """
    if not cand_path.is_file() or not rank_path.is_file():
        return False
    existing_c = read_json(cand_path)
    existing_r = read_json(rank_path)

    shared_keys = (
        "shortlist_sha256",
        "candidate_ids",
        "N",
        "K",
        "settings",
        "qualified_id",
    )
    for key in shared_keys:
        if existing_c.get(key) != candidate_doc.get(key):
            return False
        if existing_r.get(key) != ranking_doc.get(key):
            return False

    if existing_c.get("schema_version") != candidate_doc.get("schema_version"):
        return False
    if existing_r.get("schema_version") != ranking_doc.get("schema_version"):
        return False
    if existing_c.get("input_hashes") != candidate_doc.get("input_hashes"):
        return False
    if existing_r.get("input_hashes") != ranking_doc.get("input_hashes"):
        return False
    # Evaluation seals must carry the freeze commit; rewrite if missing/stale.
    for existing, built in ((existing_c, candidate_doc), (existing_r, ranking_doc)):
        if built.get("experiment_commit") and existing.get("experiment_commit") != built.get(
            "experiment_commit"
        ):
            return False

    ranking_ids = [e.get("test_class") for e in existing_r.get("ranking") or []]
    expected_ids = [e.get("test_class") for e in ranking_doc.get("ranking") or []]
    if ranking_ids != expected_ids or existing_r.get("ranking") != ranking_doc.get("ranking"):
        return False
    k = existing_c.get("K")
    if not isinstance(k, int) or ranking_ids[:k] != existing_c.get("candidate_ids"):
        return False
    if existing_c.get("candidate_ids") != existing_r.get("candidate_ids"):
        return False
    return True


def save_ranking_and_candidates(
    ranking: SuiteRanking,
    *,
    split: str,
    manifest: Mapping[str, Any],
    source_missing_count: int = 0,
    data_root: Path | None = None,
    results_root: Path | None = None,
    force: bool = False,
) -> SaveResult:
    """Atomically write shortlist + full ranking, or reuse if identical."""
    cand_path = candidate_path(ranking.example_id, data_root=data_root)
    rank_path = ranking_path(ranking.example_id, results_root=results_root)
    lock = semantic_lock_path(ranking.example_id, data_root=data_root)

    candidate_doc, ranking_doc = build_artifacts_from_ranking(
        ranking,
        split=split,
        manifest=manifest,
        source_missing_count=source_missing_count,
    )
    shortlist_hash = candidate_doc["shortlist_sha256"]
    n = candidate_doc["N"]
    k = candidate_doc["K"]

    if _artifacts_match_existing(
        candidate_doc=candidate_doc,
        ranking_doc=ranking_doc,
        cand_path=cand_path,
        rank_path=rank_path,
    ):
        return SaveResult(
            example_id=ranking.example_id,
            qualified_id=ranking.qualified_id,
            outcome=SaveOutcome.REUSED,
            n=n,
            k=k,
            candidate_path=cand_path,
            ranking_path=rank_path,
            shortlist_sha256=shortlist_hash,
            detail="inputs/configuration match existing artifacts",
        )

    if lock.is_file() and not force:
        raise CandidatesError(
            f"{ranking.qualified_id}: refusing to overwrite shortlist while "
            f"semantic lock exists at {lock.name} (pass force=True to override)"
        )

    existed = cand_path.is_file() or rank_path.is_file()
    # Write ranking first, then candidates, so a crash mid-write cannot leave a
    # shortlist without a backing full ranking.
    atomic_write_json(rank_path, ranking_doc)
    atomic_write_json(cand_path, candidate_doc)

    # Byte-level shortlist hash check after write.
    loaded = read_json(cand_path)
    if loaded.get("shortlist_sha256") != shortlist_hash:
        raise CandidatesError("shortlist hash mismatch after write")
    if loaded.get("candidate_ids") != candidate_doc["candidate_ids"]:
        raise CandidatesError("candidate_ids mismatch after write")

    return SaveResult(
        example_id=ranking.example_id,
        qualified_id=ranking.qualified_id,
        outcome=SaveOutcome.REGENERATED if existed else SaveOutcome.WRITTEN,
        n=n,
        k=k,
        candidate_path=cand_path,
        ranking_path=rank_path,
        shortlist_sha256=shortlist_hash,
        detail="stale or missing artifacts replaced"
        if existed
        else "new artifacts written",
    )


def generate_and_save(
    example: ExampleId | str,
    *,
    data_root: Path | None = None,
    results_root: Path | None = None,
    manifest: Mapping[str, Any] | None = None,
    allow_evaluation: bool = False,
    force: bool = False,
) -> SaveResult:
    """Build lexical inputs, rank the suite, and persist artifacts."""
    data = manifest if manifest is not None else load_manifest()
    ex = example if isinstance(example, ExampleId) else ExampleId.parse(example)
    split = require_manifest_membership(
        ex, manifest=data, allow_evaluation=allow_evaluation
    )
    inputs = build_lexical_inputs(
        ex,
        data_root=data_root,
        manifest=data,
        allow_evaluation=allow_evaluation,
    )
    ranking = cached_rank_suite(inputs, cache_dir=(data_root or WORKSPACE / "data").parent / "cache" / "bm25")
    return save_ranking_and_candidates(
        ranking,
        split=split,
        manifest=data,
        source_missing_count=inputs.source_missing_count,
        data_root=data_root,
        results_root=results_root,
        force=force,
    )


def load_candidates(
    example: ExampleId | str,
    *,
    data_root: Path | None = None,
    require_hash: str | None = None,
) -> dict[str, Any]:
    """Phase 5 reader: load ordered shortlist; optionally check content hash."""
    ex = example if isinstance(example, ExampleId) else ExampleId.parse(example)
    path = candidate_path(ex, data_root=data_root)
    if not path.is_file():
        raise CandidatesError(f"missing candidates file: {path}")
    doc = read_json(path)
    assert_no_private_fields(doc, context=f"candidates {ex.qualified}")
    ids = doc.get("candidate_ids")
    if not isinstance(ids, list) or not ids:
        raise CandidatesError(f"{ex.qualified}: empty candidate_ids")
    if len(ids) != len(set(ids)):
        raise CandidatesError(f"{ex.qualified}: duplicate candidate_ids")
    k = doc.get("K")
    n = doc.get("N")
    if k != len(ids):
        raise CandidatesError(
            f"{ex.qualified}: K={k} != len(candidate_ids)={len(ids)}"
        )
    if not isinstance(n, int) or k != candidate_k(n=n):
        raise CandidatesError(
            f"{ex.qualified}: K={k} inconsistent with N={n} (cap={CANDIDATE_K_CAP})"
        )
    digest = shortlist_content_hash(ids)
    stored = doc.get("shortlist_sha256")
    if stored != digest:
        raise CandidatesError(
            f"{ex.qualified}: shortlist_sha256 mismatch "
            f"(stored={stored!r}, computed={digest!r})"
        )
    if require_hash is not None and digest != require_hash:
        raise CandidatesError(
            f"{ex.qualified}: shortlist hash {digest} != required {require_hash}"
        )
    return doc


def load_ranking(
    example: ExampleId | str,
    *,
    results_root: Path | None = None,
) -> dict[str, Any]:
    ex = example if isinstance(example, ExampleId) else ExampleId.parse(example)
    path = ranking_path(ex, results_root=results_root)
    if not path.is_file():
        raise CandidatesError(f"missing ranking file: {path}")
    doc = read_json(path)
    assert_no_private_fields(doc, context=f"ranking {ex.qualified}")
    return doc


def verify_shortlist_is_ranking_prefix(
    *,
    candidates: Mapping[str, Any],
    ranking: Mapping[str, Any],
) -> None:
    """Ensure candidate_ids equal the first K full-ranking IDs."""
    cand_ids = candidates.get("candidate_ids") or []
    rank_entries = ranking.get("ranking") or []
    rank_ids = [e.get("test_class") for e in rank_entries]
    k = candidates.get("K")
    if cand_ids != rank_ids[:k]:
        raise CandidatesError(
            f"{candidates.get('qualified_id')}: shortlist is not an exact "
            f"prefix of the full ranking"
        )
    if candidates.get("shortlist_sha256") != ranking.get("shortlist_sha256"):
        raise CandidatesError("shortlist_sha256 diverges between artifacts")
    if candidates.get("candidate_ids") != ranking.get("candidate_ids"):
        raise CandidatesError("candidate_ids diverge between artifacts")


def _cli(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Save BM25 ranking + candidate shortlist for one example (P4-04)."
    )
    parser.add_argument("example_id", help="Qualified id or slug (e.g. Cli-30)")
    parser.add_argument("--data-root", type=Path, default=None)
    parser.add_argument("--results-root", type=Path, default=None)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite even if a semantic lock is present",
    )
    args = parser.parse_args(argv)
    try:
        result = generate_and_save(
            args.example_id,
            data_root=args.data_root,
            results_root=args.results_root,
            force=args.force,
        )
    except (CandidatesError, ExampleContractError, ExampleIncompleteError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(
        f"{result.qualified_id}: {result.outcome.value} "
        f"N={result.n} K={result.k} shortlist={result.shortlist_sha256[:12]}…"
    )
    print(f"  candidates={result.candidate_path}")
    print(f"  ranking={result.ranking_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
