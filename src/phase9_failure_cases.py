"""P9-03: mechanically select the 20 qualitative-review cases."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

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
from src.seal_analysis import build_case20_deltas

SCHEMA = "jev-phase9-failure-cases-v1"
OUT_JSON = WORKSPACE / "results" / "failure_cases.json"
OUT_MD = WORKSPACE / "results" / "phase9" / "failure_cases.md"
PHASE8_CASE20 = WORKSPACE / "results" / "phase8" / "case20_deltas.json"
PER_BUG = WORKSPACE / "results" / "phase8" / "per_bug_metrics.json"
METRICS_CSV = WORKSPACE / "results" / "metrics.csv"


class FailureCasesError(Exception):
    """Phase 9 failure-case selection failed."""


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


def _delta_sign_label(delta: int) -> str:
    """Accurate label from signed delta (not from selection arm)."""
    if delta > 0:
        return "jev_gain"
    if delta < 0:
        return "jev_loss"
    return "tie"


def _annotate_arm(rows: list[dict[str, Any]], *, arm: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for rank_in_arm, row in enumerate(rows, start=1):
        delta = int(row["delta_bm25_minus_jev"])
        out.append(
            {
                "qualified_id": row["qualified_id"],
                "project": row["project"],
                "bug_id": str(row["bug_id"]),
                "bm25_first_trigger_rank": int(row["bm25_first_trigger_rank"]),
                "jev_first_trigger_rank": int(row["jev_first_trigger_rank"]),
                "delta_bm25_minus_jev": delta,
                "delta_sign_label": _delta_sign_label(delta),
                "candidate_trigger_in_top200": bool(
                    row["candidate_trigger_in_top200"]
                ),
                "selection_arm": arm,
                "rank_in_arm": rank_in_arm,
            }
        )
    return out


def select_failure_cases(*, workspace: Path | None = None) -> dict[str, Any]:
    """Rebuild the 20-case list from sealed per-bug metrics and publish it."""
    root = workspace or WORKSPACE
    per_bug_path = root / "results" / "phase8" / "per_bug_metrics.json"
    metrics_path = root / "results" / "metrics.csv"
    phase8_case20_path = root / "results" / "phase8" / "case20_deltas.json"

    if not per_bug_path.is_file():
        raise FailureCasesError(f"missing {per_bug_path}")
    if not metrics_path.is_file():
        raise FailureCasesError(f"missing {metrics_path}")

    case20 = build_case20_deltas(workspace=root)
    if int(case20["n_evaluation_bugs"]) != HEADLINE_EVAL_BUGS:
        raise FailureCasesError(
            f"expected n={HEADLINE_EVAL_BUGS}, got {case20['n_evaluation_bugs']}"
        )

    gains = _annotate_arm(list(case20["top10_jev_gains"]), arm="top10_jev_gains")
    losses = _annotate_arm(list(case20["top10_jev_losses"]), arm="top10_jev_losses")
    selected = gains + losses
    selected_ids = [c["qualified_id"] for c in selected]
    if selected_ids != list(case20["selected_ids"]):
        raise FailureCasesError("selected_ids mismatch vs build_case20_deltas")
    if len(set(selected_ids)) != 20:
        raise FailureCasesError(
            f"need 20 distinct IDs, got {len(set(selected_ids))}"
        )

    # Cross-check sealed Phase 8 artifact when present.
    if phase8_case20_path.is_file():
        sealed = read_json(phase8_case20_path)
        if list(sealed.get("selected_ids", [])) != selected_ids:
            raise FailureCasesError(
                "regenerated selected_ids disagree with "
                f"{_rel(phase8_case20_path, workspace=root)}"
            )

    n_positive = sum(1 for r in case20["all_deltas"] if r["delta_bm25_minus_jev"] > 0)
    n_negative = sum(1 for r in case20["all_deltas"] if r["delta_bm25_minus_jev"] < 0)
    n_zero = sum(1 for r in case20["all_deltas"] if r["delta_bm25_minus_jev"] == 0)

    gain_arm_true_gains = sum(1 for c in gains if c["delta_sign_label"] == "jev_gain")
    loss_arm_true_losses = sum(1 for c in losses if c["delta_sign_label"] == "jev_loss")

    doc: dict[str, Any] = {
        "schema_version": SCHEMA,
        "generated_at_utc": _utcnow(),
        "ok": True,
        "rule": case20["rule"],
        "cohort": cohort_metadata(),
        "n_evaluation_bugs": HEADLINE_EVAL_BUGS,
        "delta_sign_counts": {
            "positive_jev_earlier": n_positive,
            "negative_bm25_earlier": n_negative,
            "zero_tie": n_zero,
        },
        "selection_notes": {
            "gain_arm_strictly_positive": gain_arm_true_gains,
            "loss_arm_strictly_negative": loss_arm_true_losses,
            "note": (
                "selection_arm is mechanical (10 extremes each side). "
                "delta_sign_label reflects the signed delta; ties or "
                "opposite-sign rows in an arm are not called improvements "
                "or regressions they are not."
            ),
        },
        "input_hashes": {
            "per_bug_metrics": _hash_meta(per_bug_path, workspace=root),
            "metrics_csv": _hash_meta(metrics_path, workspace=root),
            "phase8_case20_deltas": (
                _hash_meta(phase8_case20_path, workspace=root)
                if phase8_case20_path.is_file()
                else None
            ),
        },
        "top10_jev_gains": gains,
        "top10_jev_losses": losses,
        "cases": selected,
        "selected_ids": selected_ids,
    }
    return doc


def render_failure_cases_md(doc: Mapping[str, Any]) -> str:
    lines = [
        "# Mechanically selected failure / gain cases (P9-03)",
        "",
        f"Headline cohort **n = {doc['n_evaluation_bugs']}**. "
        f"Rule: `{doc['rule']}`",
        "",
        "Selection is fixed before qualitative review (P9-04). "
        "Do not replace cases for narrative convenience.",
        "",
        "## Selected IDs (gains then losses)",
        "",
        ", ".join(f"`{qid}`" for qid in doc["selected_ids"]),
        "",
        "## Table",
        "",
        "| # | ID | Arm | BM25 r | Jev r | Δ (BM25−Jev) | Sign | Trigger∈top200 |",
        "| --- | --- | --- | ---: | ---: | ---: | --- | --- |",
    ]
    for i, case in enumerate(doc["cases"], start=1):
        lines.append(
            "| {i} | `{qid}` | {arm} | {bm25} | {jev} | {delta} | {sign} | {trig} |".format(
                i=i,
                qid=case["qualified_id"],
                arm=case["selection_arm"],
                bm25=case["bm25_first_trigger_rank"],
                jev=case["jev_first_trigger_rank"],
                delta=case["delta_bm25_minus_jev"],
                sign=case["delta_sign_label"],
                trig="yes" if case["candidate_trigger_in_top200"] else "no",
            )
        )
    lines.extend(
        [
            "",
            "## Delta sign census (full cohort)",
            "",
            f"- Positive (Jev earlier): {doc['delta_sign_counts']['positive_jev_earlier']}",
            f"- Negative (BM25 earlier): {doc['delta_sign_counts']['negative_bm25_earlier']}",
            f"- Zero: {doc['delta_sign_counts']['zero_tie']}",
            "",
            "## Provenance",
            "",
            f"- JSON: `results/failure_cases.json`",
            f"- per_bug_metrics sha256=`{doc['input_hashes']['per_bug_metrics']['sha256']}`",
            f"- metrics.csv sha256=`{doc['input_hashes']['metrics_csv']['sha256']}`",
            "",
        ]
    )
    return "\n".join(lines)


def publish_failure_cases(*, workspace: Path | None = None) -> dict[str, Any]:
    root = workspace or WORKSPACE
    doc = select_failure_cases(workspace=root)
    out_json = root / "results" / "failure_cases.json"
    out_md = root / "results" / "phase9" / "failure_cases.md"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(out_json, doc)
    atomic_write_text(out_md, render_failure_cases_md(doc))
    return doc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="P9-03: mechanically select 20 failure/gain cases"
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help="Repository root (default: checkout containing this package)",
    )
    args = parser.parse_args(argv)
    try:
        doc = publish_failure_cases(workspace=args.workspace)
    except FailureCasesError as exc:
        print(f"FAIL phase9_failure_cases: {exc}", file=sys.stderr)
        return 1
    print(
        "OK phase9_failure_cases "
        f"n={doc['n_evaluation_bugs']} selected={len(doc['selected_ids'])} "
        f"path=results/failure_cases.json"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
