"""Phase 6 / P6-01: dated development baseline + diagnostic review table.

Aggregates Phases 3–5 artifacts for the 25 development bugs. Diagnostics only —
not headline evaluation metrics. Preserves the initial Jev prompt version
(``jev-would_detect_regression-v1``) as the pre-revision baseline.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.assemble_rankings import semantic_ranking_path, verify_five_systems_present
from src.audit_phase4 import audit_one_example as audit_phase4_one
from src.audit_phase5 import audit_one_example as audit_phase5_one, summarize_usage_ledger
from src.candidates import load_candidates, load_ranking
from src.example_contract import (
    WORKSPACE,
    ExampleContractError,
    ExampleId,
    atomic_write_json,
    development_example_ids,
    example_paths,
    load_manifest,
    read_json,
    validate_example_artifacts,
)
from src.semantic_cache import GPT_PROMPT_VERSION, JEV_PROMPT_VERSION
from src.select_bugs import ManifestError, verify_manifest_integrity

BASELINE_DIR = WORKSPACE / "results" / "phase6"
BASELINE_JSON = BASELINE_DIR / "development_baseline.json"
BASELINE_MD = WORKSPACE / "docs" / "phase6-baseline.md"
ACCEPTED_JEV_GAPS = {
    ("Jsoup-70", "org.jsoup.integration.ConnectTest"): (
        "OpenRouter Cloudflare WAF HTTP 403 on substring file://etc/passwd; "
        "accepted 2026-09-22 to continue Phase 6 (see docs/phase5-handoff.md)."
    ),
}


class BaselineError(Exception):
    """Development baseline could not be established."""


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _git_revision() -> dict[str, Any]:
    def _run(args: list[str]) -> str | None:
        try:
            out = subprocess.check_output(
                args, cwd=str(WORKSPACE), stderr=subprocess.DEVNULL, text=True
            )
            return out.strip() or None
        except (subprocess.CalledProcessError, FileNotFoundError, OSError):
            return None

    return {
        "commit": _run(["git", "rev-parse", "HEAD"]),
        "commit_short": _run(["git", "rev-parse", "--short", "HEAD"]),
        "branch": _run(["git", "rev-parse", "--abbrev-ref", "HEAD"]),
        "dirty": bool(_run(["git", "status", "--porcelain"])),
    }


def _first_trigger_ranks(
    ranked_ids: Sequence[str], positives: Sequence[str]
) -> dict[str, Any]:
    positions = []
    for p in positives:
        if p in ranked_ids:
            positions.append(ranked_ids.index(p) + 1)
    if not positions:
        return {
            "first_trigger_rank": None,
            "trigger_hits": 0,
            "all_triggers_ranked": False,
        }
    return {
        "first_trigger_rank": min(positions),
        "trigger_hits": len(positions),
        "all_triggers_ranked": len(positions) == len(positives),
    }


def _ranking_integrity(path: Path, *, expected_n: int, inventory: set[str]) -> dict[str, Any]:
    if not path.is_file():
        return {"present": False, "ok": False, "error": "missing"}
    doc = read_json(path)
    ids = doc.get("ranked_ids") or [
        e.get("test_class") for e in (doc.get("ranking") or [])
    ]
    ids = [x for x in ids if isinstance(x, str)]
    ok = (
        len(ids) == expected_n
        and len(ids) == len(set(ids))
        and set(ids) == inventory
    )
    return {
        "present": True,
        "ok": ok,
        "N": len(ids),
        "method": doc.get("method"),
        "model_id": (doc.get("provenance") or {}).get("model_id"),
        "provider": (doc.get("provenance") or {}).get("provider"),
        "prompt_version": (doc.get("provenance") or {}).get("prompt_version"),
        "shortlist_sha256": doc.get("shortlist_sha256"),
    }


def review_one_example(example: ExampleId | str) -> dict[str, Any]:
    """One development-only diagnostic row (not evaluation headline metrics)."""
    ex = example if isinstance(example, ExampleId) else ExampleId.parse(example)
    validated = validate_example_artifacts(ex, allow_evaluation=False)
    paths = example_paths(ex)
    inventory = list(validated["inventory"]["test_classes"])
    positives = list(validated["labels"].get("positive_classes") or [])
    patch_meta = read_json(paths["patch_meta"])
    example_doc = read_json(paths["example_json"])
    direction = example_doc.get("direction") or {}
    candidates = load_candidates(ex)
    bm25 = load_ranking(ex)
    bm25_ids = [e["test_class"] for e in bm25["ranking"]]
    n = int(candidates["N"])
    k = int(candidates["K"])

    counts = validated["inventory"].get("counts") or {}
    missing_sources = int(counts.get("source_missing") or bm25.get("source_missing_count") or 0)

    bm25_trig = _first_trigger_ranks(bm25_ids, positives)
    cand_hits = [p for p in positives if p in candidates["candidate_ids"]]

    five = verify_five_systems_present(ex)
    # Treat accepted Jev gap as noted incomplete, not silent ok.
    jev_path = semantic_ranking_path(ex, method="Jev")
    gpt_path = semantic_ranking_path(ex, method="GPT-Nano")
    inv_set = set(inventory)
    jev_info = _ranking_integrity(jev_path, expected_n=n, inventory=inv_set)
    gpt_info = _ranking_integrity(gpt_path, expected_n=n, inventory=inv_set)
    emb_path = WORKSPACE / "results" / "embeddings" / f"{ex.slug}.json"
    emb_info = _ranking_integrity(emb_path, expected_n=n, inventory=inv_set)
    rand_path = WORKSPACE / "results" / "random" / f"{ex.slug}.json"
    rand_ok = rand_path.is_file() and int(
        (read_json(rand_path) if rand_path.is_file() else {}).get("num_permutations")
        or 0
    ) == 1000

    jev_trig = (
        _first_trigger_ranks(read_json(jev_path).get("ranked_ids") or [], positives)
        if jev_info.get("present")
        else {"first_trigger_rank": None, "trigger_hits": 0}
    )
    gpt_trig = (
        _first_trigger_ranks(read_json(gpt_path).get("ranked_ids") or [], positives)
        if gpt_info.get("present")
        else {"first_trigger_rank": None, "trigger_hits": 0}
    )
    emb_trig = (
        _first_trigger_ranks(
            [e["test_class"] for e in (read_json(emb_path).get("ranking") or [])],
            positives,
        )
        if emb_info.get("present")
        else {"first_trigger_rank": None, "trigger_hits": 0}
    )

    accepted_gap = None
    if ex.qualified == "Jsoup-70" and not jev_info.get("ok"):
        accepted_gap = ACCEPTED_JEV_GAPS.get(
            ("Jsoup-70", "org.jsoup.integration.ConnectTest")
        )

    systems_complete = all(
        [
            five.get("BM25"),
            five.get("Embedding"),
            five.get("Random"),
            five.get("GPT-Nano"),
            five.get("Jev") or bool(accepted_gap),
        ]
    )

    # Phase-4 / Phase-5 integrity (labels used only here for diagnostics).
    p4 = audit_phase4_one(ex)
    p5_ok = True
    p5_error = None
    try:
        if five.get("Jev") and five.get("GPT-Nano"):
            audit_phase5_one(ex)
        elif five.get("GPT-Nano") and accepted_gap:
            # GPT-only semantic check via presence; full P5 audit needs Jev.
            p5_ok = gpt_info.get("ok", False)
            p5_error = "jev_gap_accepted"
        else:
            p5_ok = False
            p5_error = "missing_semantic_rankings"
    except Exception as exc:  # noqa: BLE001
        p5_ok = False
        p5_error = str(exc)

    return {
        "qualified_id": ex.qualified,
        "example_id": ex.slug,
        "split": "development",
        "completeness": {
            "example_ok": True,
            "systems": five,
            "systems_complete_with_accepted_gaps": systems_complete,
            "accepted_gap": accepted_gap,
        },
        "patch": {
            "direction": patch_meta.get("direction")
            or f"{direction.get('base')}->{direction.get('proposed')}",
            "base": direction.get("base") or "Bf",
            "proposed": direction.get("proposed") or "Bb",
            "patch_truncated": bool(patch_meta.get("patch_truncated")),
            "representation_chars": patch_meta.get("representation_chars"),
            "representation_char_cap": patch_meta.get("representation_char_cap"),
            "original_patch_chars": patch_meta.get("original_patch_chars"),
        },
        "suite": {
            "N": n,
            "K": k,
            "num_test_classes": len(inventory),
            "num_positive_classes": len(positives),
            "num_trigger_methods": int(
                validated["labels"].get("num_trigger_methods") or 0
            ),
            "source_missing_count": missing_sources,
        },
        "bm25": {
            "candidate_recall": bool(cand_hits),
            "num_triggers_in_top_k": len(cand_hits),
            "first_trigger_rank": bm25_trig["first_trigger_rank"],
            "shortlist_sha256": candidates.get("shortlist_sha256"),
            "integrity_ok": bool(p4.get("ok")),
        },
        "rankings": {
            "random_ok": rand_ok,
            "embedding": {**emb_info, "first_trigger_rank": emb_trig["first_trigger_rank"]},
            "jev": {**jev_info, "first_trigger_rank": jev_trig["first_trigger_rank"]},
            "gpt_nano": {
                **gpt_info,
                "first_trigger_rank": gpt_trig["first_trigger_rank"],
            },
        },
        "prompts": {
            "jev_prompt_version": JEV_PROMPT_VERSION,
            "gpt_prompt_version": GPT_PROMPT_VERSION,
            "jev_revision_count": 0,
            "baseline_prompt_preserved": True,
        },
        "integrity": {
            "phase4_ok": bool(p4.get("ok")),
            "phase5_ok": p5_ok,
            "phase5_note": p5_error,
        },
        "ok": systems_complete and bool(p4.get("ok")) and (p5_ok or bool(accepted_gap)),
    }


def build_development_baseline() -> dict[str, Any]:
    manifest = load_manifest()
    verify_manifest_integrity(manifest)
    targets = list(development_example_ids(manifest))
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for ex in targets:
        try:
            rows.append(review_one_example(ex))
        except (BaselineError, ExampleContractError, ManifestError, OSError) as exc:
            failures.append({"qualified_id": ex.qualified, "error": str(exc)})
            rows.append({"qualified_id": ex.qualified, "ok": False, "error": str(exc)})

    # Provider / model snapshot from saved decisions
    decision_path = WORKSPACE / "results" / "jev_provider_decision.json"
    gpt_registry = WORKSPACE / "results" / "gpt_comparison_models.json"
    pricing = WORKSPACE / "results" / "pricing_snapshot.json"
    jev_decision = read_json(decision_path) if decision_path.is_file() else {}
    gpt_models = read_json(gpt_registry) if gpt_registry.is_file() else {}

    complete = sum(1 for r in rows if r.get("ok"))
    with_gap = sum(
        1
        for r in rows
        if (r.get("completeness") or {}).get("accepted_gap")
    )
    recall = [
        r for r in rows if (r.get("bm25") or {}).get("candidate_recall") is not None
    ]
    report = {
        "schema_version": "jev-phase6-development-baseline-v1",
        "generated_at": _utcnow(),
        "split": "development",
        "purpose": (
            "Development-only pipeline diagnosis. Not the headline evaluation table."
        ),
        "git": _git_revision(),
        "commands": [
            "python scripts/run_baselines.py --split development",
            "python scripts/run_jev.py --split development",
            "python scripts/run_gpt.py --split development --model primary",
            "python -m src.assemble_rankings --only-primary-gpt",
            "python scripts/audit_phase5.py",
            "python scripts/run_development_baseline.py",
        ],
        "frozen_for_baseline": {
            "jev_prompt_version": JEV_PROMPT_VERSION,
            "gpt_prompt_version": GPT_PROMPT_VERSION,
            "jev_provider": jev_decision.get("selected_provider"),
            "jev_model_id": jev_decision.get("selected_model_id"),
            "jev_observed_model_id": jev_decision.get("observed_model_id")
            or (jev_decision.get("selected_route") or {}).get("observed_model_id"),
            "gpt_primary": (gpt_models.get("primary_key") or "gpt-5.4-nano"),
            "pricing_snapshot": (
                str(pricing.relative_to(WORKSPACE)) if pricing.is_file() else None
            ),
            "jev_revision_count": 0,
            "note": (
                "Initial Jev prompt and caches preserved before any P6-03 revision."
            ),
        },
        "accepted_gaps": [
            {
                "qualified_id": "Jsoup-70",
                "test_class": "org.jsoup.integration.ConnectTest",
                "system": "Jev",
                "reason": ACCEPTED_JEV_GAPS[
                    ("Jsoup-70", "org.jsoup.integration.ConnectTest")
                ],
            }
        ],
        "summary": {
            "count": len(targets),
            "ok": complete,
            "failed": len(failures),
            "with_accepted_gap": with_gap,
            "bm25_candidate_recall": (
                sum(1 for r in recall if r["bm25"]["candidate_recall"]) / len(recall)
                if recall
                else None
            ),
            "mean_bm25_first_trigger_rank": (
                sum(r["bm25"]["first_trigger_rank"] for r in recall if r["bm25"]["first_trigger_rank"])
                / sum(1 for r in recall if r["bm25"]["first_trigger_rank"])
                if any(r["bm25"].get("first_trigger_rank") for r in recall)
                else None
            ),
        },
        "usage_ledger": summarize_usage_ledger(),
        "bugs": rows,
        "failures": failures,
        "ok": len(failures) == 0 and complete == len(targets),
    }
    return report


def render_baseline_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Phase 6 development baseline (P6-01)",
        "",
        f"Generated: `{report.get('generated_at')}`",
        "",
        "Development-only diagnostic table. **Not** the headline evaluation results.",
        "",
        "## Traceability",
        "",
        f"- Git: `{((report.get('git') or {}).get('commit_short'))}` "
        f"({(report.get('git') or {}).get('branch')}"
        f"{', dirty' if (report.get('git') or {}).get('dirty') else ''})",
        f"- Jev prompt: `{(report.get('frozen_for_baseline') or {}).get('jev_prompt_version')}` "
        f"(revision count "
        f"`{(report.get('frozen_for_baseline') or {}).get('jev_revision_count')}`)",
        f"- GPT prompt: `{(report.get('frozen_for_baseline') or {}).get('gpt_prompt_version')}`",
        f"- Jev model: `{(report.get('frozen_for_baseline') or {}).get('jev_model_id')}`",
        f"- Machine record: `results/phase6/development_baseline.json`",
        "",
        "## Accepted gaps",
        "",
    ]
    for gap in report.get("accepted_gaps") or []:
        lines.append(
            f"- **{gap['qualified_id']}** / `{gap['test_class']}` ({gap['system']}): "
            f"{gap['reason']}"
        )
    lines.extend(
        [
            "",
            "## Summary",
            "",
            f"- Bugs ok: **{report['summary']['ok']}/{report['summary']['count']}** "
            f"(accepted gaps: {report['summary']['with_accepted_gap']})",
            f"- BM25 candidate recall@K: "
            f"**{(report['summary'].get('bm25_candidate_recall') or 0):.0%}**",
            f"- Mean BM25 first-trigger rank: "
            f"{report['summary'].get('mean_bm25_first_trigger_rank')}",
            "",
            "## Review table",
            "",
            "| Bug | N | K | Patch trunc | BM25 FT | Emb FT | Jev FT | GPT FT | "
            "Cand recall | Systems |",
            "| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | --- | --- |",
        ]
    )
    for row in report.get("bugs") or []:
        if not row.get("ok") and "error" in row and "suite" not in row:
            lines.append(
                f"| {row['qualified_id']} | — | — | — | — | — | — | — | — | "
                f"ERROR |"
            )
            continue
        patch = row.get("patch") or {}
        suite = row.get("suite") or {}
        bm25 = row.get("bm25") or {}
        ranks = row.get("rankings") or {}
        five = (row.get("completeness") or {}).get("systems") or {}
        sys_bits = "".join(
            ("Y" if five.get(k) else ("G" if k == "Jev" and (row.get("completeness") or {}).get("accepted_gap") else "N"))
            for k in ("Random", "BM25", "Embedding", "Jev", "GPT-Nano")
        )
        def _ft(block: Mapping[str, Any] | None) -> str:
            if not block:
                return "—"
            v = block.get("first_trigger_rank")
            return str(v) if v is not None else "—"

        trunc = "Y" if patch.get("patch_truncated") else "N"
        recall = "Y" if bm25.get("candidate_recall") else "N"
        lines.append(
            f"| {row.get('qualified_id')} | {suite.get('N')} | {suite.get('K')} | "
            f"{trunc} | {bm25.get('first_trigger_rank') or '—'} | "
            f"{_ft(ranks.get('embedding'))} | {_ft(ranks.get('jev'))} | "
            f"{_ft(ranks.get('gpt_nano'))} | {recall} | `{sys_bits}` |"
        )
    lines.extend(
        [
            "",
            "Systems column order: Random, BM25, Embedding, Jev, GPT-Nano "
            "(`Y` present, `N` missing, `G` accepted gap).",
            "",
            "FT = first-trigger rank (1-based). Lower is better for diagnosis only.",
            "",
        ]
    )
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build Phase 6 development baseline review (P6-01)."
    )
    parser.add_argument(
        "--out-json",
        type=Path,
        default=BASELINE_JSON,
    )
    parser.add_argument(
        "--out-md",
        type=Path,
        default=BASELINE_MD,
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        report = build_development_baseline()
    except (ManifestError, ExampleContractError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(args.out_json, report)
    md = render_baseline_markdown(report)
    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    args.out_md.write_text(md, encoding="utf-8")
    print(
        f"baseline: ok={report['summary']['ok']}/{report['summary']['count']} "
        f"accepted_gaps={report['summary']['with_accepted_gap']} "
        f"overall_ok={report['ok']}"
    )
    print(f"wrote: {args.out_json.relative_to(WORKSPACE)}")
    print(f"wrote: {args.out_md.relative_to(WORKSPACE)}")
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
