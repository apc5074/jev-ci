"""Offline loader for sealed Phase 7 evaluation inputs (P8-01).

Read-only. Verifies the Phase 7 seal / raw-result index hashes, loads
manifest + labels + rankings + Random contracts, and rejects missing or
tampered artifacts. Never makes provider calls or rebuilds rankings.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.example_contract import (
    WORKSPACE,
    ExampleId,
    PRIVATE_LABEL_FIELDS,
    atomic_write_json,
    load_manifest,
    read_json,
    sha256_file,
)
from src.export_predictions import ACCEPTED_JEV_GAPS
from src.random_baseline import evaluation_example_ids, resolve_bug_seed
from src.select_bugs import ManifestError, verify_manifest_integrity

SEAL_PATH = WORKSPACE / "results" / "phase7" / "raw_evaluation_seal.json"
INDEX_PATH = WORKSPACE / "results" / "phase7" / "raw_result_index.json"
VALIDATION_PATH = WORKSPACE / "results" / "phase8" / "input_validation.json"
VALIDATION_SCHEMA = "jev-phase8-input-validation-v1"

REQUIRED_PROJECTS = ("Cli", "Lang", "Math", "Jsoup", "JacksonDatabind")
NONRANDOM_METHODS = ("BM25", "Embedding", "Jev", "GPT-Nano")
ALL_METHODS = (*NONRANDOM_METHODS, "Random")
API_ENV_KEYS = (
    "OPENROUTER_API_KEY",
    "OPENAI_API_KEY",
    "TYPESAFE_API_KEY",
    "ANTHROPIC_API_KEY",
)


class InputValidationError(Exception):
    """Sealed evaluation inputs failed offline verification."""


@dataclass(frozen=True)
class BugInputs:
    """Per-bug sealed artifacts for offline metric calculation."""

    example: ExampleId
    inventory_classes: tuple[str, ...]
    positive_classes: tuple[str, ...]
    candidates: Mapping[str, Any]
    bm25_ranking: Mapping[str, Any]
    embedding_ranking: Mapping[str, Any]
    gpt_ranking: Mapping[str, Any]
    random_contract: Mapping[str, Any]
    jev_ranking: Mapping[str, Any] | None
    accepted_jev_gap: bool
    N: int
    K: int


@dataclass
class SealedEvaluationBundle:
    """Verified Phase 7 snapshot ready for Phase 8 metrics (no network)."""

    workspace: Path
    seal: Mapping[str, Any]
    index: Mapping[str, Any]
    manifest: Mapping[str, Any]
    freeze_lock: Mapping[str, Any]
    pricing_snapshot: Mapping[str, Any]
    experiment_commit: str
    run_id: str
    freeze_tag: str
    predictions_path: Path
    predictions_sha256: str
    usage_ledger_path: Path
    bugs: dict[str, BugInputs] = field(default_factory=dict)
    validation_report: dict[str, Any] = field(default_factory=dict)

    def bug(self, qualified_id: str) -> BugInputs:
        try:
            return self.bugs[qualified_id]
        except KeyError as exc:
            raise InputValidationError(f"unknown evaluation bug {qualified_id}") from exc

    def example_ids(self) -> tuple[ExampleId, ...]:
        return tuple(b.example for b in self.bugs.values())


def _utcnow() -> str:
    return datetime.now().astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _rel(path: Path, *, workspace: Path) -> str:
    try:
        return str(path.resolve().relative_to(workspace.resolve()))
    except ValueError:
        return str(path)


def clear_provider_credentials() -> dict[str, bool]:
    """Remove provider API keys from the process environment (offline mode)."""
    cleared: dict[str, bool] = {}
    for key in API_ENV_KEYS:
        cleared[key] = key in os.environ
        os.environ.pop(key, None)
    return cleared


def _read_tests_all(path: Path) -> list[str]:
    if not path.is_file():
        raise InputValidationError(f"missing tests.all: {path}")
    lines = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not lines:
        raise InputValidationError(f"empty tests.all: {path}")
    if len(lines) != len(set(lines)):
        raise InputValidationError(f"duplicate IDs in tests.all: {path}")
    return lines


def _ranking_ids(doc: Mapping[str, Any]) -> list[str]:
    if "ranked_ids" in doc and isinstance(doc["ranked_ids"], list):
        return list(doc["ranked_ids"])
    ranking = doc.get("ranking") or []
    return [str(e["test_class"]) for e in ranking]


def _assert_permutation(
    ids: Sequence[str],
    *,
    inventory: Sequence[str],
    label: str,
) -> None:
    if len(ids) != len(inventory) or set(ids) != set(inventory):
        raise InputValidationError(f"{label}: ranking is not a permutation of inventory")
    if len(ids) != len(set(ids)):
        raise InputValidationError(f"{label}: duplicate class IDs in ranking")


def _verify_file_hash(path: Path, expected: str, *, label: str) -> str:
    if not path.is_file():
        raise InputValidationError(f"{label}: missing file {path}")
    digest = sha256_file(path)
    if digest != expected:
        raise InputValidationError(
            f"{label}: sha256 mismatch for {path} "
            f"(expected {expected[:16]}…, got {digest[:16]}…)"
        )
    return digest


def _index_entry_map(index: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for entry in index.get("artifacts") or []:
        path = entry.get("path")
        if isinstance(path, str):
            out[path] = entry
    return out


def _require_index_hash(
    *,
    workspace: Path,
    entries: Mapping[str, Mapping[str, Any]],
    relative: str,
    label: str,
) -> str:
    entry = entries.get(relative)
    if entry is None:
        raise InputValidationError(f"{label}: not in raw-result index ({relative})")
    return _verify_file_hash(
        workspace / relative,
        str(entry["sha256"]),
        label=label,
    )


def load_bug_inputs(
    example: ExampleId,
    *,
    workspace: Path,
    index_entries: Mapping[str, Mapping[str, Any]],
    expected_commit: str,
    manifest: Mapping[str, Any],
    accepted_gaps: Mapping[str, Any],
) -> BugInputs:
    slug = example.slug
    qid = example.qualified

    inventory_path = workspace / "data" / "tests" / slug / "inventory.json"
    labels_path = workspace / "data" / "tests" / slug / "labels.json"
    tests_all_path = workspace / "data" / "tests" / slug / "raw" / "tests.all"
    candidates_rel = f"data/candidates/{slug}.json"
    bm25_rel = f"results/rankings/{slug}.json"
    emb_rel = f"results/embeddings/{slug}.json"
    gpt_rel = f"results/semantic/gpt_nano/{slug}.json"
    jev_rel = f"results/semantic/jev/{slug}.json"
    random_rel = f"results/random/{slug}.json"

    _require_index_hash(
        workspace=workspace,
        entries=index_entries,
        relative=candidates_rel,
        label=f"{qid} candidates",
    )
    _require_index_hash(
        workspace=workspace,
        entries=index_entries,
        relative=bm25_rel,
        label=f"{qid} BM25",
    )
    _require_index_hash(
        workspace=workspace,
        entries=index_entries,
        relative=emb_rel,
        label=f"{qid} Embedding",
    )
    _require_index_hash(
        workspace=workspace,
        entries=index_entries,
        relative=gpt_rel,
        label=f"{qid} GPT-Nano",
    )
    _require_index_hash(
        workspace=workspace,
        entries=index_entries,
        relative=random_rel,
        label=f"{qid} Random",
    )
    _require_index_hash(
        workspace=workspace,
        entries=index_entries,
        relative=f"data/tests/{slug}/labels.json",
        label=f"{qid} labels",
    )
    _require_index_hash(
        workspace=workspace,
        entries=index_entries,
        relative=f"data/tests/{slug}/inventory.json",
        label=f"{qid} inventory",
    )

    inventory = read_json(inventory_path)
    labels = read_json(labels_path)
    # Labels are private analysis inputs — must not appear in model-visible rankings.
    for doc_name, doc in (
        ("inventory", inventory),
    ):
        leaked = PRIVATE_LABEL_FIELDS.intersection(doc.keys())
        if leaked:
            raise InputValidationError(
                f"{qid}: private fields in {doc_name}: {sorted(leaked)}"
            )

    inventory_classes = tuple(inventory["test_classes"])
    tests_all = _read_tests_all(tests_all_path)
    if list(inventory_classes) != tests_all:
        raise InputValidationError(
            f"{qid}: inventory.test_classes != raw/tests.all order/content"
        )

    positives = labels.get("positive_classes")
    if not isinstance(positives, list) or not positives:
        raise InputValidationError(f"{qid}: labels.positive_classes empty or missing")
    positive_classes = tuple(str(x) for x in positives)
    unknown = [c for c in positive_classes if c not in set(inventory_classes)]
    if unknown:
        raise InputValidationError(
            f"{qid}: trigger classes not in inventory: {unknown[:5]}"
        )

    candidates = read_json(workspace / candidates_rel)
    bm25 = read_json(workspace / bm25_rel)
    embedding = read_json(workspace / emb_rel)
    gpt = read_json(workspace / gpt_rel)
    random_doc = read_json(workspace / random_rel)

    for label, doc in (
        ("candidates", candidates),
        ("BM25", bm25),
        ("Embedding", embedding),
        ("GPT-Nano", gpt),
    ):
        commit = doc.get("experiment_commit")
        if commit is not None and commit != expected_commit:
            raise InputValidationError(
                f"{qid} {label}: experiment_commit {commit!r} != {expected_commit!r}"
            )
        leaked = PRIVATE_LABEL_FIELDS.intersection(doc.keys())
        if leaked:
            raise InputValidationError(
                f"{qid} {label}: private label fields leaked: {sorted(leaked)}"
            )

    n = int(candidates["N"])
    k = int(candidates["K"])
    if n != len(inventory_classes):
        raise InputValidationError(f"{qid}: candidates.N != inventory size")
    bm25_ids = _ranking_ids(bm25)
    if list(candidates["candidate_ids"]) != bm25_ids[:k]:
        raise InputValidationError(f"{qid}: candidates are not BM25 prefix")

    _assert_permutation(
        bm25_ids, inventory=inventory_classes, label=f"{qid} BM25"
    )
    _assert_permutation(
        _ranking_ids(embedding),
        inventory=inventory_classes,
        label=f"{qid} Embedding",
    )
    _assert_permutation(
        _ranking_ids(gpt), inventory=inventory_classes, label=f"{qid} GPT-Nano"
    )

    seed_info = resolve_bug_seed(example, split="evaluation", manifest=manifest)
    if int(random_doc.get("num_permutations") or 0) != 1000:
        raise InputValidationError(f"{qid}: Random must define 1000 permutations")
    if int(random_doc["seed"]) != seed_info.seed:
        raise InputValidationError(f"{qid}: Random seed mismatch")
    if int(random_doc.get("N") or 0) != n:
        raise InputValidationError(f"{qid}: Random N mismatch")

    gap = accepted_gaps.get(qid)
    jev_doc: Mapping[str, Any] | None = None
    jev_path = workspace / jev_rel
    if gap is not None:
        if jev_path.is_file():
            raise InputValidationError(
                f"{qid}: Jev ranking present despite accepted gap"
            )
        accepted_jev_gap = True
    else:
        _require_index_hash(
            workspace=workspace,
            entries=index_entries,
            relative=jev_rel,
            label=f"{qid} Jev",
        )
        jev_doc = read_json(jev_path)
        if jev_doc.get("experiment_commit") not in {None, expected_commit}:
            raise InputValidationError(f"{qid} Jev: experiment_commit mismatch")
        leaked = PRIVATE_LABEL_FIELDS.intersection(jev_doc.keys())
        if leaked:
            raise InputValidationError(
                f"{qid} Jev: private label fields leaked: {sorted(leaked)}"
            )
        _assert_permutation(
            _ranking_ids(jev_doc),
            inventory=inventory_classes,
            label=f"{qid} Jev",
        )
        if list(jev_doc.get("candidate_ids") or []) != list(
            candidates["candidate_ids"]
        ):
            raise InputValidationError(f"{qid}: Jev/candidates shortlist diverge")
        if list(gpt.get("candidate_ids") or []) != list(candidates["candidate_ids"]):
            raise InputValidationError(f"{qid}: GPT/candidates shortlist diverge")
        accepted_jev_gap = False

    return BugInputs(
        example=example,
        inventory_classes=inventory_classes,
        positive_classes=positive_classes,
        candidates=candidates,
        bm25_ranking=bm25,
        embedding_ranking=embedding,
        gpt_ranking=gpt,
        random_contract=random_doc,
        jev_ranking=jev_doc,
        accepted_jev_gap=accepted_jev_gap,
        N=n,
        K=k,
    )


def load_and_verify_sealed_inputs(
    *,
    workspace: Path | None = None,
    seal_path: Path | None = None,
    clear_credentials: bool = True,
    require_offline_env: bool = True,
) -> SealedEvaluationBundle:
    """Load the sealed Phase 7 snapshot and fail closed on any integrity error."""
    root = workspace or WORKSPACE
    cleared = clear_provider_credentials() if clear_credentials else {}
    if require_offline_env:
        present = [k for k in API_ENV_KEYS if os.environ.get(k)]
        if present:
            raise InputValidationError(
                f"provider credentials still set after clear: {present}"
            )

    seal_file = seal_path or (root / "results" / "phase7" / "raw_evaluation_seal.json")
    if not seal_file.is_file():
        raise InputValidationError(f"missing Phase 7 seal: {seal_file}")
    seal = read_json(seal_file)
    if not seal.get("ok"):
        raise InputValidationError("Phase 7 seal is not ok=true")
    if seal.get("schema_version") != "jev-raw-evaluation-seal-v1":
        raise InputValidationError(
            f"unsupported seal schema {seal.get('schema_version')!r}"
        )

    experiment_commit = str(seal["experiment_commit"])
    run_id = str(seal["run_id"])
    freeze_tag = str(seal.get("freeze_tag") or "experiment-v1")
    # overall.md historically named the tag experiment-v1-frozen; this study
    # froze as experiment-v1 (see freeze_lock / Phase 7 seal).
    if freeze_tag not in {"experiment-v1", "experiment-v1-frozen"}:
        raise InputValidationError(f"unexpected freeze_tag {freeze_tag!r}")

    freeze_lock = read_json(root / "results" / "phase6" / "freeze_lock.json")
    if freeze_lock.get("commit_sha") != experiment_commit:
        raise InputValidationError(
            "freeze_lock commit_sha does not match seal experiment_commit"
        )
    if freeze_lock.get("tag") not in {"experiment-v1", "experiment-v1-frozen"}:
        raise InputValidationError(
            f"freeze_lock tag {freeze_lock.get('tag')!r} rejected"
        )
    if not freeze_lock.get("validated"):
        raise InputValidationError("freeze_lock is not validated")

    index_rel = seal["raw_result_index"]["path"]
    index_path = root / index_rel
    _verify_file_hash(
        index_path,
        str(seal["raw_result_index"]["sha256"]),
        label="raw_result_index",
    )
    index = read_json(index_path)
    if index.get("experiment_commit") != experiment_commit:
        raise InputValidationError("raw-result index experiment_commit mismatch")

    pred_rel = seal["predictions"]["path"]
    predictions_path = root / pred_rel
    pred_hash = _verify_file_hash(
        predictions_path,
        str(seal["predictions"]["sha256"]),
        label="predictions.jsonl",
    )

    # Config refs from index
    entries = _index_entry_map(index)
    for kind, rel in (
        ("manifest", "data/manifest.json"),
        ("pricing_snapshot", "results/pricing_snapshot.json"),
        ("usage_ledger", "results/usage_ledger.jsonl"),
        ("freeze_lock", "results/phase6/freeze_lock.json"),
        ("experiment_yaml", "experiment.yaml"),
    ):
        _require_index_hash(
            workspace=root, entries=entries, relative=rel, label=kind
        )

    manifest = load_manifest(root / "data" / "manifest.json")
    try:
        verify_manifest_integrity(manifest)
    except ManifestError as exc:
        raise InputValidationError(f"manifest integrity failed: {exc}") from exc

    example_ids = evaluation_example_ids(manifest)
    if len(example_ids) != 125:
        raise InputValidationError(f"expected 125 evaluation IDs, got {len(example_ids)}")

    from collections import Counter

    projects = Counter(ex.project for ex in example_ids)
    for proj in REQUIRED_PROJECTS:
        if projects.get(proj) != 25:
            raise InputValidationError(
                f"project {proj} has {projects.get(proj)} evaluation bugs, want 25"
            )

    accepted_gaps = dict(seal.get("accepted_jev_gaps") or ACCEPTED_JEV_GAPS)
    if set(accepted_gaps) != set(ACCEPTED_JEV_GAPS):
        raise InputValidationError("seal accepted_jev_gaps diverges from exporter set")

    bugs: dict[str, BugInputs] = {}
    failures: list[dict[str, str]] = []
    method_coverage = {m: 0 for m in ALL_METHODS}
    for ex in example_ids:
        try:
            bug = load_bug_inputs(
                ex,
                workspace=root,
                index_entries=entries,
                expected_commit=experiment_commit,
                manifest=manifest,
                accepted_gaps=accepted_gaps,
            )
            bugs[ex.qualified] = bug
            method_coverage["BM25"] += 1
            method_coverage["Embedding"] += 1
            method_coverage["GPT-Nano"] += 1
            method_coverage["Random"] += 1
            if bug.jev_ranking is not None:
                method_coverage["Jev"] += 1
        except (InputValidationError, OSError, KeyError, TypeError, ValueError) as exc:
            failures.append({"qualified_id": ex.qualified, "error": str(exc)})

    if failures:
        sample = failures[:3]
        raise InputValidationError(
            f"{len(failures)} evaluation bugs failed input validation "
            f"(e.g. {sample})"
        )

    if method_coverage["BM25"] != 125 or method_coverage["Embedding"] != 125:
        raise InputValidationError(f"incomplete baseline coverage: {method_coverage}")
    if method_coverage["GPT-Nano"] != 125 or method_coverage["Random"] != 125:
        raise InputValidationError(f"incomplete GPT/Random coverage: {method_coverage}")
    if method_coverage["Jev"] != 125 - len(accepted_gaps):
        raise InputValidationError(
            f"Jev coverage {method_coverage['Jev']} != "
            f"{125 - len(accepted_gaps)} (125 minus accepted gaps)"
        )

    # Predictions line count vs seal
    line_count = 0
    with predictions_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                line_count += 1
    expected_lines = int(seal["predictions"]["line_count"])
    if line_count != expected_lines:
        raise InputValidationError(
            f"predictions.jsonl line_count {line_count} != seal {expected_lines}"
        )

    pricing = read_json(root / "results" / "pricing_snapshot.json")
    usage_path = root / "results" / "usage_ledger.jsonl"
    if not usage_path.is_file():
        raise InputValidationError("missing usage ledger")

    report = {
        "schema_version": VALIDATION_SCHEMA,
        "ok": True,
        "validated_at": _utcnow(),
        "workspace": str(root),
        "offline": True,
        "credentials_cleared": cleared,
        "freeze_tag": freeze_tag,
        "experiment_commit": experiment_commit,
        "run_id": run_id,
        "seal_path": _rel(seal_file, workspace=root),
        "seal_sha256": sha256_file(seal_file),
        "predictions": {
            "path": pred_rel,
            "sha256": pred_hash,
            "line_count": line_count,
        },
        "raw_result_index": {
            "path": index_rel,
            "sha256": seal["raw_result_index"]["sha256"],
        },
        "counts": {
            "evaluation_bugs": len(bugs),
            "projects": dict(projects),
            "methods": method_coverage,
            "accepted_jev_gaps": len(accepted_gaps),
        },
        "model_prompt_refs": {
            "jev_prompt_version": "jev-would_detect_regression-v1",
            "gpt_prompt_version": "gpt-would_detect_regression-v1",
            "pricing_snapshot_path": "results/pricing_snapshot.json",
        },
        "notes": [
            "No provider calls; API credentials cleared for offline load",
            "Labels loaded only for analysis; rankings checked free of private fields",
            "Jev absent for accepted A-001 gaps (not invented)",
            "Freeze tag is experiment-v1 (overall.md alias experiment-v1-frozen)",
        ],
    }

    return SealedEvaluationBundle(
        workspace=root,
        seal=seal,
        index=index,
        manifest=manifest,
        freeze_lock=freeze_lock,
        pricing_snapshot=pricing,
        experiment_commit=experiment_commit,
        run_id=run_id,
        freeze_tag=freeze_tag,
        predictions_path=predictions_path,
        predictions_sha256=pred_hash,
        usage_ledger_path=usage_path,
        bugs=bugs,
        validation_report=report,
    )


def write_validation_report(
    bundle: SealedEvaluationBundle,
    *,
    path: Path | None = None,
) -> Path:
    out = path or (bundle.workspace / "results" / "phase8" / "input_validation.json")
    atomic_write_json(out, bundle.validation_report)
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help="Workspace root (default: /workspace)",
    )
    parser.add_argument(
        "--write",
        type=Path,
        default=None,
        help="Write validation JSON report (default: results/phase8/input_validation.json)",
    )
    parser.add_argument(
        "--keep-credentials",
        action="store_true",
        help="Do not clear provider API env vars (still makes no network calls)",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        bundle = load_and_verify_sealed_inputs(
            workspace=args.workspace,
            clear_credentials=not args.keep_credentials,
        )
        out = write_validation_report(bundle, path=args.write)
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        f"OK bugs={len(bundle.bugs)} commit={bundle.experiment_commit[:12]}… "
        f"predictions={bundle.validation_report['predictions']['line_count']} "
        f"report={out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
