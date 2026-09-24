"""P9-01: verify Phase 8 analysis handoff and finalize the headline table."""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.analysis_cohort import (
    HEADLINE_EVAL_BUGS,
    HEADLINE_METRICS_ROWS,
    cohort_metadata,
    is_excluded_a001,
)
from src.example_contract import (
    WORKSPACE,
    atomic_write_json,
    atomic_write_text,
    read_json,
    sha256_file,
)
from src.report_outputs import METHODS, build_headline_table

PHASE7_SEAL = WORKSPACE / "results" / "phase7" / "raw_evaluation_seal.json"
PHASE8_SEAL = WORKSPACE / "results" / "phase8" / "analysis_seal.json"
FREEZE_LOCK = WORKSPACE / "results" / "phase6" / "freeze_lock.json"
METRICS_CSV = WORKSPACE / "results" / "metrics.csv"
HEADLINE_MD = WORKSPACE / "results" / "phase9" / "headline_table.md"
HEADLINE_JSON = WORKSPACE / "results" / "phase9" / "headline_table.json"
VERIFY_JSON = WORKSPACE / "results" / "phase9" / "handoff_verification.json"

SCHEMA = "jev-phase9-handoff-verification-v1"
HEADLINE_SCHEMA = "jev-phase9-headline-table-v1"


class HandoffError(Exception):
    """Phase 9 handoff verification failed."""


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _rel(path: Path, *, workspace: Path) -> str:
    try:
        return str(path.resolve().relative_to(workspace.resolve()))
    except ValueError:
        return str(path)


def _fmt_rate(x: float) -> str:
    return f"{x:.4f}"


def _fmt_usd(x: float | None) -> str:
    if x is None:
        return "—"
    return f"{x:.6f}"


def _hash_meta(path: Path, *, workspace: Path) -> dict[str, Any]:
    return {
        "path": _rel(path, workspace=workspace),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
    }


def _load_metrics_rows(workspace: Path) -> list[dict[str, str]]:
    path = workspace / "results" / "metrics.csv"
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _as_float(value: str) -> float:
    return float(value)


def _as_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes"}


def _best_methods(
    methods: Mapping[str, Mapping[str, Any]],
    key: str,
    *,
    lower_better: bool = False,
) -> set[str]:
    vals = {m: float(methods[m][key]) for m in METHODS}
    target = min(vals.values()) if lower_better else max(vals.values())
    return {m for m, v in vals.items() if abs(v - target) < 1e-12}


