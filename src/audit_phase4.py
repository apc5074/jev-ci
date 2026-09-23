"""Phase 4 retrieval integrity audit (development rankings + shortlists).

Validates every development BM25 ranking against the fixed-base inventory and
every candidate shortlist as its exact prefix. Computes **development-only**
candidate trigger recall (diagnostics; not the evaluation metric).

Phase 5 contract: ``load_candidates`` + ``shortlist_content_hash`` /
``require_hash`` — Jev and GPT must consume the same ordered IDs.
"""

from __future__ import annotations

import argparse
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.candidates import (
    CANDIDATE_K_CAP,
    CandidatesError,
    candidate_k,
    candidate_path,
    load_candidates,
    load_ranking,
    ranking_path,
    shortlist_content_hash,
    verify_shortlist_is_ranking_prefix,
)
from src.example_contract import (
    WORKSPACE,
    ExampleContractError,
    ExampleId,
    atomic_write_json,
    development_example_ids,
    load_manifest,
    validate_example_artifacts,
)
from src.select_bugs import ManifestError, verify_manifest_integrity
from src.ranking import build_lexical_inputs, LexicalInputError
from src.bm25 import bm25_provenance


class AuditError(Exception):
    """One or more Phase 4 integrity checks failed."""


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def assert_ranking_sorted(ranking_entries: Sequence[Mapping[str, Any]]) -> None:
    """Score desc, then FQCN asc; ranks are contiguous 1..N."""
    if not ranking_entries:
        raise AuditError("empty ranking")
    prev_key: tuple[float, str] | None = None
    for i, entry in enumerate(ranking_entries):
        fqcn = entry.get("test_class")
        score = entry.get("score")
        rank = entry.get("rank")
        if not isinstance(fqcn, str) or not fqcn:
            raise AuditError(f"ranking[{i}]: bad test_class")
        if not isinstance(score, (int, float)) or not math.isfinite(float(score)):
            raise AuditError(f"{fqcn}: non-finite score {score!r}")
        if rank != i + 1:
            raise AuditError(f"{fqcn}: rank {rank} != expected {i + 1}")
        key = (-float(score), fqcn)
        if prev_key is not None and key < prev_key:
            raise AuditError(
                f"ordering violation at rank {rank}: {fqcn} key={key} prev={prev_key}"
            )
        prev_key = key


