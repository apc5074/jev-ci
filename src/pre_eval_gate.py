"""Pre-evaluation integrity gate (Phase 6 / P6-06).

Validates development artifacts and preregistration agreement **before** any
evaluation extraction/scoring. Does not unlock evaluation (that is P6-07's
``freeze_lock.json`` after ``experiment-v1``).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.assemble_rankings import (
    assemble_gpt_ranking,
    assemble_jev_ranking,
    semantic_ranking_path,
    verify_five_systems_present,
)
from src.audit_phase4 import audit_one_example as audit_phase4_one
from src.audit_phase5 import audit_one_example as audit_phase5_one
from src.candidates import load_candidates, load_ranking
from src.embeddings import (
    load_patch_representation_text,
    load_test_representation_texts,
)
from src.example_contract import (
    WORKSPACE,
    ExampleContractError,
    ExampleId,
    atomic_write_json,
    development_example_ids,
    example_paths,
    load_manifest,
    read_json,
    require_manifest_membership,
    validate_example_artifacts,
)
from src.experiment_config import load_experiment_config
from src.freeze_guard import freeze_lock_summary
from src.gpt_ranker import primary_comparison_model
from src.select_bugs import ManifestError, verify_manifest_integrity
from src.semantic_cache import build_jev_state

GATE_JSON = WORKSPACE / "results" / "phase6" / "pre_eval_gate.json"
GATE_MD = WORKSPACE / "docs" / "phase6-pre-eval-gate.md"
ACCEPTED_JEV_GAPS = {
    "Jsoup-70": {
        "test_class": "org.jsoup.integration.ConnectTest",
        "reason": "OpenRouter WAF A-001 (documented in EXPERIMENT.md)",
    }
}

# Pipeline-injected leakage patterns in *structured* model-visible payloads.
# Genuine Java source may contain the tokens "fixed"/"buggy"; we only flag
# explicit pipeline envelopes.
_LEAK_PATTERNS = [
    re.compile(r"(?im)^bug[_ ]?id\s*[:=]"),
    re.compile(r"(?im)^issue[_ ]?title\s*[:=]"),
    re.compile(r"(?im)^tests\.trigger\b"),
    re.compile(r"(?im)^trigger(?:ing)?[_ ]?(?:method|class|list)\s*[:=]"),
    re.compile(r"(?im)^expected[_ ]?result\s*[:=]"),
    re.compile(r"(?im)^defects4j\b"),
    re.compile(r"(?im)^qualified[_ ]?id\s*[:=]"),
]


class GateError(Exception):
    """One or more pre-evaluation gate checks failed."""


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_preregistration_agreement() -> dict[str, Any]:
    cfg = load_experiment_config()
    yaml_path = WORKSPACE / "experiment.yaml"
    md_path = WORKSPACE / "EXPERIMENT.md"
    jev_prompt = WORKSPACE / "prompts" / "jev" / "v1.json"
    gpt_prompt = WORKSPACE / "prompts" / "gpt" / "v1.json"
    errors: list[str] = []
    if not md_path.is_file():
        errors.append("missing EXPERIMENT.md")
    if not yaml_path.is_file():
        errors.append("missing experiment.yaml")
    for label, path, expected in (
        ("jev_prompt", jev_prompt, cfg["jev"].get("prompt_file_sha256")),
        ("gpt_prompt", gpt_prompt, cfg["gpt_nano"].get("prompt_file_sha256")),
    ):
        if not path.is_file():
            errors.append(f"missing {path}")
            continue
        digest = _sha256_file(path)
        if expected and digest != expected:
            errors.append(f"{label} sha mismatch: {digest} != {expected}")
    md = md_path.read_text(encoding="utf-8") if md_path.is_file() else ""
    for needle in ("FDR@10%", "prompts/jev/v1.json", "claim limits", "H1"):
        if needle.lower() not in md.lower():
            errors.append(f"EXPERIMENT.md missing {needle!r}")
    return {
        "ok": not errors,
        "errors": errors,
        "config_status": cfg.get("status"),
        "jev_prompt_version": cfg["jev"].get("prompt_version"),
        "gpt_prompt_version": cfg["gpt_nano"].get("prompt_version"),
        "prompt_revision_count": cfg["jev"].get("prompt_revision_count"),
    }


def check_no_evaluation_artifacts(manifest: Mapping[str, Any]) -> dict[str, Any]:
    hits: list[str] = []
    for qid in manifest.get("evaluation_bug_ids") or []:
        ex = ExampleId.parse(qid)
        for rel in (
            f"data/bugs/{ex.slug}/example.json",
            f"data/candidates/{ex.slug}.json",
            f"results/rankings/{ex.slug}.json",
            f"results/embeddings/{ex.slug}.json",
            f"results/random/{ex.slug}.json",
            f"results/semantic/jev/{ex.slug}.json",
            f"results/semantic/gpt_nano/{ex.slug}.json",
        ):
            if (WORKSPACE / rel).is_file():
                hits.append(rel)
    return {"ok": not hits, "hits": hits, "checked": len(manifest.get("evaluation_bug_ids") or [])}


def check_patch_direction(example: ExampleId) -> dict[str, Any]:
    paths = example_paths(example)
    example_doc = read_json(paths["example_json"])
    patch_meta = read_json(paths["patch_meta"])
    direction = example_doc.get("direction") or {}
    base = direction.get("base") or "Bf"
    proposed = direction.get("proposed") or "Bb"
    ok = (
        base == "Bf"
        and proposed == "Bb"
        and patch_meta.get("direction") == "fixed_to_buggy"
    )
    return {
        "ok": ok,
        "base": base,
        "proposed": proposed,
        "patch_meta_direction": patch_meta.get("direction"),
    }


def check_trigger_consistency(example: ExampleId) -> dict[str, Any]:
    validated = validate_example_artifacts(example, allow_evaluation=False)
    inventory = set(validated["inventory"]["test_classes"])
    labels = validated["labels"]
    positives = list(labels.get("positive_classes") or [])
    anomalies = (labels.get("consistency") or {}).get("anomalies") or []
    missing = [p for p in positives if p not in inventory]
    ok = not missing and (labels.get("consistency") or {}).get(
        "all_positives_in_inventory", True
    )
    return {
        "ok": ok,
        "num_positives": len(positives),
        "missing_from_inventory": missing,
        "anomalies": anomalies,
    }


def check_ranking_permutation(
    example: ExampleId, *, method: str, inventory: set[str], n: int
) -> dict[str, Any]:
    if method == "BM25":
        doc = load_ranking(example)
        ids = [e["test_class"] for e in doc.get("ranking") or []]
    elif method == "Embedding":
        path = WORKSPACE / "results" / "embeddings" / f"{example.slug}.json"
        if not path.is_file():
            return {"ok": False, "error": "missing"}
        doc = read_json(path)
        ids = [e["test_class"] for e in doc.get("ranking") or []]
    elif method == "Random":
        path = WORKSPACE / "results" / "random" / f"{example.slug}.json"
        if not path.is_file():
            return {"ok": False, "error": "missing"}
        doc = read_json(path)
        ok = int(doc.get("num_permutations") or 0) == 1000
        return {"ok": ok, "num_permutations": doc.get("num_permutations")}
    else:
        path = semantic_ranking_path(example, method=method)
        if not path.is_file():
            return {"ok": False, "error": "missing"}
        doc = read_json(path)
        ids = list(doc.get("ranked_ids") or [])
    ok = len(ids) == n and len(set(ids)) == n and set(ids) == inventory
    return {"ok": ok, "N": len(ids)}


def check_model_visible_state(example: ExampleId) -> dict[str, Any]:
    """Ensure prepared Jev/GPT state has only allowed keys and no pipeline leak headers."""
    candidates = load_candidates(example)
    patch = load_patch_representation_text(example)
    pairs = dict(load_test_representation_texts(example))
    leaks: list[dict[str, str]] = []
    checked = 0
    for cls in candidates["candidate_ids"]:
        text = pairs[cls]
        state = build_jev_state(code_change=patch, candidate_test=text)
        checked += 1
        if set(state.keys()) != {"code_change", "candidate_test"}:
            leaks.append(
                {
                    "test_class": cls,
                    "error": f"unexpected state keys {sorted(state.keys())}",
                }
            )
            continue
        for field in ("code_change", "candidate_test"):
            blob = state[field]
            # Bug id must not appear as a pipeline header line.
            if re.search(
                rf"(?im)^(?:bug|example|qualified)[_ ]?id\s*[:=]\s*{re.escape(example.qualified)}\s*$",
                blob,
            ):
                leaks.append({"test_class": cls, "error": f"bug id header in {field}"})
            for pat in _LEAK_PATTERNS:
                if pat.search(blob):
                    leaks.append(
                        {
                            "test_class": cls,
                            "error": f"leak pattern {pat.pattern!r} in {field}",
                        }
                    )
                    break
    return {"ok": not leaks, "checked_pairs": checked, "leaks": leaks[:20]}


def check_jev_gpt_shortlist_equality(example: ExampleId) -> dict[str, Any]:
    cand = load_candidates(example)
    jev_path = semantic_ranking_path(example, method="Jev")
    gpt_path = semantic_ranking_path(example, method="GPT-Nano")
    if not gpt_path.is_file():
        return {"ok": False, "error": "missing GPT-Nano ranking"}
    gpt = read_json(gpt_path)
    if not jev_path.is_file():
        gap = ACCEPTED_JEV_GAPS.get(example.qualified)
        if gap:
            return {
                "ok": True,
                "accepted_gap": gap,
                "gpt_candidates_match_phase4": gpt.get("candidate_ids")
                == cand["candidate_ids"],
                "shortlist_sha256": cand.get("shortlist_sha256"),
            }
        return {"ok": False, "error": "missing Jev ranking"}
    jev = read_json(jev_path)
    ok = (
        jev.get("candidate_ids") == gpt.get("candidate_ids") == cand["candidate_ids"]
        and jev.get("shortlist_sha256")
        == gpt.get("shortlist_sha256")
        == cand.get("shortlist_sha256")
    )
    # Same patch/test strings implied by shared cache key construction from
    # Phase-3 files; record representation hashes for traceability.
    patch = load_patch_representation_text(example)
    return {
        "ok": ok,
        "shortlist_sha256": cand.get("shortlist_sha256"),
        "K": cand.get("K"),
        "patch_sha256": hashlib.sha256(patch.encode()).hexdigest(),
    }


def cache_only_rebuild_proof(example: ExampleId = ExampleId.parse("Cli-30")) -> dict[str, Any]:
    saved = {
        k: os.environ.pop(k, None)
        for k in ("OPENROUTER_API_KEY", "OPENAI_API_KEY", "TYPESAFE_API_KEY")
    }
    try:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jev = assemble_jev_ranking(example, results_root=root, write=True)
            gpt = assemble_gpt_ranking(
                example,
                model=primary_comparison_model(),
                results_root=root,
                write=True,
            )
            return {
                "ok": True,
                "example": example.qualified,
                "credentials_cleared": True,
                "same_shortlist": jev.document["shortlist_sha256"]
                == gpt.document["shortlist_sha256"],
                "same_candidates": jev.document["candidate_ids"]
                == gpt.document["candidate_ids"],
                "jev_N": jev.document["N"],
                "gpt_N": gpt.document["N"],
            }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
    finally:
        for key, val in saved.items():
            if val is not None:
                os.environ[key] = val


def check_freeze_guard_blocks_evaluation() -> dict[str, Any]:
    """Ensure evaluation IDs are refused without freeze_lock."""
    manifest = load_manifest()
    eval_id = (manifest.get("evaluation_bug_ids") or [None])[0]
    if not eval_id:
        return {"ok": False, "error": "no evaluation ids in manifest"}
    summary = freeze_lock_summary()
    blocked = False
    error = None
    try:
        require_manifest_membership(eval_id, allow_evaluation=True)
        # If we get here, evaluation is unlocked (unexpected pre-P6-07).
        blocked = False
        error = "evaluation unexpectedly allowed before freeze_lock"
    except Exception as exc:  # noqa: BLE001
        blocked = True
        error = str(exc)
    ok = blocked and not summary["unlocked"]
    return {
        "ok": ok,
        "blocked_without_lock": blocked,
        "freeze_lock": summary,
        "probe_example": eval_id,
        "error": error,
    }


def audit_one_development_bug(example: ExampleId) -> dict[str, Any]:
    validated = validate_example_artifacts(example, allow_evaluation=False)
    inventory = set(validated["inventory"]["test_classes"])
    n = len(inventory)
    direction = check_patch_direction(example)
    triggers = check_trigger_consistency(example)
    five = verify_five_systems_present(example)
    gap = ACCEPTED_JEV_GAPS.get(example.qualified)
    systems_ok = all(
        [
            five.get("BM25"),
            five.get("Embedding"),
            five.get("Random"),
            five.get("GPT-Nano"),
            five.get("Jev") or bool(gap),
        ]
    )
    rankings = {
        "BM25": check_ranking_permutation(
            example, method="BM25", inventory=inventory, n=n
        ),
        "Embedding": check_ranking_permutation(
            example, method="Embedding", inventory=inventory, n=n
        ),
        "Random": check_ranking_permutation(
            example, method="Random", inventory=inventory, n=n
        ),
        "GPT-Nano": check_ranking_permutation(
            example, method="GPT-Nano", inventory=inventory, n=n
        ),
    }
    if five.get("Jev"):
        rankings["Jev"] = check_ranking_permutation(
            example, method="Jev", inventory=inventory, n=n
        )
        try:
            audit_phase5_one(example)
            p5_ok = True
            p5_error = None
        except Exception as exc:  # noqa: BLE001
            p5_ok = False
            p5_error = str(exc)
    else:
        rankings["Jev"] = {"ok": False, "accepted_gap": gap}
        p5_ok = bool(gap)
        p5_error = "accepted_gap" if gap else "missing_jev"
    p4 = audit_phase4_one(example)
    state = check_model_visible_state(example)
    shortlist = check_jev_gpt_shortlist_equality(example)
    ok = all(
        [
            direction["ok"],
            triggers["ok"],
            systems_ok,
            p4.get("ok"),
            p5_ok,
            state["ok"],
            shortlist["ok"],
            all(r.get("ok") for k, r in rankings.items() if k != "Jev" or five.get("Jev")),
        ]
    )
    return {
        "qualified_id": example.qualified,
        "ok": ok,
        "N": n,
        "direction": direction,
        "triggers": triggers,
        "systems": five,
        "accepted_gap": gap,
        "rankings": rankings,
        "phase4_ok": bool(p4.get("ok")),
        "phase5_ok": p5_ok,
        "phase5_note": p5_error,
        "model_visible_state": {
            "ok": state["ok"],
            "checked_pairs": state["checked_pairs"],
            "leak_count": len(state.get("leaks") or []),
            "leaks": state.get("leaks") or [],
        },
        "shortlist_equality": shortlist,
    }


def run_pre_eval_gate() -> dict[str, Any]:
    manifest = load_manifest()
    verify_manifest_integrity(manifest)
    targets = list(development_example_ids(manifest))
    bugs: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for ex in targets:
        try:
            row = audit_one_development_bug(ex)
            bugs.append(row)
            if not row["ok"]:
                failures.append(
                    {
                        "qualified_id": ex.qualified,
                        "error": "one or more development integrity checks failed",
                    }
                )
        except (GateError, ExampleContractError, ManifestError, OSError) as exc:
            failures.append({"qualified_id": ex.qualified, "error": str(exc)})
            bugs.append({"qualified_id": ex.qualified, "ok": False, "error": str(exc)})

    report: dict[str, Any] = {
        "schema_version": "jev-phase6-pre-eval-gate-v1",
        "generated_at": _utcnow(),
        "split": "development",
        "count": len(targets),
        "passed": sum(1 for b in bugs if b.get("ok")),
        "failed": len(failures),
        "preregistration": check_preregistration_agreement(),
        "no_evaluation_artifacts": check_no_evaluation_artifacts(manifest),
        "freeze_guard": check_freeze_guard_blocks_evaluation(),
        "cache_only_rebuild": cache_only_rebuild_proof(),
        "accepted_gaps": [
            {"qualified_id": k, **v} for k, v in ACCEPTED_JEV_GAPS.items()
        ],
        "bugs": bugs,
        "failures": failures,
        "evaluation_unlocked": False,
        "notes": (
            "Gate does not unlock evaluation. P6-07 writes freeze_lock.json "
            "after tagging experiment-v1."
        ),
    }
    report["ok"] = all(
        [
            report["failed"] == 0,
            report["preregistration"]["ok"],
            report["no_evaluation_artifacts"]["ok"],
            report["freeze_guard"]["ok"],
            report["cache_only_rebuild"]["ok"],
            report["passed"] == report["count"],
        ]
    )
    return report


def render_gate_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Phase 6 pre-evaluation integrity gate (P6-06)",
        "",
        f"Generated: `{report.get('generated_at')}`",
        "",
        f"**Overall: `{'PASS' if report.get('ok') else 'FAIL'}`**",
        "",
        "## Checks",
        "",
        f"- Development bugs passed: **{report['passed']}/{report['count']}**",
        f"- Preregistration agreement: "
        f"**{'ok' if report['preregistration']['ok'] else 'FAIL'}**",
        f"- No evaluation artifacts: "
        f"**{'ok' if report['no_evaluation_artifacts']['ok'] else 'FAIL'}** "
        f"(hits={len(report['no_evaluation_artifacts'].get('hits') or [])})",
        f"- Freeze guard blocks evaluation: "
        f"**{'ok' if report['freeze_guard']['ok'] else 'FAIL'}**",
        f"- Cache-only rebuild proof: "
        f"**{'ok' if report['cache_only_rebuild']['ok'] else 'FAIL'}** "
        f"({(report['cache_only_rebuild'] or {}).get('example')})",
        f"- Evaluation unlocked: **{report.get('evaluation_unlocked')}**",
        "",
        "## Accepted gaps",
        "",
    ]
    for gap in report.get("accepted_gaps") or []:
        lines.append(
            f"- **{gap['qualified_id']}** / `{gap['test_class']}`: {gap['reason']}"
        )
    if report.get("failures"):
        lines.extend(["", "## Failures", ""])
        for fail in report["failures"]:
            lines.append(f"- {fail['qualified_id']}: {fail['error']}")
    lines.extend(
        [
            "",
            "## Next",
            "",
            "P6-07: commit/tag `experiment-v1` and write "
            "`results/phase6/freeze_lock.json` (do not unlock evaluation before that).",
            "",
            f"Machine report: `results/phase6/pre_eval_gate.json`",
            "",
        ]
    )
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run Phase 6 pre-evaluation integrity gate (P6-06)."
    )
    parser.add_argument("--out-json", type=Path, default=GATE_JSON)
    parser.add_argument("--out-md", type=Path, default=GATE_MD)
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        report = run_pre_eval_gate()
    except (ManifestError, ExampleContractError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(args.out_json, report)
    args.out_md.write_text(render_gate_markdown(report), encoding="utf-8")
    print(
        f"pre-eval gate: {'PASS' if report['ok'] else 'FAIL'} "
        f"passed={report['passed']}/{report['count']}"
    )
    print(f"wrote: {args.out_json.relative_to(WORKSPACE)}")
    print(f"wrote: {args.out_md.relative_to(WORKSPACE)}")
    for fail in report.get("failures") or []:
        print(f"  ! {fail['qualified_id']}: {fail['error']}", file=sys.stderr)
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