def verify_handoff(*, workspace: Path | None = None) -> dict[str, Any]:
    root = workspace or WORKSPACE
    errors: list[str] = []
    notes: list[str] = []

    phase7_path = root / "results" / "phase7" / "raw_evaluation_seal.json"
    phase8_path = root / "results" / "phase8" / "analysis_seal.json"
    freeze_path = root / "results" / "phase6" / "freeze_lock.json"
    for required in (phase7_path, phase8_path, freeze_path, root / "results" / "metrics.csv"):
        if not required.is_file():
            errors.append(f"missing required file: {_rel(required, workspace=root)}")

    if errors:
        return {
            "schema_version": SCHEMA,
            "ok": False,
            "errors": errors,
            "notes": notes,
            "created_at": _utcnow(),
        }

    phase7 = read_json(phase7_path)
    phase8 = read_json(phase8_path)
    freeze = read_json(freeze_path)

    # Phase 7 seal integrity
    for key in ("predictions", "raw_result_index"):
        block = phase7.get(key) or {}
        path = root / str(block.get("path") or "")
        expected = str(block.get("sha256") or "")
        if not path.is_file():
            errors.append(f"phase7 missing {key} at {path}")
            continue
        live = sha256_file(path)
        if live != expected:
            errors.append(f"phase7 {key} hash mismatch: live={live} seal={expected}")

    # Phase 8 analysis seal integrity
    if not phase8.get("ok"):
        errors.append("phase8 analysis_seal.ok is false")
    artifacts = phase8.get("phase8_artifacts") or {}
    for key, meta in artifacts.items():
        if key == "figures":
            for name, fig in meta.items():
                path = root / fig["path"]
                if not path.is_file():
                    errors.append(f"missing figure {name}")
                    continue
                live = sha256_file(path)
                if live != fig["sha256"]:
                    errors.append(
                        f"figure {name} hash mismatch: live={live} seal={fig['sha256']}"
                    )
            continue
        path = root / meta["path"]
        if not path.is_file():
            errors.append(f"missing artifact {key}")
            continue
        live = sha256_file(path)
        if live != meta["sha256"]:
            errors.append(
                f"artifact {key} hash mismatch: live={live} seal={meta['sha256']}"
            )

    experiment_commit = str(phase8.get("experiment_commit") or "")
    if freeze.get("commit_sha") != experiment_commit:
        errors.append(
            f"freeze_lock commit {freeze.get('commit_sha')!r} != "
            f"seal {experiment_commit!r}"
        )
    if freeze.get("tag") not in {"experiment-v1", "experiment-v1-frozen"}:
        errors.append(f"unexpected freeze tag {freeze.get('tag')!r}")
    if phase8.get("freeze_tag") not in {"experiment-v1", "experiment-v1-frozen"}:
        errors.append(f"unexpected phase8 freeze_tag {phase8.get('freeze_tag')!r}")

    # Coverage: headline cohort bugs + metrics rows
    stats = read_json(root / "results" / "statistics.json")
    bug_ids = list(stats.get("configuration", {}).get("bug_id_order") or [])
    if len(bug_ids) != HEADLINE_EVAL_BUGS:
        errors.append(
            f"statistics bug_id_order length {len(bug_ids)} != {HEADLINE_EVAL_BUGS}"
        )
    if len(set(bug_ids)) != len(bug_ids):
        errors.append("duplicate bug IDs in statistics configuration")
    if any(is_excluded_a001(qid) for qid in bug_ids):
        errors.append("statistics still includes an A-001 excluded bug")

    rows = _load_metrics_rows(root)
    if len(rows) != HEADLINE_METRICS_ROWS:
        errors.append(
            f"metrics.csv has {len(rows)} rows, expected {HEADLINE_METRICS_ROWS}"
        )
    methods_seen = {r["method"] for r in rows}
    if methods_seen != set(METHODS):
        errors.append(f"metrics methods {sorted(methods_seen)} != {list(METHODS)}")
    splits = {r["split"] for r in rows}
    if splits != {"evaluation"}:
        errors.append(f"unexpected splits in metrics.csv: {splits}")
    qids = {r["qualified_id"] for r in rows}
    if len(qids) != HEADLINE_EVAL_BUGS:
        errors.append(f"metrics.csv unique bugs {len(qids)} != {HEADLINE_EVAL_BUGS}")
    if set(bug_ids) and set(bug_ids) != qids:
        errors.append("statistics bug_id_order does not match metrics.csv IDs")

    # Cross-check headline / cohort / CSV FDR@10% and costs
    cohort = read_json(root / "results" / "phase8" / "cohort_summaries.json")
    table = build_headline_table(workspace=root)

    for method in METHODS:
        method_rows = [r for r in rows if r["method"] == method]
        if len(method_rows) != HEADLINE_EVAL_BUGS:
            errors.append(
                f"{method}: expected {HEADLINE_EVAL_BUGS} CSV rows, got {len(method_rows)}"
            )
            continue
        if method == "Random":
            mean_det = (
                sum(_as_float(r["detected_at_10pct"]) for r in method_rows)
                / float(HEADLINE_EVAL_BUGS)
            )
        else:
            mean_det = (
                sum(1 for r in method_rows if _as_bool(r["detected_at_10pct"]))
                / float(HEADLINE_EVAL_BUGS)
            )
        reported = float(cohort["cohort"][method]["primary_fdr_at_10pct"])
        headline = float(table["methods"][method]["fdr_at_10pct"])
        if abs(mean_det - reported) > 1e-9:
            errors.append(f"{method} CSV FDR@10 {mean_det} != cohort {reported}")
        if abs(headline - reported) > 1e-12:
            errors.append(f"{method} headline FDR@10 {headline} != cohort {reported}")

        if method in {"Embedding", "Jev", "GPT-Nano"}:
            csv_sum = sum(
                float(r["reranker_cost_usd"])
                for r in method_rows
                if r.get("reranker_cost_usd") not in (None, "")
            )
            per_bug = float(table["methods"][method]["cost_usd_per_bug"])
            expected_sum = per_bug * HEADLINE_EVAL_BUGS
            if abs(csv_sum - expected_sum) > 1e-4:
                errors.append(
                    f"{method} CSV cost sum {csv_sum} != headline*n {expected_sum}"
                )

    # Figure-data provenance vs cohort (FDR@10 points)
    fig = read_json(root / "results" / "phase8" / "figure_data.json")
    for method, pts in fig["figure1_budget_curve"].items():
        fdr10 = next(
            float(p["fdr"])
            for p in pts
            if abs(float(p["budget_fraction"]) - 0.1) < 1e-12
        )
        expected = float(cohort["cohort"][method]["primary_fdr_at_10pct"])
        if abs(fdr10 - expected) > 1e-12:
            errors.append(f"figure_data {method} FDR@10 {fdr10} != cohort {expected}")

    notes.append(f"phase7_seal_ok={not any('phase7' in e for e in errors)}")
    notes.append(f"n_metrics_rows={len(rows)}")
    notes.append(f"n_evaluation_bugs={len(qids)}")

    sealed_at = str(phase8.get("sealed_at") or phase7.get("sealed_at") or _utcnow())
    return {
        "schema_version": SCHEMA,
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "created_at": sealed_at,
        "freeze_tag": phase8.get("freeze_tag"),
        "experiment_commit": experiment_commit,
        "run_id": phase8.get("run_id"),
        "phase7_seal": _hash_meta(phase7_path, workspace=root),
        "phase8_seal": _hash_meta(phase8_path, workspace=root),
        "metrics_csv": _hash_meta(root / "results" / "metrics.csv", workspace=root),
        "statistics_json": _hash_meta(
            root / "results" / "statistics.json", workspace=root
        ),
        "figure_data": _hash_meta(
            root / "results" / "phase8" / "figure_data.json", workspace=root
        ),
        "n_evaluation_bugs": len(qids),
        "n_metrics_rows": len(rows),
        "method_order": list(METHODS),
    }