def audit_one_example(
    example: ExampleId | str,
    *,
    data_root: Path | None = None,
    results_root: Path | None = None,
    manifest: Mapping[str, Any] | None = None,
    allow_evaluation: bool = False,
    require_experiment_commit: bool = False,
) -> dict[str, Any]:
    """Integrity-check one ranking/shortlist pair."""
    data = manifest if manifest is not None else load_manifest()
    ex = example if isinstance(example, ExampleId) else ExampleId.parse(example)
    data_root = data_root or (WORKSPACE / "data")
    results_root = results_root or (WORKSPACE / "results")

    validated = validate_example_artifacts(
        ex,
        data_root=data_root,
        manifest=data,
        allow_evaluation=allow_evaluation,
    )
    inventory = validated["inventory"]
    labels = validated["labels"]
    inventory_classes: list[str] = list(inventory["test_classes"])
    positives: list[str] = list(labels.get("positive_classes") or [])
    if not positives:
        raise AuditError(f"{ex.qualified}: no positive_classes")

    candidates = load_candidates(ex, data_root=data_root)
    ranking = load_ranking(ex, results_root=results_root)
    verify_shortlist_is_ranking_prefix(candidates=candidates, ranking=ranking)

    n = candidates["N"]
    k = candidates["K"]
    if n != len(inventory_classes):
        raise AuditError(
            f"{ex.qualified}: N={n} != inventory size {len(inventory_classes)}"
        )
    if k != candidate_k(n=n):
        raise AuditError(f"{ex.qualified}: K={k} != min({CANDIDATE_K_CAP}, {n})")

    rank_entries = ranking.get("ranking") or []
    if len(rank_entries) != n:
        raise AuditError(
            f"{ex.qualified}: ranking length {len(rank_entries)} != N={n}"
        )
    ranked_ids = [e["test_class"] for e in rank_entries]
    if len(ranked_ids) != len(set(ranked_ids)):
        raise AuditError(f"{ex.qualified}: duplicate ranking IDs")
    if set(ranked_ids) != set(inventory_classes):
        missing = sorted(set(inventory_classes) - set(ranked_ids))
        extra = sorted(set(ranked_ids) - set(inventory_classes))
        raise AuditError(
            f"{ex.qualified}: ranking is not a permutation of inventory "
            f"(missing={missing[:5]} extra={extra[:5]})"
        )
    assert_ranking_sorted(rank_entries)
    for entry in rank_entries:
        score = entry.get("score")
        if score is None or not math.isfinite(float(score)):
            raise AuditError(f"{ex.qualified}: non-finite BM25 score")

    # Provenance / hash consistency between artifacts.
    if candidates.get("shortlist_sha256") != ranking.get("shortlist_sha256"):
        raise AuditError(f"{ex.qualified}: shortlist_sha256 mismatch")
    digest = shortlist_content_hash(candidates["candidate_ids"])
    if digest != candidates["shortlist_sha256"]:
        raise AuditError(f"{ex.qualified}: recomputed shortlist hash mismatch")
    for key in ("defects4j_commit", "selection_seed"):
        c_val = (candidates.get("manifest") or {}).get(key)
        r_val = (ranking.get("manifest") or {}).get(key)
        m_val = data.get(key)
        if c_val != m_val or r_val != m_val:
            raise AuditError(
                f"{ex.qualified}: manifest.{key} mismatch "
                f"(candidates={c_val!r}, ranking={r_val!r}, manifest={m_val!r})"
            )

    if require_experiment_commit:
        from src.freeze_guard import assert_evaluation_allowed

        lock = assert_evaluation_allowed()
        expected = lock.get("commit_sha")
        for label, doc in (("candidates", candidates), ("ranking", ranking)):
            if doc.get("experiment_commit") != expected:
                raise AuditError(
                    f"{ex.qualified}: {label} experiment_commit "
                    f"{doc.get('experiment_commit')!r} != {expected!r}"
                )
            if doc.get("split") != "evaluation":
                raise AuditError(f"{ex.qualified}: {label} split is not evaluation")

    current = build_lexical_inputs(
        ex,
        data_root=data_root,
        manifest=data,
        allow_evaluation=allow_evaluation,
    )
    expected_hashes = {**current.input_hashes, **bm25_provenance()}
    if ranking.get("input_hashes") != expected_hashes:
        raise AuditError(f"{ex.qualified}: ranking inputs are stale")
    if any(expected_hashes.get(key) != value
           for key, value in candidates.get("input_hashes", {}).items()):
        raise AuditError(f"{ex.qualified}: candidate inputs are stale")

    # Development diagnostic only — labels never enter candidate files.
    # Evaluation audits omit trigger-in-shortlist metrics (Phase 8 owns recall).
    top_ids = candidates["candidate_ids"]
    hits = [p for p in positives if p in top_ids] if not allow_evaluation else []
    first_trigger_rank = None
    if positives and not allow_evaluation:
        first_trigger_rank = min(ranked_ids.index(p) + 1 for p in positives)

    # Ensure candidate file has no private label fields (already asserted by loader).
    for field in ("positive_classes", "trigger_methods"):
        if field in candidates or field in ranking:
            raise AuditError(f"{ex.qualified}: private field leaked into artifacts")

    row = {
        "qualified_id": ex.qualified,
        "ok": True,
        "N": n,
        "K": k,
        "num_positive_classes": len(positives),
        "shortlist_sha256": digest,
        "source_missing_count": ranking.get("source_missing_count", 0),
        "experiment_commit": candidates.get("experiment_commit"),
    }
    if not allow_evaluation:
        row["trigger_in_top_k"] = bool(hits)
        row["num_triggers_in_top_k"] = len(hits)
        row["first_trigger_rank"] = first_trigger_rank
    return row


