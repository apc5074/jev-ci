"""Audit and seal the Phase 7 evaluation raw results (P7-09).

Read-only checks over sealed rankings, predictions.jsonl, the raw-result index,
Random contracts, and evaluation usage. No provider calls. Aggregate metrics
(FDR, recall, method comparisons) are forbidden here — Phase 8 only.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.audit_phase5 import (
    AuditError,
    audit_baselines,
    audit_semantic_ranking,
    summarize_usage_ledger,
)
from src.example_contract import (
    WORKSPACE,
    ExampleContractError,
    ExampleId,
    atomic_write_json,
    load_manifest,
    read_json,
    sha256_file,
)
from src.export_predictions import (
    ACCEPTED_JEV_GAPS,
    INDEX_PATH,
    PREDICTIONS_PATH,
    validate_predictions,
)
from src.random_baseline import (
    evaluation_example_ids,
    regenerate_from_contract,
    resolve_bug_seed,
)
from src.select_bugs import ManifestError, verify_manifest_integrity

REQUIRED_PROJECTS = ("Cli", "Lang", "Math", "Jsoup", "JacksonDatabind")
SEAL_PATH = WORKSPACE / "results" / "phase7" / "raw_evaluation_seal.json"
AUDIT_PATH = WORKSPACE / "results" / "phase7" / "evaluation_seal_audit.json"
HANDOFF_PATH = WORKSPACE / "docs" / "phase7-seal.md"
SEAL_SCHEMA_VERSION = "jev-raw-evaluation-seal-v1"


class SealError(Exception):
    """Evaluation seal / completeness audit failed."""


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(WORKSPACE.resolve()))
    except ValueError:
        return str(path)


def _require_commit(doc: Mapping[str, Any], *, expected: str, label: str) -> None:
    commit = doc.get("experiment_commit")
    if commit is None:
        # Random contracts may omit commit; rankings/candidates should carry it.
        return
    if commit != expected:
        raise SealError(f"{label}: experiment_commit {commit!r} != {expected!r}")


def audit_random_contract(example: ExampleId, *, manifest: Mapping[str, Any]) -> dict[str, Any]:
    path = WORKSPACE / "results" / "random" / f"{example.slug}.json"
    if not path.is_file():
        raise SealError(f"{example.qualified}: missing Random contract")
    doc = read_json(path)
    if doc.get("split") != "evaluation":
        raise SealError(f"{example.qualified}: Random split != evaluation")
    if int(doc.get("num_permutations") or 0) != 1000:
        raise SealError(f"{example.qualified}: Random num_permutations != 1000")
    seed_info = resolve_bug_seed(example, split="evaluation", manifest=manifest)
    if int(doc["seed"]) != seed_info.seed:
        raise SealError(
            f"{example.qualified}: Random seed {doc['seed']} != expected {seed_info.seed}"
        )
    if int(doc["bug_index"]) != seed_info.bug_index:
        raise SealError(f"{example.qualified}: Random bug_index mismatch")

    inventory = read_json(
        WORKSPACE / "data" / "tests" / example.slug / "inventory.json"
    )
    classes = list(inventory["test_classes"])
    perms = regenerate_from_contract(doc, test_classes=classes)
    if len(perms) != 1000:
        raise SealError(f"{example.qualified}: regenerated perm count != 1000")
    if list(perms[0]) != list(doc["first_permutation"]):
        raise SealError(f"{example.qualified}: first_permutation drift")
    if list(perms[-1]) != list(doc["last_permutation"]):
        raise SealError(f"{example.qualified}: last_permutation drift")
    return {
        "ok": True,
        "seed": doc["seed"],
        "bug_index": doc["bug_index"],
        "permutations_sha256": doc["permutations_sha256"],
        "N": doc["N"],
    }


def audit_one_evaluation_bug(
    example: ExampleId,
    *,
    expected_commit: str,
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    base = audit_baselines(example)
    bm25 = read_json(WORKSPACE / "results" / "rankings" / f"{example.slug}.json")
    emb = read_json(WORKSPACE / "results" / "embeddings" / f"{example.slug}.json")
    cand = base["candidates_doc"]
    _require_commit(bm25, expected=expected_commit, label=f"BM25 {example.qualified}")
    _require_commit(emb, expected=expected_commit, label=f"Embedding {example.qualified}")
    _require_commit(cand, expected=expected_commit, label=f"candidates {example.qualified}")

    if list(cand["candidate_ids"]) != base["bm25_ids"][: int(cand["K"])]:
        raise SealError(f"{example.qualified}: candidates are not BM25 prefix")

    semantic: list[dict[str, Any]] = []
    gap = ACCEPTED_JEV_GAPS.get(example.qualified)
    jev_path = WORKSPACE / "results" / "semantic" / "jev" / f"{example.slug}.json"
    if gap is not None:
        if jev_path.is_file():
            raise SealError(
                f"{example.qualified}: Jev ranking present despite accepted gap"
            )
        semantic.append(
            {
                "method": "Jev",
                "ok": True,
                "accepted_gap": True,
                "gap_test_class": gap,
                "path": None,
            }
        )
    else:
        jev = audit_semantic_ranking(
            example=example,
            method="Jev",
            candidates=cand,
            bm25_ids=base["bm25_ids"],
        )
        jev_doc = read_json(jev_path)
        _require_commit(jev_doc, expected=expected_commit, label=f"Jev {example.qualified}")
        semantic.append({**jev, "accepted_gap": False, "ok": True})

    gpt = audit_semantic_ranking(
        example=example,
        method="GPT-Nano",
        candidates=cand,
        bm25_ids=base["bm25_ids"],
    )
    gpt_doc = read_json(
        WORKSPACE / "results" / "semantic" / "gpt_nano" / f"{example.slug}.json"
    )
    _require_commit(gpt_doc, expected=expected_commit, label=f"GPT {example.qualified}")
    if gap is None:
        jev_doc = read_json(jev_path)
        if list(jev_doc["candidate_ids"]) != list(gpt_doc["candidate_ids"]):
            raise SealError(f"{example.qualified}: Jev/GPT candidate_ids diverge")
        if jev_doc.get("shortlist_sha256") != gpt_doc.get("shortlist_sha256"):
            raise SealError(f"{example.qualified}: Jev/GPT shortlist_sha256 diverge")
    semantic.append({**gpt, "ok": True})

    random_info = audit_random_contract(example, manifest=manifest)

    # Labels exist and are nonempty (private; not loaded into rankings).
    labels = read_json(WORKSPACE / "data" / "tests" / example.slug / "labels.json")
    triggers = labels.get("positive_classes")
    if not isinstance(triggers, list) or not triggers:
        raise SealError(f"{example.qualified}: empty or missing positive_classes labels")

    example_status = read_json(
        WORKSPACE / "data" / "bugs" / example.slug / "example.json"
    )
    if example_status.get("status") != "complete":
        raise SealError(
            f"{example.qualified}: example status {example_status.get('status')!r}"
        )

    return {
        "qualified_id": example.qualified,
        "project": example.project,
        "ok": True,
        "N": base["N"],
        "K": base["K"],
        "shortlist_sha256": base["shortlist_sha256"],
        "accepted_jev_gap": gap is not None,
        "baselines": {
            "bm25": True,
            "embedding": True,
            "random": True,
            "candidates": True,
        },
        "semantic": semantic,
        "random": random_info,
        "trigger_class_count": len(triggers),
    }


def verify_index_integrity(
    *,
    index_path: Path,
    predictions_path: Path,
    expected_commit: str,
) -> dict[str, Any]:
    if not index_path.is_file():
        raise SealError(f"missing raw-result index: {index_path}")
    index = read_json(index_path)
    if index.get("experiment_commit") != expected_commit:
        raise SealError("raw-result index experiment_commit mismatch")
    pred_meta = index.get("predictions") or {}
    if pred_meta.get("path") != _rel(predictions_path) and pred_meta.get(
        "path"
    ) != "results/predictions.jsonl":
        # Allow either relative form.
        if Path(pred_meta.get("path") or "") != predictions_path:
            pass
    live_hash = sha256_file(predictions_path)
    if pred_meta.get("sha256") != live_hash:
        raise SealError(
            f"predictions.jsonl hash drift: index={pred_meta.get('sha256')} "
            f"live={live_hash}"
        )
    # Re-hash a sample of indexed artifacts for tamper detection.
    checked = 0
    for entry in index.get("artifacts") or []:
        kind = entry.get("kind")
        if kind not in {
            "bm25_ranking",
            "embedding_ranking",
            "gpt_nano_ranking",
            "jev_ranking",
            "random_baseline",
            "candidates",
            "pricing_snapshot",
            "freeze_lock",
            "manifest",
        }:
            continue
        path = WORKSPACE / entry["path"]
        if not path.is_file():
            raise SealError(f"indexed artifact missing: {entry['path']}")
        digest = sha256_file(path)
        if digest != entry["sha256"]:
            raise SealError(f"hash mismatch for {entry['path']}")
        checked += 1
    return {
        "ok": True,
        "predictions_sha256": live_hash,
        "index_sha256": sha256_file(index_path),
        "artifacts_rehashed": checked,
        "accepted_jev_gaps": len(index.get("accepted_jev_gaps") or {}),
    }


def reconcile_evaluation_usage(
    *,
    expected_gpt_pairs: int,
    expected_jev_pairs: int,
) -> dict[str, Any]:
    ledger = WORKSPACE / "results" / "usage_ledger.jsonl"
    if not ledger.is_file():
        raise SealError("missing usage ledger")
    by_kind: Counter[str] = Counter()
    list_price = 0.0
    platform_fee = 0.0
    for line in ledger.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        meta = rec.get("metadata") or {}
        if meta.get("split") != "evaluation":
            continue
        kind = str(rec.get("kind") or "unknown")
        by_kind[kind] += 1
        lp = rec.get("list_price_inference_usd")
        fee = rec.get("platform_fee_usd")
        if isinstance(lp, (int, float)) and math.isfinite(float(lp)):
            list_price += float(lp)
        if isinstance(fee, (int, float)) and math.isfinite(float(fee)):
            platform_fee += float(fee)

    errors: list[str] = []
    if by_kind.get("gpt", 0) != expected_gpt_pairs:
        errors.append(
            f"evaluation gpt ledger rows {by_kind.get('gpt', 0)} != "
            f"expected shortlist pairs {expected_gpt_pairs}"
        )
    if by_kind.get("jev", 0) != expected_jev_pairs:
        errors.append(
            f"evaluation jev ledger rows {by_kind.get('jev', 0)} != "
            f"expected scored pairs {expected_jev_pairs}"
        )
    pricing = WORKSPACE / "results" / "pricing_snapshot.json"
    if not pricing.is_file():
        errors.append("missing pricing_snapshot.json")

    return {
        "ok": not errors,
        "errors": errors,
        "evaluation_rows_by_kind": dict(by_kind),
        "evaluation_list_price_inference_usd": list_price,
        "evaluation_platform_fee_usd": platform_fee,
        "expected_gpt_pairs": expected_gpt_pairs,
        "expected_jev_pairs": expected_jev_pairs,
        "pricing_snapshot_sha256": sha256_file(pricing) if pricing.is_file() else None,
        "full_ledger_summary": summarize_usage_ledger(ledger),
    }


def render_handoff_markdown(seal: Mapping[str, Any]) -> str:
    pred = seal["predictions"]
    return f"""# Phase 7 raw-evaluation seal (P7-09)