def render_report_headline(
    table: Mapping[str, Any],
    *,
    provenance: Mapping[str, Any],
) -> str:
    methods = table["methods"]
    names = table["display_name"]
    best = {
        "fdr_at_5pct": _best_methods(methods, "fdr_at_5pct"),
        "fdr_at_10pct": _best_methods(methods, "fdr_at_10pct"),
        "fdr_at_20pct": _best_methods(methods, "fdr_at_20pct"),
        "mrr": _best_methods(methods, "mrr"),
        "apfd": _best_methods(methods, "apfd"),
        "median_nftr": _best_methods(methods, "median_nftr", lower_better=True),
    }
    cols = [
        ("FDR@5%", "fdr_at_5pct"),
        ("FDR@10%", "fdr_at_10pct"),
        ("FDR@20%", "fdr_at_20pct"),
        ("MRR", "mrr"),
        ("APFD", "apfd"),
        ("Median NFTR", "median_nftr"),
        ("Cost/Bug", "cost_usd_per_bug"),
    ]
    lines = [
        "# Headline results (evaluation, n=113)",
        "",
        "Fixed method order: Random, BM25, Embedding, Jev, GPT-5.4 nano. "
        "**FDR@10%** is the primary outcome. "
        "Twelve A-001 Jsoup bugs are excluded from every method (see README).",
        "",
        "| Method | FDR@5% | FDR@10% | FDR@20% | MRR | APFD | Median NFTR | Cost/Bug |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for method in METHODS:
        cells = [names[method]]
        for _, key in cols:
            if key == "cost_usd_per_bug":
                if method in {"Random", "BM25"}:
                    cells.append("—")
                else:
                    cells.append(_fmt_usd(methods[method][key]))
                continue
            text = _fmt_rate(float(methods[method][key]))
            if method in best[key]:
                text = f"**{text}**"
            cells.append(text)
        lines.append("| " + " | ".join(cells) + " |")

    jev = float(methods["Jev"]["fdr_at_10pct"])
    bm25 = float(methods["BM25"]["fdr_at_10pct"])
    lines.extend(
        [
            "",
            "## Presentation notes",
            "",
            "- Bold marks the best quality value in each column "
            "(highest FDR/MRR/APFD; **lowest** median NFTR). Ties are all bolded.",
            "- Cost/Bug is **not** treated as a quality metric and is never bolded.",
            "- Random and BM25 show an em dash (—): they incur no paid API cost under "
            "the Phase 6 pricing snapshot.",
            "- Paid Cost/Bug is mean **effective prepaid credits** per headline-cohort "
            "evaluation bug (Embedding / Jev / GPT-5.4 nano), from the frozen usage "
            f"ledger ÷ {HEADLINE_EVAL_BUGS}.",
            f"- Primary contrast: Jev FDR@10% = {_fmt_rate(jev)} vs BM25 = {_fmt_rate(bm25)} "
            f"(Δ = {100.0 * (jev - bm25):+.1f} pp).",
            "",
            "## Provenance",
            "",
            f"- Freeze tag: `{provenance.get('freeze_tag')}`",
            f"- Experiment commit: `{provenance.get('experiment_commit')}`",
            f"- Run ID: `{provenance.get('run_id')}`",
            f"- Phase 8 analysis seal: `{provenance.get('phase8_seal', {}).get('sha256')}`",
            f"- `metrics.csv`: `{provenance.get('metrics_csv', {}).get('sha256')}`",
            f"- `statistics.json`: `{provenance.get('statistics_json', {}).get('sha256')}`",
            f"- `figure_data.json`: `{provenance.get('figure_data', {}).get('sha256')}`",
            "",
            "Values are generated from sealed Phase 8 cohort summaries and cross-checked "
            "against `metrics.csv` and the cost ledger — not hand-copied.",
            "",
        ]
    )
    return "\n".join(lines)


def build_headline_artifact(
    *,
    workspace: Path,
    verification: Mapping[str, Any],
) -> dict[str, Any]:
    table = build_headline_table(workspace=workspace)
    sealed_at = str(verification.get("created_at") or _utcnow())
    return {
        "schema_version": HEADLINE_SCHEMA,
        "created_at": sealed_at,
        "freeze_tag": verification.get("freeze_tag"),
        "experiment_commit": verification.get("experiment_commit"),
        "run_id": verification.get("run_id"),
        "n_evaluation_bugs": HEADLINE_EVAL_BUGS,
        "analysis_cohort": cohort_metadata(),
        "method_order": list(METHODS),
        "display_name": table["display_name"],
        "methods": table["methods"],
        "best_quality": {
            key: sorted(_best_methods(table["methods"], key, lower_better=(key == "median_nftr")))
            for key in (
                "fdr_at_5pct",
                "fdr_at_10pct",
                "fdr_at_20pct",
                "mrr",
                "apfd",
                "median_nftr",
            )
        },
        "primary_outcome": "fdr_at_10pct",
        "cost_basis": (
            f"effective_prepaid_credits_usd / {HEADLINE_EVAL_BUGS} for Embedding, Jev, "
            "GPT-Nano; em dash for unpaid Random/BM25"
        ),
        "provenance": {
            "phase7_seal": verification.get("phase7_seal"),
            "phase8_seal": verification.get("phase8_seal"),
            "metrics_csv": verification.get("metrics_csv"),
            "statistics_json": verification.get("statistics_json"),
            "figure_data": verification.get("figure_data"),
            "cohort_summaries": "results/phase8/cohort_summaries.json",
            "cost_latency": "results/phase8/cost_latency.json",
        },
    }


def run_phase9_handoff(*, workspace: Path | None = None) -> dict[str, Any]:
    root = workspace or WORKSPACE
    verification = verify_handoff(workspace=root)
    out_dir = root / "results" / "phase9"
    out_dir.mkdir(parents=True, exist_ok=True)

    atomic_write_json(out_dir / "handoff_verification.json", verification)
    if not verification["ok"]:
        raise HandoffError(
            "handoff verification failed: " + "; ".join(verification["errors"][:8])
        )

    artifact = build_headline_artifact(workspace=root, verification=verification)
    md = render_report_headline(
        {
            "methods": artifact["methods"],
            "display_name": artifact["display_name"],
        },
        provenance=verification,
    )
    md_path = out_dir / "headline_table.md"
    json_path = out_dir / "headline_table.json"
    atomic_write_text(md_path, md)
    artifact["artifacts"] = {
        "headline_md": _hash_meta(md_path, workspace=root),
    }
    atomic_write_json(json_path, artifact)
    artifact["artifacts"]["headline_json"] = _hash_meta(json_path, workspace=root)
    # Persist sidecar hashes without nesting a changing self-hash of this file.
    sidecar = {
        "schema_version": "jev-phase9-headline-sidecar-v1",
        "created_at": artifact["created_at"],
        "headline_md": artifact["artifacts"]["headline_md"],
        "headline_json": _hash_meta(json_path, workspace=root),
    }
    atomic_write_json(out_dir / "headline_sidecar.json", sidecar)
    return {
        "ok": True,
        "verification": verification,
        "headline_md": str(md_path),
        "headline_json": str(json_path),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=None)
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        result = run_phase9_handoff(workspace=args.workspace)
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        "OK phase9_handoff "
        f"bugs={result['verification']['n_evaluation_bugs']} "
        f"rows={result['verification']['n_metrics_rows']} "
        f"headline={result['headline_md']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
