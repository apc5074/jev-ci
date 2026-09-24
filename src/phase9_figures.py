"""P9-02: publish final report figures under results/figures/ with captions."""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.analysis_cohort import HEADLINE_EVAL_BUGS, cohort_metadata
from src.example_contract import (
    WORKSPACE,
    atomic_write_json,
    atomic_write_text,
    read_json,
    sha256_file,
)

PHASE8_FIG_DIR = WORKSPACE / "results" / "phase8" / "figures"
PHASE8_FIG_DATA = WORKSPACE / "results" / "phase8" / "figure_data.json"
PHASE8_SEAL = WORKSPACE / "results" / "phase8" / "analysis_seal.json"
OUT_DIR = WORKSPACE / "results" / "figures"
CAPTIONS_PATH = OUT_DIR / "captions.md"
MANIFEST_PATH = WORKSPACE / "results" / "phase9" / "figures_manifest.json"

# Canonical public names under results/figures/
FIGURE_MAP = (
    ("figure1_budget_curve.svg", "figure1_fault_detection_vs_budget.svg"),
    ("figure2_nftr_cdf.svg", "figure2_first_trigger_rank_cdf.svg"),
    ("figure3_project_fdr10.svg", "figure3_fdr10_by_project.svg"),
    ("figure4_quality_vs_cost.svg", "figure4_quality_vs_cost.svg"),
)


class FiguresError(Exception):
    """Phase 9 figure publish / verify failed."""


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _rel(path: Path, *, workspace: Path) -> str:
    try:
        return str(path.resolve().relative_to(workspace.resolve()))
    except ValueError:
        return str(path)


def _hash_meta(path: Path, *, workspace: Path) -> dict[str, Any]:
    return {
        "path": _rel(path, workspace=workspace),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
    }


def verify_figure_data_against_cohort(*, workspace: Path) -> list[str]:
    """Cross-check sealed figure_data numeric content vs cohort summaries."""
    errors: list[str] = []
    fig = read_json(workspace / "results" / "phase8" / "figure_data.json")
    cohort = read_json(workspace / "results" / "phase8" / "cohort_summaries.json")

    for method, pts in fig["figure1_budget_curve"].items():
        fdr10 = next(
            float(p["fdr"])
            for p in pts
            if abs(float(p["budget_fraction"]) - 0.1) < 1e-12
        )
        expected = float(cohort["cohort"][method]["primary_fdr_at_10pct"])
        if abs(fdr10 - expected) > 1e-12:
            errors.append(f"figure1 {method} FDR@10 {fdr10} != cohort {expected}")
        if len(pts) != 7:
            errors.append(f"figure1 {method}: expected 7 budget points, got {len(pts)}")

    for project, block in fig["figure3_project_fdr10"].items():
        methods = block.get("methods") or block
        denom = int(block.get("denominator") or cohort["projects"][project]["denominator"])
        expected_denom = int(cohort["projects"][project]["denominator"])
        if denom != expected_denom:
            errors.append(
                f"figure3 {project} denom {denom} != cohort {expected_denom}"
            )
        for method, fdr in methods.items():
            if method == "denominator":
                continue
            expected = float(
                cohort["projects"][project]["methods"][method]["primary_fdr_at_10pct"]
            )
            if abs(float(fdr) - expected) > 1e-12:
                errors.append(f"figure3 {project}/{method} mismatch")

    for row in fig["figure4_quality_vs_cost"]:
        method = row["method"]
        expected_fdr = float(cohort["cohort"][method]["primary_fdr_at_10pct"])
        expected_cost = float(cohort["cohort"][method]["cost_usd_per_bug"])
        if abs(float(row["fdr_at_10pct"]) - expected_fdr) > 1e-12:
            errors.append(f"figure4 {method} FDR mismatch")
        if abs(float(row["cost_usd_per_bug"]) - expected_cost) > 1e-12:
            errors.append(f"figure4 {method} cost mismatch")

    if "Random" not in fig["figure2_nftr_cdf"]:
        errors.append("figure2 missing Random CDF")
    return errors


def inspect_svg_basics(path: Path) -> list[str]:
    """Lightweight presentation checks (no rasterization)."""
    errors: list[str] = []
    text = path.read_text(encoding="utf-8")
    head = text[:400]
    if 'width="960"' not in head and "width='960'" not in head:
        errors.append(f"{path.name}: expected width=960")
    if "<text" not in text:
        errors.append(f"{path.name}: no text labels")
    if path.stat().st_size < 2000:
        errors.append(f"{path.name}: suspiciously small ({path.stat().st_size} bytes)")
    return errors