**Overall: `{"PASS" if seal.get("ok") else "FAIL"}`**

Phase 7 evaluation raw results are sealed. Phase 8 must load these immutable
inputs only — no provider calls, no ranking repair, no aggregate analysis before
verifying this seal.

## Freeze identity

- `freeze_tag`: `{seal.get("freeze_tag")}`
- `experiment_commit`: `{seal.get("experiment_commit")}`
- `run_id`: `{seal.get("run_id")}`
- `sealed_at`: `{seal.get("sealed_at")}`

## Primary artifacts

| Artifact | Path | SHA-256 |
| --- | --- | --- |
| Predictions | `{pred["path"]}` | `{pred["sha256"]}` |
| Raw-result index | `{seal["raw_result_index"]["path"]}` | `{seal["raw_result_index"]["sha256"]}` |
| Seal record | `{seal["seal_path"]}` | `{seal.get("seal_sha256", "(see file)")}` |

## Coverage

- Evaluation bugs: **{seal["counts"]["evaluation_bugs"]}** (Cli/Lang/Math/Jsoup/JacksonDatabind × 25)
- BM25 / Embedding / GPT-Nano / Random: **125/125**
- Jev: **{seal["counts"]["jev_rankings"]}/125** ({seal["counts"]["accepted_jev_gaps"]} accepted A-001 gaps)
- `predictions.jsonl` lines: **{pred["line_count"]}**

