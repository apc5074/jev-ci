"""P9-07: final consistency check, finding statement, and artifact index."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.example_contract import (
    WORKSPACE,
    atomic_write_json,
    atomic_write_text,
    read_json,
    sha256_file,
)
from src.phase9_reproduction import build_inventory, reconcile_report_claims

SCHEMA = "jev-phase9-final-v1"
OUT_JSON = WORKSPACE / "results" / "phase9" / "final_index.json"
OUT_MD = WORKSPACE / "results" / "phase9" / "final_index.md"
FINDING_MD = WORKSPACE / "results" / "phase9" / "main_finding.md"

METHOD_NAMES = ("Random", "BM25", "Embedding", "Jev", "GPT-5.4 nano", "GPT-Nano")


class FinalCloseError(Exception):
    """Phase 9 final close failed."""


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _rel(path: Path, *, workspace: Path) -> str:
    try:
        return str(path.resolve().relative_to(workspace.resolve()))
    except ValueError:
        return str(path)


def _hash_meta(path: Path, *, workspace: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return {
        "path": _rel(path, workspace=workspace),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
    }


def consistency_checks(*, workspace: Path) -> dict[str, Any]:
    errors: list[str] = []
    cohort = read_json(workspace / "results/phase8/cohort_summaries.json")
    headline = read_json(workspace / "results/phase9/headline_table.json")
    stats = read_json(workspace / "results/statistics.json")
    figures_man = read_json(workspace / "results/phase9/figures_manifest.json")
    failure = read_json(workspace / "results/failure_analysis.json")
    cases = read_json(workspace / "results/failure_cases.json")
    repro = read_json(workspace / "results/phase9/reproduction_record.json")
    seal8 = read_json(workspace / "results/phase8/analysis_seal.json")

    method_order = list(headline.get("method_order") or [])
    if method_order != ["Random", "BM25", "Embedding", "Jev", "GPT-Nano"]:
        errors.append(f"headline method_order unexpected: {method_order}")

    readme = (workspace / "README.md").read_text(encoding="utf-8")
    for name in ("Random", "BM25", "Embedding", "Jev", "GPT-5.4 nano"):
        if name not in readme:
            errors.append(f"README missing method name {name}")

    jev = float(cohort["cohort"]["Jev"]["primary_fdr_at_10pct"])
    bm25 = float(cohort["cohort"]["BM25"]["primary_fdr_at_10pct"])
    if abs(jev - 0.9557522123893806) > 1e-9:
        errors.append(f"unexpected Jev FDR {jev}")
    if abs(bm25 - 0.7345132743362832) > 1e-9:
        errors.append(f"unexpected BM25 FDR {bm25}")

    if len(failure["cases"]) != 20 or len(cases["selected_ids"]) != 20:
        errors.append("failure analysis/cases not length 20")
    if failure["selected_ids"] != cases["selected_ids"]:
        errors.append("failure analysis IDs != failure_cases selected_ids")

    if len(figures_man.get("figures", [])) != 4:
        errors.append("figures manifest does not list 4 figures")

    if not repro.get("ok"):
        errors.append("reproduction_record.ok is false")

    if not seal8.get("ok", True) and "phase8_artifacts" not in seal8:
        errors.append("phase8 analysis seal missing")

    # Candidate ceiling story matches handoff
    ceiling = cohort.get("candidate_ceiling") or {}
    if float(ceiling.get("recall", -1)) != 1.0:
        errors.append(f"candidate recall not 1.0: {ceiling}")

    reconcile = reconcile_report_claims(workspace=workspace)
    if not reconcile["ok"]:
        errors.append(f"report reconciliation failed: {reconcile['text_checks']}")

    return {
        "ok": len(errors) == 0,
        "errors": errors,
        "jev_fdr_at_10pct": jev,
        "bm25_fdr_at_10pct": bm25,
        "delta_pp": 100.0 * (jev - bm25),
        "mcnemar_p": stats["primary"]["paired_detection_fdr_at_10pct"][
            "mcnemar_exact_two_sided_p"
        ],
        "practical_success": cohort["practical_success"]["practically_successful"],
        "n_cases": len(failure["cases"]),
        "n_figures": len(figures_man.get("figures", [])),
        "reproduction_ok": bool(repro.get("ok")),
        "report_reconciliation": reconcile,
    }


def main_finding_text(*, workspace: Path) -> str:
    cohort = read_json(workspace / "results/phase8/cohort_summaries.json")
    jev = float(cohort["cohort"]["Jev"]["primary_fdr_at_10pct"])
    bm25 = float(cohort["cohort"]["BM25"]["primary_fdr_at_10pct"])
    delta_pp = 100.0 * (jev - bm25)
    n = int(cohort["counts"]["evaluation_bugs"])
    practical = cohort["practical_success"]
    return "\n".join(
        [
            "# Main finding",
            "",
            f"On the paired headline cohort (**n = {n}** evaluation bugs), "
            f"**Jev** ranked known fault-revealing test classes under a **10% "
            f"test-class execution budget** more effectively than **BM25**: "
            f"FDR@10% **{jev:.4f}** vs **{bm25:.4f}** (**+{delta_pp:.1f} pp**).",
            "",
            "The preregistered practical-success rule **passed** via alternative 1 "
            f"(≥5 pp over BM25; winning_alternative=`{practical.get('winning_alternative')}`).",
            "",
            "This result is about **ranking known triggering tests** at a class-count "
            "budget. It does **not** claim a 90% CI runtime reduction, superior general "
            "code understanding, calibrated probabilities, or relevance judgments about "
            "non-triggering tests.",
            "",
            "Frozen raw Phase 7 data and Phase 8 analyzed outputs remain the source of "
            "truth; Phase 9 only presents and interprets them. The design lock in "
            "`experiment.yaml` is unchanged.",
            "",
        ]
    )


def build_final_index(*, workspace: Path) -> dict[str, Any]:
    root = workspace
    consistency = consistency_checks(workspace=root)
    if not consistency["ok"]:
        raise FinalCloseError(f"consistency failed: {consistency['errors']}")

    inventory = build_inventory(workspace=root)
    if not inventory["ok"]:
        raise FinalCloseError(f"inventory missing: {inventory['missing']}")

    finding = main_finding_text(workspace=root)
    atomic_write_text(root / "results/phase9/main_finding.md", finding)

    index = {
        "schema_version": SCHEMA,
        "generated_at_utc": _utcnow(),
        "ok": True,
        "phase_complete": True,
        "main_finding_path": "results/phase9/main_finding.md",
        "consistency": consistency,
        "freeze": {
            "tag": "experiment-v1",
            "experiment_commit": "edc70bacd23f2fc5f511ef4d97a33376e7b20bf8",
            "phase7_seal": _hash_meta(
                root / "results/phase7/raw_evaluation_seal.json", workspace=root
            ),
            "phase8_seal": _hash_meta(
                root / "results/phase8/analysis_seal.json", workspace=root
            ),
        },
        "artifact_index": {
            "manifest": "data/manifest.json",
            "preregistration": "experiment.yaml",
            "metrics": "results/metrics.csv",
            "predictions": "results/predictions.jsonl",
            "statistics": "results/statistics.json",
            "headline_table": "results/phase9/headline_table.md",
            "figures": "results/figures/",
            "failure_cases": "results/failure_cases.json",
            "failure_analysis": "results/failure_analysis.json",
            "readme": "README.md",
            "reproduction": "results/phase9/reproduction_record.json",
            "inventory": "results/phase9/final_artifact_inventory.json",
            "main_finding": "results/phase9/main_finding.md",
        },
        "inventory_ok": inventory["ok"],
        "deviations_recorded": [
            "A-001-eval: 12 Jsoup WAF gaps excluded from all methods (n=113)",
            "D-wallclock: shortlist walls reconstructed from per-request latencies",
            "D-tag-name: freeze tag experiment-v1",
        ],
        "post_hoc_exploration": [
            "P9-04 qualitative categories on mechanical 20-case list (explanatory only)",
        ],
    }
    return index


def render_final_index_md(doc: Mapping[str, Any]) -> str:
    lines = [
        "# Phase 9 final artifact index (P9-07)",
        "",
        f"**Phase complete: `{doc['phase_complete']}`** · consistency OK: `{doc['consistency']['ok']}`",
        "",
        "## Main finding",
        "",
        f"See [`main_finding.md`](main_finding.md). "
        f"Jev FDR@10%={doc['consistency']['jev_fdr_at_10pct']:.4f} vs "
        f"BM25={doc['consistency']['bm25_fdr_at_10pct']:.4f} "
        f"(+{doc['consistency']['delta_pp']:.1f} pp); practical success="
        f"`{doc['consistency']['practical_success']}`.",
        "",
        "## Artifact index",
        "",
        "| Role | Path |",
        "| --- | --- |",
    ]
    for role, path in doc["artifact_index"].items():
        lines.append(f"| {role} | `{path}` |")
    lines.extend(
        [
            "",
            "## Freeze",
            "",
            f"- Tag: `{doc['freeze']['tag']}`",
            f"- Commit: `{doc['freeze']['experiment_commit']}`",
            f"- Phase 7 seal: `{doc['freeze']['phase7_seal']['sha256'] if doc['freeze']['phase7_seal'] else 'missing'}`",
            f"- Phase 8 seal: `{doc['freeze']['phase8_seal']['sha256'] if doc['freeze']['phase8_seal'] else 'missing'}`",
            "",
            "## Deviations / post-hoc",
            "",
        ]
    )
    for d in doc["deviations_recorded"]:
        lines.append(f"- {d}")
    for p in doc["post_hoc_exploration"]:
        lines.append(f"- Post-hoc: {p}")
    lines.append("")
    return "\n".join(lines)


def publish_final(*, workspace: Path | None = None) -> dict[str, Any]:
    root = workspace or WORKSPACE
    doc = build_final_index(workspace=root)
    out_dir = root / "results" / "phase9"
    out_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(out_dir / "final_index.json", doc)
    atomic_write_text(out_dir / "final_index.md", render_final_index_md(doc))
    return doc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P9-07: finalize Phase 9 closeout")
    parser.add_argument("--workspace", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        doc = publish_final(workspace=args.workspace)
    except FinalCloseError as exc:
        print(f"FAIL phase9_final: {exc}", file=sys.stderr)
        return 1
    print(
        "OK phase9_final "
        f"complete={doc['phase_complete']} "
        f"delta_pp={doc['consistency']['delta_pp']:.1f} "
        f"path=results/phase9/final_index.json"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