def retrieval_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Development diagnostics, using full-suite first-trigger ranks."""
    n = len(rows)
    return {
        "bugs": n,
        "fdr_at_10_percent": sum(r["first_trigger_rank"] <= max(1, math.ceil(.10 * r["N"])) for r in rows) / n if n else None,
        "mrr": sum(1 / r["first_trigger_rank"] for r in rows) / n if n else None,
        "mean_first_trigger_rank": sum(r["first_trigger_rank"] for r in rows) / n if n else None,
        "candidate_recall": sum(r["trigger_in_top_k"] for r in rows) / n if n else None,
        "whole_suite_shortlists": sum(r["K"] == r["N"] for r in rows),
    }


def audit_development_set(
    *,
    data_root: Path | None = None,
    results_root: Path | None = None,
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    """Audit all 25 development rankings/shortlists + candidate recall."""
    data = load_manifest(manifest_path)
    try:
        verify_manifest_integrity(data)
    except ManifestError as exc:
        raise ExampleContractError(f"manifest integrity failed: {exc}") from exc

    data_root = data_root or (WORKSPACE / "data")
    results_root = results_root or (WORKSPACE / "results")
    targets = development_example_ids(data)

    rows: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for ex in targets:
        try:
            row = audit_one_example(
                ex,
                data_root=data_root,
                results_root=results_root,
                manifest=data,
            )
            rows.append(row)
        except (AuditError, CandidatesError, ExampleContractError, LexicalInputError, OSError) as exc:
            failed.append({"qualified_id": ex.qualified, "ok": False, "error": str(exc)})
            rows.append(
                {"qualified_id": ex.qualified, "ok": False, "error": str(exc)}
            )

    passed = [r for r in rows if r.get("ok")]
    recall_hits = sum(1 for r in passed if r.get("trigger_in_top_k"))
    recall_denom = len(passed)
    candidate_trigger_recall = (
        recall_hits / recall_denom if recall_denom else 0.0
    )

    # Case inspection: earliest / latest first-trigger ranks among hits.
    with_rank = [
        r for r in passed if r.get("first_trigger_rank") is not None
    ]
    with_rank_sorted = sorted(with_rank, key=lambda r: int(r["first_trigger_rank"]))
    case_inspection = {
        "note": (
            "Development diagnostics only. Do not tune K, expand queries, or "
            "change the corpus from these ranks. Freeze methodology in Phase 6."
        ),
        "high_retrieval": [
            {
                "qualified_id": r["qualified_id"],
                "first_trigger_rank": r["first_trigger_rank"],
                "N": r["N"],
                "K": r["K"],
            }
            for r in with_rank_sorted[:3]
        ],
        "low_retrieval": [
            {
                "qualified_id": r["qualified_id"],
                "first_trigger_rank": r["first_trigger_rank"],
                "N": r["N"],
                "K": r["K"],
            }
            for r in with_rank_sorted[-3:]
        ],
        "misses": [
            r["qualified_id"] for r in passed if not r.get("trigger_in_top_k")
        ],
    }

    # No evaluation candidate/ranking artifacts should exist yet.
    evaluation_artifacts: list[str] = []
    for raw in data.get("evaluation_bug_ids") or []:
        ex = ExampleId.parse(str(raw))
        if candidate_path(ex, data_root=data_root).is_file():
            evaluation_artifacts.append(f"candidates:{ex.qualified}")
        if ranking_path(ex, results_root=results_root).is_file():
            evaluation_artifacts.append(f"ranking:{ex.qualified}")

    report = {
        "audited_at": _utcnow(),
        "split": "development",
        "metric_scope": "development_only",
        "defects4j_commit": data.get("defects4j_commit"),
        "selection_seed": data.get("selection_seed"),
        "k_cap": CANDIDATE_K_CAP,
        "counts": {
            "targets": len(targets),
            "passed": len(passed),
            "failed": len(failed),
            "evaluation_artifacts_forbidden": len(evaluation_artifacts),
        },
        "failed_ids": [r["qualified_id"] for r in failed],
        "evaluation_artifact_ids": evaluation_artifacts,
        "candidate_trigger_recall_at_k": {
            "definition": (
                "Fraction of development bugs with at least one known "
                "triggering class in the BM25 top K (K=min(200,N)). "
                "Not the 125-bug evaluation metric."
            ),
            "bugs_with_trigger_in_top_k": recall_hits,
            "bugs_audited": recall_denom,
            "recall": candidate_trigger_recall,
        },
        "retrieval_metrics": {
            "scope": "development_only",
            "complete": not failed,
            "all": retrieval_metrics(passed),
            "suites_over_200": retrieval_metrics([r for r in passed if r["N"] > 200]),
            "by_project": {project: retrieval_metrics([
                r for r in passed if r["qualified_id"].split("-")[0] == project])
                for project in sorted({r["qualified_id"].split("-")[0] for r in passed})},
        },
        "case_inspection": case_inspection,
        "phase5_contract": {
            "reader": "src.candidates.load_candidates",
            "content_hash": "src.candidates.shortlist_content_hash",
            "require_hash_arg": "load_candidates(..., require_hash=...)",
            "rule": (
                "Jev and GPT receive the same ordered candidate_ids; each "
                "reranks that prefix and appends the untouched BM25 tail."
            ),
        },
        "examples": rows,
        "ok": (
            not failed
            and not evaluation_artifacts
            and len(passed) == 25
            and len(targets) == 25
        ),
    }
    return report


def audit_evaluation_set(
    *,
    data_root: Path | None = None,
    results_root: Path | None = None,
    manifest_path: Path | None = None,
    experiment_commit: str | None = None,
) -> dict[str, Any]:
    """Audit all 125 evaluation rankings/shortlists (P7-03). No recall metrics."""
    data = load_manifest(manifest_path)
    try:
        verify_manifest_integrity(data)
    except ManifestError as exc:
        raise ExampleContractError(f"manifest integrity failed: {exc}") from exc

    data_root = data_root or (WORKSPACE / "data")
    results_root = results_root or (WORKSPACE / "results")
    raw_ids = list(data.get("evaluation_bug_ids") or [])
    targets = [ExampleId.parse(str(raw)) for raw in raw_ids]

    rows: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for ex in targets:
        try:
            row = audit_one_example(
                ex,
                data_root=data_root,
                results_root=results_root,
                manifest=data,
                allow_evaluation=True,
                require_experiment_commit=True,
            )
            rows.append(row)
        except (
            AuditError,
            CandidatesError,
            ExampleContractError,
            LexicalInputError,
            OSError,
        ) as exc:
            failed.append(
                {"qualified_id": ex.qualified, "ok": False, "error": str(exc)}
            )
            rows.append(
                {"qualified_id": ex.qualified, "ok": False, "error": str(exc)}
            )

    passed = [r for r in rows if r.get("ok")]
    return {
        "schema_version": "jev-phase7-candidates-audit-v1",
        "audited_at": _utcnow(),
        "split": "evaluation",
        "metric_scope": "integrity_only_no_recall",
        "experiment_commit": experiment_commit,
        "defects4j_commit": data.get("defects4j_commit"),
        "selection_seed": data.get("selection_seed"),
        "k_cap": CANDIDATE_K_CAP,
        "counts": {
            "targets": len(targets),
            "passed": len(passed),
            "failed": len(failed),
            "N_total": sum(int(r.get("N") or 0) for r in passed),
            "K_total": sum(int(r.get("K") or 0) for r in passed),
        },
        "failed_ids": [r["qualified_id"] for r in failed],
        "examples": rows,
        "ok": not failed and len(passed) == 125,
        "notes": (
            "Shortlists sealed as BM25 ranking prefixes. Candidate trigger "
            "recall is deferred to Phase 8; not computed here."
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit Phase 4 BM25 rankings and candidate shortlists",
    )
    parser.add_argument(
        "--split",
        choices=("development", "evaluation"),
        default="development",
        help="Manifest split to audit",
    )
    parser.add_argument(
        "--write",
        type=Path,
        default=None,
        help="Where to write the JSON audit report",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    write_path = args.write
    if write_path is None:
        if args.split == "evaluation":
            write_path = WORKSPACE / "results" / "phase7" / "candidates_audit.json"
        else:
            write_path = WORKSPACE / "results" / "audit-phase4.json"

    try:
        if args.split == "evaluation":
            from src.freeze_guard import assert_evaluation_allowed

            lock = assert_evaluation_allowed()
            report = audit_evaluation_set(
                experiment_commit=lock.get("commit_sha"),
            )
        else:
            report = audit_development_set()
    except ExampleContractError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    write_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(write_path, report)
    counts = report["counts"]
    print(
        f"audit phase4 ({report['split']}): "
        f"passed={counts['passed']}/{counts['targets']} "
        f"failed={counts['failed']} "
        f"report={write_path}",
        flush=True,
    )
    if report.get("candidate_trigger_recall_at_k"):
        recall = report["candidate_trigger_recall_at_k"]
        print(
            f"dev_candidate_recall@K="
            f"{recall['bugs_with_trigger_in_top_k']}/{recall['bugs_audited']} "
            f"({recall['recall']:.1%})",
            flush=True,
        )
    if report.get("case_inspection", {}).get("misses"):
        print(
            "misses: " + ", ".join(report["case_inspection"]["misses"]),
            file=sys.stderr,
        )
    if counts["failed"]:
        print(
            "failed ids: " + ", ".join(report["failed_ids"]),
            file=sys.stderr,
        )
        return 1
    if not report["ok"]:
        print("audit phase4: report not ok", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