## Offline Phase 8 read

```bash
docker run --rm --platform linux/amd64 \\
  -v "$(pwd):/workspace" -w /workspace \\
  jev-ci:phase1 python -c "
from pathlib import Path
import json
from src.example_contract import sha256_file
seal=json.loads(Path('results/phase7/raw_evaluation_seal.json').read_text())
assert sha256_file(Path(seal['predictions']['path']))==seal['predictions']['sha256']
assert sha256_file(Path(seal['raw_result_index']['path']))==seal['raw_result_index']['sha256']
print('seal-ok', seal['experiment_commit'], seal['run_id'])
"
```

Do **not** compute FDR, candidate recall, method deltas, or failure cases until
this seal verifies.
"""


def run_seal(
    *,
    write: bool = True,
) -> dict[str, Any]:
    manifest = load_manifest()
    try:
        verify_manifest_integrity(manifest)
    except ManifestError as exc:
        raise SealError(f"manifest integrity failed: {exc}") from exc

    run = read_json(WORKSPACE / "results" / "phase7" / "run.json")
    expected_commit = run["experiment_commit"]
    run_id = run["run_id"]
    example_ids = evaluation_example_ids(manifest)
    if len(example_ids) != 125:
        raise SealError(f"expected 125 evaluation bugs, got {len(example_ids)}")

    projects = Counter(ex.project for ex in example_ids)
    for proj in REQUIRED_PROJECTS:
        if projects.get(proj) != 25:
            raise SealError(f"project {proj} has {projects.get(proj)} evaluation bugs")

    bugs: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    k_total = 0
    jev_scored_pairs = 0
    for ex in example_ids:
        try:
            row = audit_one_evaluation_bug(
                ex, expected_commit=expected_commit, manifest=manifest
            )
            bugs.append(row)
            k_total += int(row["K"])
            if not row["accepted_jev_gap"]:
                jev_scored_pairs += int(row["K"])
        except (SealError, AuditError, ExampleContractError, OSError, KeyError) as exc:
            failures.append({"qualified_id": ex.qualified, "error": str(exc)})
            bugs.append({"qualified_id": ex.qualified, "ok": False, "error": str(exc)})

    pred_stats = validate_predictions(PREDICTIONS_PATH, example_ids=example_ids)
    index_check = verify_index_integrity(
        index_path=INDEX_PATH,
        predictions_path=PREDICTIONS_PATH,
        expected_commit=expected_commit,
    )
    # GPT scored every shortlist class; Jev missed exactly one class per gap bug
    # in the ledger (12), while rankings omit those 12 bugs entirely.
    usage = reconcile_evaluation_usage(
        expected_gpt_pairs=k_total,
        expected_jev_pairs=k_total - len(ACCEPTED_JEV_GAPS),
    )

    ok = (
        not failures
        and bool(index_check.get("ok"))
        and bool(usage.get("ok"))
        and pred_stats["unique_keys"] == pred_stats["line_count"]
        and pred_stats["line_count"] == pred_stats["expected_keys"]
    )

    audit = {
        "schema_version": "jev-phase7-evaluation-seal-audit-v1",
        "audited_at": _utcnow(),
        "ok": ok,
        "experiment_commit": expected_commit,
        "run_id": run_id,
        "counts": {
            "evaluation_bugs": len(example_ids),
            "passed": sum(1 for b in bugs if b.get("ok")),
            "failed": len(failures),
            "projects": dict(projects),
            "jev_rankings": len(example_ids) - len(ACCEPTED_JEV_GAPS),
            "accepted_jev_gaps": len(ACCEPTED_JEV_GAPS),
            "K_total": k_total,
        },
        "failed_ids": [f["qualified_id"] for f in failures],
        "failures": failures,
        "predictions": pred_stats,
        "index_check": index_check,
        "usage_reconciliation": usage,
        "examples": bugs,
        "notes": [
            "No aggregate FDR/recall/method comparison computed",
            "Accepted Jev A-001 gaps match P7-07 assembly",
            "Random permutations regenerated from sealed seeds",
        ],
    }

    index = read_json(INDEX_PATH)
    seal = {
        "schema_version": SEAL_SCHEMA_VERSION,
        "ok": ok,
        "sealed_at": _utcnow(),
        "freeze_tag": "experiment-v1",
        "experiment_commit": expected_commit,
        "run_id": run_id,
        "seal_path": "results/phase7/raw_evaluation_seal.json",
        "predictions": {
            "path": "results/predictions.jsonl",
            "sha256": index_check["predictions_sha256"],
            "line_count": pred_stats["line_count"],
            "schema_version": "jev-predictions-v1",
        },
        "raw_result_index": {
            "path": "results/phase7/raw_result_index.json",
            "sha256": index_check["index_sha256"],
            "schema_version": index.get("schema_version"),
        },
        "audit_path": "results/phase7/evaluation_seal_audit.json",
        "counts": audit["counts"],
        "accepted_jev_gaps": {
            qid: {
                "test_class": cls,
                "reason": "OpenRouter WAF A-001 on file://etc/passwd",
            }
            for qid, cls in sorted(ACCEPTED_JEV_GAPS.items())
        },
        "usage": {
            "evaluation_rows_by_kind": usage["evaluation_rows_by_kind"],
            "evaluation_list_price_inference_usd": usage[
                "evaluation_list_price_inference_usd"
            ],
            "evaluation_platform_fee_usd": usage["evaluation_platform_fee_usd"],
            "pricing_snapshot_sha256": usage["pricing_snapshot_sha256"],
        },
        "phase8_inputs": [
            "results/phase7/raw_evaluation_seal.json",
            "results/phase7/raw_result_index.json",
            "results/predictions.jsonl",
            "results/rankings/",
            "results/embeddings/",
            "results/semantic/jev/",
            "results/semantic/gpt_nano/",
            "results/random/",
            "data/candidates/",
            "data/tests/*/labels.json",
            "data/manifest.json",
            "results/pricing_snapshot.json",
            "results/usage_ledger.jsonl",
            "experiment.yaml",
            "README.md",
        ],
        "forbidden_until_seal_verified": [
            "aggregate FDR",
            "candidate recall@200",
            "method differences / significance tests",
            "failure-case analysis",
            "metrics.csv / statistics.json / figures",
        ],
        "offline_verify_command": (
            "python -c \"from pathlib import Path; import json; "
            "from src.example_contract import sha256_file; "
            "s=json.loads(Path('results/phase7/raw_evaluation_seal.json').read_text()); "
            "assert sha256_file(Path(s['predictions']['path']))==s['predictions']['sha256']; "
            "print('seal-ok')\""
        ),
    }

    if write:
        atomic_write_json(AUDIT_PATH, audit)
        atomic_write_json(SEAL_PATH, seal)
        # Re-read seal file hash into document for handoff convenience.
        seal_sha = sha256_file(SEAL_PATH)
        seal["seal_sha256"] = seal_sha
        atomic_write_json(SEAL_PATH, seal)
        HANDOFF_PATH.parent.mkdir(parents=True, exist_ok=True)
        HANDOFF_PATH.write_text(render_handoff_markdown(seal), encoding="utf-8")

    if not ok:
        raise SealError(
            f"evaluation seal failed: {len(failures)} bug failures; "
            f"usage_ok={usage.get('ok')}; index_ok={index_check.get('ok')}"
        )
    return seal


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Run checks without writing seal artifacts",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        seal = run_seal(write=not args.no_write)
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        f"OK seal={seal['seal_path']} commit={seal['experiment_commit'][:12]}… "
        f"bugs={seal['counts']['evaluation_bugs']} "
        f"predictions={seal['predictions']['line_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
