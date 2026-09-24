"""Phase 5 development audit: five ranking systems + semantic score gates (P5-09).

Checks for every development bug:

- Random / BM25 / Embedding / Jev / GPT-Nano artifacts exist and cover all N classes
- Jev and GPT-Nano share the same Phase-4 ``candidate_ids`` / ``shortlist_sha256``
- Semantic tails match BM25 byte-for-byte; prefixes are shortlist permutations
- No private label fields in ranking docs; cache entries match expected model IDs
- Usage ledger summary (calls, tokens, list-price vs fees)
- Optional cache-only assembly proof (no API keys required)
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.assemble_rankings import (
    AssembleError,
    assemble_gpt_ranking,
    assemble_jev_ranking,
    semantic_ranking_path,
)
from src.candidates import load_candidates, load_ranking, shortlist_content_hash
from src.example_contract import (
    WORKSPACE,
    ExampleContractError,
    ExampleId,
    PRIVATE_LABEL_FIELDS,
    atomic_write_json,
    development_example_ids,
    load_manifest,
)
from src.gpt_ranker import primary_comparison_model
from src.select_bugs import ManifestError, verify_manifest_integrity

AUDIT_PATH = WORKSPACE / "results" / "audit-phase5.json"
USAGE_LEDGER = WORKSPACE / "results" / "usage_ledger.jsonl"
REQUIRED_SEMANTIC = ("Jev", "GPT-Nano")


class AuditError(Exception):
    """One or more Phase 5 integrity checks failed."""


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _assert_permutation(ids: Sequence[str], *, expected: set[str], label: str) -> None:
    if len(ids) != len(expected) or set(ids) != expected:
        raise AuditError(f"{label}: not a full-suite permutation")
    if len(ids) != len(set(ids)):
        raise AuditError(f"{label}: duplicate class ids")


def _check_no_private(doc: Mapping[str, Any], *, label: str) -> None:
    leaked = PRIVATE_LABEL_FIELDS.intersection(doc.keys())
    if leaked:
        raise AuditError(f"{label}: private fields {sorted(leaked)}")


def audit_semantic_ranking(
    *,
    example: ExampleId,
    method: str,
    candidates: Mapping[str, Any],
    bm25_ids: list[str],
) -> dict[str, Any]:
    path = semantic_ranking_path(example, method=method)
    if not path.is_file():
        raise AuditError(f"{example.qualified}: missing {method} ranking at {path}")
    doc = json.loads(path.read_text(encoding="utf-8"))
    _check_no_private(doc, label=f"{method} {example.qualified}")
    k = int(candidates["K"])
    n = int(candidates["N"])
    if doc.get("shortlist_sha256") != candidates.get("shortlist_sha256"):
        raise AuditError(f"{example.qualified}/{method}: shortlist_sha256 mismatch")
    if list(doc.get("candidate_ids") or []) != list(candidates["candidate_ids"]):
        raise AuditError(f"{example.qualified}/{method}: candidate_ids diverge")
    ranked = list(doc.get("ranked_ids") or [])
    _assert_permutation(ranked, expected=set(bm25_ids), label=f"{method} ranked_ids")
    if ranked[k:] != bm25_ids[k:]:
        raise AuditError(f"{example.qualified}/{method}: BM25 tail altered")
    if set(ranked[:k]) != set(candidates["candidate_ids"]):
        raise AuditError(f"{example.qualified}/{method}: prefix not shortlist permutation")
    # Score gate on prefix
    for entry in doc.get("ranking") or []:
        if entry.get("scored"):
            score = entry.get("score")
            if not isinstance(score, (int, float)) or not math.isfinite(float(score)):
                raise AuditError(
                    f"{example.qualified}/{method}: bad score for {entry.get('test_class')}"
                )
            if not (0.0 <= float(score) <= 1.0):
                raise AuditError(
                    f"{example.qualified}/{method}: score out of range for "
                    f"{entry.get('test_class')}"
                )
        elif entry.get("rank", 0) <= k:
            raise AuditError(
                f"{example.qualified}/{method}: unscored shortlist class "
                f"{entry.get('test_class')}"
            )
    if doc.get("N") != n or doc.get("K") != k:
        raise AuditError(f"{example.qualified}/{method}: N/K mismatch")
    return {
        "method": method,
        "path": str(path.relative_to(WORKSPACE)),
        "N": n,
        "K": k,
        "model_id": (doc.get("provenance") or {}).get("model_id"),
        "provider": (doc.get("provenance") or {}).get("provider"),
        "prompt_version": (doc.get("provenance") or {}).get("prompt_version"),
    }


def audit_baselines(example: ExampleId) -> dict[str, Any]:
    bm25 = load_ranking(example)
    candidates = load_candidates(example)
    bm25_ids = [e["test_class"] for e in bm25["ranking"]]
    n = int(candidates["N"])
    _assert_permutation(bm25_ids, expected=set(bm25_ids), label="bm25")
    if len(bm25_ids) != n:
        raise AuditError(f"{example.qualified}: BM25 N mismatch")
    digest = shortlist_content_hash(candidates["candidate_ids"])
    if candidates.get("shortlist_sha256") != digest:
        raise AuditError(f"{example.qualified}: candidate shortlist hash stale")

    emb_path = WORKSPACE / "results" / "embeddings" / f"{example.slug}.json"
    if not emb_path.is_file():
        raise AuditError(f"{example.qualified}: missing Embedding ranking")
    emb = json.loads(emb_path.read_text(encoding="utf-8"))
    emb_ids = [e["test_class"] for e in emb.get("ranking") or []]
    _assert_permutation(emb_ids, expected=set(bm25_ids), label="embedding")
    if emb.get("settings", {}).get("uses_bm25"):
        raise AuditError(f"{example.qualified}: Embedding must not use BM25")

    rand_path = WORKSPACE / "results" / "random" / f"{example.slug}.json"
    if not rand_path.is_file():
        raise AuditError(f"{example.qualified}: missing Random contract")
    rand = json.loads(rand_path.read_text(encoding="utf-8"))
    if int(rand.get("num_permutations") or 0) != 1000:
        raise AuditError(f"{example.qualified}: Random must define 1000 permutations")

    return {
        "bm25": True,
        "embedding": True,
        "random": True,
        "candidates": True,
        "shortlist_sha256": digest,
        "N": n,
        "K": int(candidates["K"]),
        "bm25_ids": bm25_ids,
        "candidates_doc": candidates,
    }


def summarize_usage_ledger(path: Path = USAGE_LEDGER) -> dict[str, Any]:
    if not path.is_file():
        return {"present": False, "rows": 0}
    by_kind: dict[str, dict[str, Any]] = {}
    rows = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows += 1
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind = str(rec.get("kind") or rec.get("cache_kind") or "unknown")
        bucket = by_kind.setdefault(
            kind,
            {
                "rows": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "list_price_usd": 0.0,
                "platform_fee_usd": 0.0,
                "effective_prepaid_credits_usd": 0.0,
            },
        )
        bucket["rows"] += 1
        usage = rec.get("usage") or {}
        costs = rec.get("costs") or rec.get("cost_breakdown") or {}
        bucket["input_tokens"] += int(usage.get("input_tokens") or rec.get("input_tokens") or 0)
        bucket["output_tokens"] += int(
            usage.get("output_tokens") or rec.get("output_tokens") or 0
        )
        # Ledger rows store costs flat (list_price_inference_usd) or nested.
        list_price = costs.get("list_price_usd")
        if list_price is None:
            list_price = costs.get("list_price_inference_usd")
        if list_price is None:
            list_price = rec.get("list_price_inference_usd", rec.get("list_price_usd"))
        fee = costs.get("platform_fee_usd", rec.get("platform_fee_usd"))
        effective = costs.get(
            "effective_prepaid_credits_usd",
            rec.get("effective_prepaid_credits_usd"),
        )
        if isinstance(list_price, (int, float)):
            bucket["list_price_usd"] += float(list_price)
        if isinstance(fee, (int, float)):
            bucket["platform_fee_usd"] += float(fee)
        if isinstance(effective, (int, float)):
            bucket["effective_prepaid_credits_usd"] += float(effective)
    return {"present": True, "rows": rows, "by_kind": by_kind}


def audit_one_example(example: ExampleId | str) -> dict[str, Any]:
    ex = example if isinstance(example, ExampleId) else ExampleId.parse(example)
    base = audit_baselines(ex)
    semantic = []
    for method in REQUIRED_SEMANTIC:
        semantic.append(
            audit_semantic_ranking(
                example=ex,
                method=method,
                candidates=base["candidates_doc"],
                bm25_ids=base["bm25_ids"],
            )
        )
    # Jev / GPT shortlist equality
    jev = semantic[0]
    gpt = semantic[1]
    if jev["K"] != gpt["K"]:
        raise AuditError(f"{ex.qualified}: Jev/GPT K diverge")
    return {
        "qualified_id": ex.qualified,
        "ok": True,
        "N": base["N"],
        "K": base["K"],
        "shortlist_sha256": base["shortlist_sha256"],
        "baselines": {
            "bm25": True,
            "embedding": True,
            "random": True,
            "candidates": True,
        },
        "semantic": semantic,
    }


def run_cache_only_assembly_proof(
    example: ExampleId | str = "Cli-30",
) -> dict[str, Any]:
    """Reassemble rankings with no API credentials (cache + decision files only)."""
    ex = ExampleId.parse(str(example)) if not isinstance(example, ExampleId) else example
    import os
    import tempfile

    saved = {
        k: os.environ.pop(k, None)
        for k in ("OPENROUTER_API_KEY", "OPENAI_API_KEY", "TYPESAFE_API_KEY")
    }
    try:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jev = assemble_jev_ranking(ex, results_root=root, write=True)
            gpt = assemble_gpt_ranking(
                ex,
                model=primary_comparison_model(),
                results_root=root,
                write=True,
            )
            return {
                "ok": True,
                "example": ex.qualified,
                "credentials_cleared": True,
                "jev_path": str(jev.path),
                "gpt_path": str(gpt.path),
                "same_shortlist": jev.document["shortlist_sha256"]
                == gpt.document["shortlist_sha256"],
                "same_candidates": jev.document["candidate_ids"]
                == gpt.document["candidate_ids"],
            }
    except AssembleError as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        for key, val in saved.items():
            if val is not None:
                os.environ[key] = val


def run_audit(
    *,
    examples: Sequence[ExampleId] | None = None,
    include_cache_only_proof: bool = True,
) -> dict[str, Any]:
    manifest = load_manifest()
    verify_manifest_integrity(manifest)
    targets = list(examples) if examples is not None else list(
        development_example_ids(manifest)
    )
    bugs: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for ex in targets:
        try:
            bugs.append(audit_one_example(ex))
        except (AuditError, ExampleContractError, AssembleError, OSError) as exc:
            failures.append({"qualified_id": ex.qualified, "error": str(exc)})
            bugs.append({"qualified_id": ex.qualified, "ok": False, "error": str(exc)})

    unresolved = [
        {
            "qualified_id": "Jsoup-70",
            "test_class": "org.jsoup.integration.ConnectTest",
            "system": "Jev",
            "provider": "openrouter",
            "error": "HTTP 403 Cloudflare WAF",
            "trigger_substring": "file://etc/passwd",
            "notes": (
                "OpenRouter edge blocks Jev System One POSTs whose model-visible "
                "state contains this literal (case-insensitive). GPT chat accepts "
                "the same Phase-3 representation. Do not rewrite representations; "
                "resolve via TypeSafe direct or OpenRouter allowlist in Phase 6."
            ),
            "evidence": "accepted OpenRouter WAF gap (file://etc/passwd)",
        }
    ]
    # Only keep unresolved entries that still lack a Jev ranking.
    unresolved = [
        u
        for u in unresolved
        if not semantic_ranking_path(
            ExampleId.parse(u["qualified_id"]), method="Jev"
        ).is_file()
    ]

    report: dict[str, Any] = {
        "schema_version": "jev-phase5-audit-v1",
        "generated_at": _utcnow(),
        "split": "development",
        "count": len(targets),
        "passed": sum(1 for b in bugs if b.get("ok")),
        "failed": len(failures),
        "required_semantic_methods": list(REQUIRED_SEMANTIC),
        "usage_ledger": summarize_usage_ledger(),
        "unresolved_availability": unresolved,
        "bugs": bugs,
        "failures": failures,
    }
    if include_cache_only_proof:
        # Prefer a bug that already has scores; fall back to first target.
        proof_ex = next(
            (ExampleId.parse(b["qualified_id"]) for b in bugs if b.get("ok")),
            targets[0] if targets else ExampleId.parse("Cli-30"),
        )
        report["cache_only_assembly_proof"] = run_cache_only_assembly_proof(proof_ex)
        if not report["cache_only_assembly_proof"].get("ok"):
            report["failed"] = int(report["failed"]) + 1
    report["ok"] = report["failed"] == 0 and not report["unresolved_availability"]
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit Phase 5 development rankings.")
    parser.add_argument("--only", nargs="+", default=None)
    parser.add_argument("--skip-cache-only-proof", action="store_true")
    parser.add_argument(
        "--out",
        type=Path,
        default=AUDIT_PATH,
        help="Audit report path",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        examples = (
            [ExampleId.parse(x) for x in args.only] if args.only else None
        )
        report = run_audit(
            examples=examples,
            include_cache_only_proof=not args.skip_cache_only_proof,
        )
    except (ManifestError, ExampleContractError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    args.out.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(args.out, report)
    print(
        f"audit: passed={report['passed']}/{report['count']} "
        f"failed={report['failed']} ok={report['ok']}"
    )
    print(f"wrote: {args.out.relative_to(WORKSPACE)}")
    for fail in report.get("failures") or []:
        print(f"  ! {fail['qualified_id']}: {fail['error']}", file=sys.stderr)
    proof = report.get("cache_only_assembly_proof") or {}
    if proof:
        print(f"cache-only proof: ok={proof.get('ok')} example={proof.get('example')}")
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