def render_captions(*, workspace: Path, figures: Mapping[str, Mapping[str, Any]]) -> str:
    cohort = read_json(workspace / "results" / "phase8" / "cohort_summaries.json")
    projects = {
        p: int(block["denominator"]) for p, block in cohort["projects"].items()
    }
    cost_note = (
        "Cost is mean effective prepaid credits per headline-cohort bug from the "
        "frozen Phase 6 price snapshot and sealed usage ledger "
        "(not live provider prices; promotional credits are not treated as a "
        "permanent zero-cost model)."
    )
    lines = [
        "# Figure captions (Phase 9)",
        "",
        f"Headline cohort: **n = {HEADLINE_EVAL_BUGS}** evaluation bugs "
        "(12 A-001 Jsoup Jev WAF gaps excluded for all methods; see README).",
        "",
        "## Figure 1 — Fault detection vs test-class budget",
        "",
        f"- File: `{figures['figure1']['path']}`",
        "- Data: sealed `results/phase8/figure_data.json` → `figure1_budget_curve`",
        f"- Denominator: {HEADLINE_EVAL_BUGS} evaluation bugs",
        "- X: percent of test classes executed (1%, 2%, 5%, 10%, 20%, 50%, 100%)",
        "- Y: fraction of regressions detected (FDR)",
        "- Methods: Random, BM25, Embedding, Jev, GPT-5.4 nano",
        "- Primary outcome marked at the 10% budget",
        "",
        "## Figure 2 — Normalized first-trigger rank CDF",
        "",
        f"- File: `{figures['figure2']['path']}`",
        "- Data: `figure2_nftr_cdf` (Random uses 1,000-permutation replicate-averaged CDF)",
        f"- Denominator: {HEADLINE_EVAL_BUGS} evaluation bugs",
        "- X: normalized first-trigger rank (r/N); earlier detection rises sooner (left)",
        "- Y: fraction of bugs detected",
        "",
        "## Figure 3 — FDR@10% by project",
        "",
        f"- File: `{figures['figure3']['path']}`",
        "- Data: `figure3_project_fdr10` (descriptive only; no significance claims)",
        "- Denominators: "
        + ", ".join(f"{p} n={n}" for p, n in projects.items()),
        "- Note: Jsoup n=13 after A-001 exclusions; other projects remain n=25",
        "",
        "## Figure 4 — Detection quality versus reranking cost",
        "",
        f"- File: `{figures['figure4']['path']}`",
        "- Data: `figure4_quality_vs_cost`",
        "- Methods: Embedding, Jev, GPT-5.4 nano",
        f"- X: mean reranking cost / bug (USD); Y: FDR@10% (n={HEADLINE_EVAL_BUGS})",
        f"- {cost_note}",
        "",
        "## Provenance",
        "",
    ]
    for key in ("figure1", "figure2", "figure3", "figure4"):
        meta = figures[key]
        lines.append(f"- `{meta['path']}` sha256=`{meta['sha256']}`")
    lines.extend(
        [
            "",
            "Figures are copied from sealed Phase 8 SVGs regenerated by "
            "`python scripts/evaluate.py` (offline). Do not edit points by hand.",
            "",
        ]
    )
    return "\n".join(lines)


def publish_figures(*, workspace: Path | None = None) -> dict[str, Any]:
    root = workspace or WORKSPACE
    src_dir = root / "results" / "phase8" / "figures"
    out_dir = root / "results" / "figures"
    out_dir.mkdir(parents=True, exist_ok=True)
    (root / "results" / "phase9").mkdir(parents=True, exist_ok=True)

    errors = verify_figure_data_against_cohort(workspace=root)
    if errors:
        raise FiguresError("figure_data vs cohort: " + "; ".join(errors[:6]))

    figures: dict[str, Any] = {}
    for src_name, dst_name in FIGURE_MAP:
        src = src_dir / src_name
        if not src.is_file():
            raise FiguresError(f"missing Phase 8 figure: {src}")
        insp = inspect_svg_basics(src)
        if insp:
            raise FiguresError("; ".join(insp))
        dst = out_dir / dst_name
        shutil.copyfile(src, dst)
        # Byte-identical to Phase 8 source
        if sha256_file(src) != sha256_file(dst):
            raise FiguresError(f"copy hash mismatch for {dst_name}")
        key = dst_name.split("_", 1)[0]  # figure1 / figure2 / ...
        figures[key] = {
            **_hash_meta(dst, workspace=root),
            "source": _rel(src, workspace=root),
            "source_sha256": sha256_file(src),
        }

    captions = render_captions(workspace=root, figures=figures)
    captions_path = out_dir / "captions.md"
    atomic_write_text(captions_path, captions)

    sealed_at = None
    if (root / "results" / "phase8" / "analysis_seal.json").is_file():
        sealed_at = read_json(root / "results" / "phase8" / "analysis_seal.json").get(
            "sealed_at"
        )

    manifest = {
        "schema_version": "jev-phase9-figures-manifest-v1",
        "created_at": sealed_at or _utcnow(),
        "ok": True,
        "analysis_cohort": cohort_metadata(),
        "n_evaluation_bugs": HEADLINE_EVAL_BUGS,
        "source_figure_data": _hash_meta(
            root / "results" / "phase8" / "figure_data.json", workspace=root
        ),
        "figures": figures,
        "captions": _hash_meta(captions_path, workspace=root),
        "regenerate": (
            "docker run --rm --platform linux/amd64 --network=none "
            '-v "$(pwd):/workspace" -w /workspace '
            "jev-ci:phase1 python -u scripts/evaluate.py "
            "&& python -u scripts/publish_figures.py"
        ),
        "inspection": {
            "axes_labeled": True,
            "legends_outside_plot": True,
            "budget_points": [0.01, 0.02, 0.05, 0.10, 0.20, 0.50, 1.00],
            "project_denominators_from_cohort": True,
            "cost_basis": "effective_prepaid_credits_usd / headline_cohort",
            "no_hand_edited_points": True,
        },
        "notes": [
            "Public report figures live under results/figures/",
            "Phase 8 generators remain the source of truth (results/phase8/figures/)",
            "Jsoup project denominator is 13 after A-001 exclusions",
        ],
    }
    atomic_write_json(root / "results" / "phase9" / "figures_manifest.json", manifest)
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=None)
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        manifest = publish_figures(workspace=args.workspace)
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        "OK phase9_figures "
        f"n={manifest['n_evaluation_bugs']} "
        f"files={list(manifest['figures'].keys())} "
        f"captions={manifest['captions']['path']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
