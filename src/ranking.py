"""BM25 lexical query/document builders (Phase 4 input contract).

Locks how suite-retrieval BM25 (and later provenance checks) see each bug:

- **Document** (one per ``tests.all`` / inventory class): FQCN plus the **entire**
  fixed-revision Java source from the inventory ``source_map``. Missing-source
  classes contribute the FQCN alone. Compact 12k semantic representations and
  windowed excerpts are never used as the BM25 corpus.
- **Query:** model-visible patch ``representation.txt`` (modified files, modified
  classes, and the capped unified diff). This is the locked Phase 6 choice so
  lexical and semantic rankers share the same change context. The untruncated
  ``regression_patch.diff`` is audit-only and is not queried.

Trigger labels and bug-outcome metadata are never read into queries, documents,
or ranking features.

Staleness: ``input_hashes`` (class IDs, query text, per-document texts, inventory
and patch representation file hashes, contract version, tokenizer version/config)
must match before a saved ranking is reused.

Tokenization of query and document text for BM25 uses the single shared
``src.tokenize.tokenize`` also used by Phase 3 window selection.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Mapping, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.example_contract import (
    atomic_write_json,
    ExampleContractError,
    ExampleId,
    ExampleIncompleteError,
    PRIVATE_LABEL_FIELDS,
    assert_no_private_fields,
    example_paths,
    load_example,
    read_json,
    sha256_file,
)
from src.bm25 import (
    BM25_B,
    BM25_K1,
    BM25_VERSION,
    bm25_corpus_stats,
    bm25_provenance,
    bm25_scores,
)
from src.extract_tests import SOURCE_ENCODING, SOURCE_ENCODING_ERRORS
from src.representations import read_fixed_source
from src.tokenize import tokenize, tokenizer_provenance

# Bump when document/query assembly rules change; invalidates saved rankings.
LEXICAL_INPUT_CONTRACT_VERSION = "jev-bm25-lexical-v1"

# Locked query diff choice (carry into Phase 6 preregistration).
QUERY_DIFF_SOURCE = "model_visible_representation"
QUERY_DIFF_SOURCE_ALTERNATIVE = "untruncated_regression_patch"  # not used

DOCUMENT_JOIN = "\n"  # FQCN then full source when source is available


class LexicalInputError(Exception):
    """Failed to build a BM25 query or document under the locked contract."""


def tokenize_query(query_text: str) -> list[str]:
    """Tokenize a BM25 query with the shared Phase 3/4 tokenizer."""
    return tokenize(query_text)


def tokenize_document(document_text: str) -> list[str]:
    """Tokenize a BM25 document with the shared Phase 3/4 tokenizer."""
    return tokenize(document_text)


@dataclass(frozen=True)
class LexicalDocument:
    """One BM25 corpus document for a test class."""

    test_class: str
    text: str
    source_file: str | None
    source_missing: bool
    text_sha256: str


@dataclass(frozen=True)
class LexicalQuery:
    """BM25 query for one bug."""

    text: str
    diff_source: str
    query_sha256: str
    modified_files: tuple[str, ...]
    modified_classes: tuple[str, ...]
    representation_path: str
    patch_truncated: bool | None


@dataclass(frozen=True)
class LexicalInputs:
    """Full query + corpus + provenance hashes for one example."""

    example_id: str
    qualified_id: str
    query: LexicalQuery
    documents: tuple[LexicalDocument, ...]
    input_hashes: dict[str, Any]
    source_missing_count: int


@dataclass(frozen=True)
class RankedTestClass:
    """One entry in a full-suite BM25 ranking."""

    test_class: str
    score: float
    rank: int  # 1-based
    source_missing: bool


@dataclass(frozen=True)
class SuiteRanking:
    """Complete BM25 ranking over all test classes for one bug."""

    example_id: str
    qualified_id: str
    ranked: tuple[RankedTestClass, ...]
    n_docs: int
    avgdl: float
    query_token_count: int
    distinct_query_terms: int
    bm25_version: str
    k1: float
    b: float
    input_hashes: dict[str, Any]


def rank_tokenized_corpus(
    *,
    test_classes: Sequence[str],
    document_token_lists: Sequence[Sequence[str]],
    query_tokens: Sequence[str],
    source_missing: Sequence[bool] | None = None,
) -> list[RankedTestClass]:
    """Score and sort a tokenized corpus: score desc, then FQCN asc."""
    n = len(test_classes)
    if len(document_token_lists) != n:
        raise LexicalInputError(
            f"tokenized docs {len(document_token_lists)} != classes {n}"
        )
    if source_missing is not None and len(source_missing) != n:
        raise LexicalInputError("source_missing length mismatch")
    missing = (
        list(source_missing)
        if source_missing is not None
        else [False] * n
    )

    scores = bm25_scores(query_tokens, document_token_lists)
    if len(scores) != n:
        raise LexicalInputError("bm25_scores length mismatch")

    for score in scores:
        if not math.isfinite(score):
            raise LexicalInputError(f"non-finite BM25 score: {score!r}")

    order = sorted(
        range(n),
        key=lambda i: (-scores[i], test_classes[i], i),
    )
    return [
        RankedTestClass(
            test_class=test_classes[i],
            score=float(scores[i]),
            rank=rank,
            source_missing=bool(missing[i]),
        )
        for rank, i in enumerate(order, start=1)
    ]


def cached_rank_suite(inputs: LexicalInputs, *, cache_dir: Path) -> SuiteRanking:
    """Reuse scoring by content, after callers re-read and hash source inputs."""
    signature = {**inputs.input_hashes, **bm25_provenance(), "cache_version": 1}
    key = _sha256_text(json.dumps(signature, sort_keys=True))
    path = cache_dir / f"{key}.json"
    if path.is_file():
        try:
            envelope = read_json(path)
            payload = envelope["ranking"]
            digest = _sha256_text(json.dumps(payload, sort_keys=True))
            if envelope.get("sha256") != digest:
                raise ValueError("cache content mismatch")
            result = SuiteRanking(**{**payload, "ranked": tuple(
                RankedTestClass(**row) for row in payload["ranked"])})
            if (result.input_hashes != {**inputs.input_hashes, **bm25_provenance()}
                    or result.qualified_id != inputs.qualified_id
                    or result.n_docs != len(inputs.documents)
                    or {r.test_class for r in result.ranked} != {d.test_class for d in inputs.documents}
                    or len(result.ranked) != len(inputs.documents)
                    or any(not math.isfinite(r.score) for r in result.ranked)):
                raise ValueError("cache provenance mismatch")
            return result
        except (OSError, ValueError, KeyError, TypeError):
            pass  # Corrupt cache is disposable; recompute from source inputs.
    result = rank_suite(inputs)
    payload = asdict(result)
    atomic_write_json(path, {"ranking": payload,
        "sha256": _sha256_text(json.dumps(payload, sort_keys=True))})
    return result


def rank_suite(inputs: LexicalInputs) -> SuiteRanking:
    """Full-suite BM25 ranking for one bug's lexical inputs.

    Corpus = every inventory / ``tests.all`` class. Scores are finite (including
    zero for no overlap). Order: descending BM25, ascending FQCN on ties.
    """
    test_classes = [d.test_class for d in inputs.documents]
    doc_tokens = [tokenize_document(d.text) for d in inputs.documents]
    query_tokens = tokenize_query(inputs.query.text)
    missing = [d.source_missing for d in inputs.documents]

    ranked = rank_tokenized_corpus(
        test_classes=test_classes,
        document_token_lists=doc_tokens,
        query_tokens=query_tokens,
        source_missing=missing,
    )
    stats = bm25_corpus_stats(doc_tokens)
    # Distinct query terms (same policy as scorer).
    seen: set[str] = set()
    distinct = 0
    for tok in query_tokens:
        if tok in seen:
            continue
        seen.add(tok)
        distinct += 1

    hashes = dict(inputs.input_hashes)
    hashes.update(bm25_provenance())

    return SuiteRanking(
        example_id=inputs.example_id,
        qualified_id=inputs.qualified_id,
        ranked=tuple(ranked),
        n_docs=int(stats["n_docs"]),
        avgdl=float(stats["avgdl"]),
        query_token_count=len(query_tokens),
        distinct_query_terms=distinct,
        bm25_version=BM25_VERSION,
        k1=BM25_K1,
        b=BM25_B,
        input_hashes=hashes,
    )


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_lines(lines: Sequence[str]) -> str:
    """Hash a deterministic newline-terminated line list."""
    payload = "".join(f"{line}\n" for line in lines)
    return _sha256_text(payload)


def compose_document_text(*, test_class: str, source_text: str | None) -> str:
    """Assemble one BM25 document string.

    Available source → ``{FQCN}\\n{entire fixed-revision source}``.
    Missing source → FQCN only (no fabricated body).
    """
    if not test_class:
        raise LexicalInputError("empty test_class")
    if source_text is None:
        return test_class
    return f"{test_class}{DOCUMENT_JOIN}{source_text}"


def build_document_from_source_entry(
    entry: Mapping[str, Any],
    *,
    checkout_fixed: Path,
) -> LexicalDocument:
    """Build one document from an inventory ``source_map`` entry.

    If ``source_missing`` is true, the document is the FQCN alone.
    If ``source_missing`` is false, the mapped file must exist under the fixed
    checkout; absence is a hard error (no fallback to compact representations).
    """
    test_class = entry.get("test_class")
    if not isinstance(test_class, str) or not test_class:
        raise LexicalInputError(f"invalid source_map entry test_class: {entry!r}")

    source_missing = bool(entry.get("source_missing", False))
    source_file = entry.get("source_file")
    if source_file is not None and not isinstance(source_file, str):
        raise LexicalInputError(
            f"{test_class}: source_file must be str or null, got {type(source_file)}"
        )

    if source_missing or not source_file:
        text = compose_document_text(test_class=test_class, source_text=None)
        return LexicalDocument(
            test_class=test_class,
            text=text,
            source_file=None,
            source_missing=True,
            text_sha256=_sha256_text(text),
        )

    path = checkout_fixed / source_file
    if not path.is_file():
        raise LexicalInputError(
            f"{test_class}: inventory marks source available at {source_file!r} "
            f"but file is missing under fixed checkout {checkout_fixed} "
            f"(refusing compact-representation fallback)"
        )
    try:
        source_text = read_fixed_source(path)
    except Exception as exc:  # noqa: BLE001 — surface as contract failure
        raise LexicalInputError(
            f"{test_class}: failed to read fixed source {source_file!r}: {exc}"
        ) from exc

    text = compose_document_text(test_class=test_class, source_text=source_text)
    return LexicalDocument(
        test_class=test_class,
        text=text,
        source_file=source_file,
        source_missing=False,
        text_sha256=_sha256_text(text),
    )


def build_query_from_patch_artifacts(
    *,
    representation_path: Path,
    patch_meta: Mapping[str, Any] | None = None,
) -> LexicalQuery:
    """Load the locked model-visible patch representation as the BM25 query.

    ``representation.txt`` already encodes modified file paths, modified class
    names, and the (possibly capped) proposed unified diff. That entire file is
    the query text so lexical BM25 sees the same change context as semantic
    rankers.
    """
    if not representation_path.is_file():
        raise LexicalInputError(f"missing patch representation: {representation_path}")
    try:
        text = representation_path.read_text(
            encoding=SOURCE_ENCODING,
            errors=SOURCE_ENCODING_ERRORS,
        )
    except UnicodeDecodeError as exc:
        raise LexicalInputError(
            f"UTF-8 decode failed for {representation_path}: {exc}"
        ) from exc
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    meta = patch_meta or {}
    modified_files = tuple(meta.get("modified_files") or ())
    modified_classes = tuple(meta.get("modified_classes") or ())
    if PRIVATE_LABEL_FIELDS.intersection(meta.keys()):
        raise LexicalInputError("patch_meta contains private label fields")

    try:
        rel = str(representation_path.resolve().relative_to(_REPO_ROOT.resolve()))
    except ValueError:
        rel = str(representation_path)

    return LexicalQuery(
        text=text,
        diff_source=QUERY_DIFF_SOURCE,
        query_sha256=_sha256_text(text),
        modified_files=modified_files,
        modified_classes=modified_classes,
        representation_path=rel,
        patch_truncated=meta.get("patch_truncated"),
    )


def compute_lexical_input_hashes(
    *,
    test_classes: Sequence[str],
    query: LexicalQuery,
    documents: Sequence[LexicalDocument],
    inventory_path: Path,
    representation_path: Path,
) -> dict[str, Any]:
    """Deterministic hashes for stale-ranking detection."""
    if len(documents) != len(test_classes):
        raise LexicalInputError(
            f"document count {len(documents)} != test_classes {len(test_classes)}"
        )
    for fqcn, doc in zip(test_classes, documents):
        if doc.test_class != fqcn:
            raise LexicalInputError(
                f"document order mismatch: expected {fqcn}, got {doc.test_class}"
            )

    per_doc = [f"{d.test_class}:{d.text_sha256}" for d in documents]
    hashes: dict[str, Any] = {
        "lexical_input_contract_version": LEXICAL_INPUT_CONTRACT_VERSION,
        "query_diff_source": QUERY_DIFF_SOURCE,
        "test_class_ids_sha256": _sha256_lines(list(test_classes)),
        "query_sha256": query.query_sha256,
        "documents_sha256": _sha256_lines(per_doc),
        "inventory_sha256": sha256_file(inventory_path),
        "patch_representation_sha256": sha256_file(representation_path),
        "num_documents": len(documents),
        "source_missing_count": sum(1 for d in documents if d.source_missing),
    }
    hashes.update(tokenizer_provenance())
    return hashes


def build_lexical_inputs(
    example: ExampleId | str,
    *,
    data_root: Path | None = None,
    manifest: Mapping[str, Any] | None = None,
    allow_evaluation: bool = False,
    require_complete: bool = True,
) -> LexicalInputs:
    """Build query + one full-source document per inventory test class.

    Does not open ``labels.json`` or any trigger export. Compact test
    representations under ``representations/`` are ignored.
    """
    loaded = load_example(
        example,
        data_root=data_root,
        manifest=manifest,
        require_complete=require_complete,
        allow_evaluation=allow_evaluation,
    )
    ex: ExampleId = loaded["example_id"]
    paths = loaded["paths"]

    inventory_path = paths["test_inventory"]
    representation_path = paths["patch_representation"]
    checkout_fixed = paths["checkout_fixed"]
    if not checkout_fixed.is_dir():
        raise LexicalInputError(
            f"{ex.qualified}: fixed checkout missing at {checkout_fixed}"
        )

    inventory = read_json(inventory_path)
    assert_no_private_fields(inventory, context=f"{ex.qualified} inventory")
    leaked = PRIVATE_LABEL_FIELDS.intersection(inventory.keys())
    if leaked:
        raise LexicalInputError(
            f"{ex.qualified}: private fields in inventory: {sorted(leaked)}"
        )

    test_classes = inventory.get("test_classes")
    source_map = inventory.get("source_map")
    if not isinstance(test_classes, list) or not test_classes:
        raise LexicalInputError(f"{ex.qualified}: empty test_classes")
    if not isinstance(source_map, list) or len(source_map) != len(test_classes):
        raise LexicalInputError(
            f"{ex.qualified}: source_map missing or length mismatch "
            f"({0 if not isinstance(source_map, list) else len(source_map)} "
            f"vs {len(test_classes)})"
        )

    by_class = {entry.get("test_class"): entry for entry in source_map}
    documents: list[LexicalDocument] = []
    for fqcn in test_classes:
        entry = by_class.get(fqcn)
        if entry is None:
            raise LexicalInputError(f"{ex.qualified}: source_map missing {fqcn}")
        documents.append(
            build_document_from_source_entry(entry, checkout_fixed=checkout_fixed)
        )

    patch_meta = None
    if paths["patch_meta"].is_file():
        patch_meta = read_json(paths["patch_meta"])
        assert_no_private_fields(patch_meta, context=f"{ex.qualified} patch_meta")

    query = build_query_from_patch_artifacts(
        representation_path=representation_path,
        patch_meta=patch_meta,
    )

    hashes = compute_lexical_input_hashes(
        test_classes=test_classes,
        query=query,
        documents=documents,
        inventory_path=inventory_path,
        representation_path=representation_path,
    )

    return LexicalInputs(
        example_id=ex.slug,
        qualified_id=ex.qualified,
        query=query,
        documents=tuple(documents),
        input_hashes=hashes,
        source_missing_count=hashes["source_missing_count"],
    )


def lexical_inputs_to_summary(inputs: LexicalInputs) -> dict[str, Any]:
    """Compact, label-free summary suitable for logs / provenance."""
    return {
        "example_id": inputs.example_id,
        "qualified_id": inputs.qualified_id,
        "num_documents": len(inputs.documents),
        "source_missing_count": inputs.source_missing_count,
        "query_diff_source": inputs.query.diff_source,
        "query_chars": len(inputs.query.text),
        "input_hashes": inputs.input_hashes,
        "documents": [
            {
                "test_class": d.test_class,
                "source_missing": d.source_missing,
                "source_file": d.source_file,
                "text_sha256": d.text_sha256,
                "text_chars": len(d.text),
            }
            for d in inputs.documents
        ],
    }


def _cli(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build BM25 lexical inputs / suite ranking for one example."
    )
    parser.add_argument("example_id", help="Qualified id or slug (e.g. Cli-30)")
    parser.add_argument(
        "--data-root",
        type=Path,
        default=None,
        help="Override data root (default: container /workspace/data)",
    )
    parser.add_argument(
        "--show-query-head",
        type=int,
        default=0,
        help="Print the first N characters of the query text",
    )
    parser.add_argument(
        "--rank",
        action="store_true",
        help="Score and print the full-suite BM25 ranking summary",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=5,
        help="With --rank, print this many top FQCNs (default 5)",
    )
    args = parser.parse_args(argv)

    try:
        inputs = build_lexical_inputs(
            args.example_id,
            data_root=args.data_root,
        )
    except (LexicalInputError, ExampleContractError, ExampleIncompleteError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    summary = lexical_inputs_to_summary(inputs)
    print(
        f"{summary['qualified_id']}: docs={summary['num_documents']} "
        f"missing_src={summary['source_missing_count']} "
        f"query_chars={summary['query_chars']} "
        f"diff_source={inputs.query.diff_source}"
    )
    print(f"  test_class_ids_sha256={inputs.input_hashes['test_class_ids_sha256']}")
    print(f"  query_sha256={inputs.input_hashes['query_sha256']}")
    print(f"  documents_sha256={inputs.input_hashes['documents_sha256']}")
    print(
        f"  inventory_sha256={inputs.input_hashes['inventory_sha256']}"
    )
    print(
        "  patch_representation_sha256="
        f"{inputs.input_hashes['patch_representation_sha256']}"
    )
    if args.show_query_head > 0:
        head = inputs.query.text[: args.show_query_head]
        print("--- query head ---")
        print(head)
    if args.rank:
        ranking = rank_suite(inputs)
        print(
            f"  bm25={ranking.bm25_version} k1={ranking.k1} b={ranking.b} "
            f"N={ranking.n_docs} avgdl={ranking.avgdl:.2f} "
            f"q_terms={ranking.distinct_query_terms}"
        )
        for entry in ranking.ranked[: max(0, args.top)]:
            print(
                f"  #{entry.rank} score={entry.score:.6f} {entry.test_class}"
            )
    return 0


# ---------------------------------------------------------------------------
# P5-08 semantic assembly — lazy re-exports (avoid candidates ↔ ranking cycle).
# Implementation: ``src.assemble_rankings``.
# ---------------------------------------------------------------------------
_ASSEMBLY_EXPORTS = frozenset(
    {
        "AssembleError",
        "AssembledRanking",
        "assemble_from_scores",
        "assemble_gpt_ranking",
        "assemble_jev_ranking",
        "semantic_ranking_path",
    }
)


def __getattr__(name: str):  # pragma: no cover - import plumbing
    if name in _ASSEMBLY_EXPORTS:
        from src import assemble_rankings as _assemble

        return getattr(_assemble, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


if __name__ == "__main__":
    raise SystemExit(_cli())
