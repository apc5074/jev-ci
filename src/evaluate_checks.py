"""Focused integrity checks for offline ``evaluate.py`` (P8-08)."""

from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Any

from src.analysis_cohort import HEADLINE_EVAL_BUGS, HEADLINE_METRICS_ROWS
from src.example_contract import WORKSPACE, read_json
from src.metrics import apfd, budget_k, first_trigger_rank
from src.statistics import mcnemar_exact_two_sided


def run_evaluate_checks(*, workspace: Path | None = None) -> dict[str, Any]:
    root = workspace or WORKSPACE
    failures: list[str] = []
    passed: list[str] = []

    def ok(name: str) -> None:
        passed.append(name)

    def fail(name: str, msg: str) -> None:
        failures.append(f"{name}: {msg}")

    # Schema counts
    metrics_path = root / "results" / "metrics.csv"
    if not metrics_path.is_file():
        fail("metrics_csv", "missing results/metrics.csv")
    else:
        with metrics_path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        if len(rows) != HEADLINE_METRICS_ROWS:
            fail(
                "metrics_csv",
                f"expected {HEADLINE_METRICS_ROWS} rows, got {len(rows)}",
            )
        else:
            ok("metrics_csv_565")
        methods = {r["method"] for r in rows}
        if methods != {"Random", "BM25", "Embedding", "Jev", "GPT-Nano"}:
            fail("metrics_methods", f"unexpected methods {methods}")
        else:
            ok("metrics_methods")
        if any(r["split"] != "evaluation" for r in rows):
            fail("metrics_split", "non-evaluation rows present")
        else:
            ok("metrics_split")

    # Budget ceiling hand-check
    if budget_k(fraction=0.10, n=15) != 2:
        fail("budget_k", "ceil(0.10*15) should be 2")
    else:
        ok("budget_k_ceiling")

    # APFD limits
    if not math.isclose(apfd(r=1, n=10), 0.95):
        fail("apfd", "rank-1 N=10 APFD should be 0.95")
    else:
        ok("apfd_rank1")
    if not math.isclose(apfd(r=10, n=10), 0.05):
        fail("apfd", "rank-N APFD should be 1/(2N)")
    else:
        ok("apfd_rank_n")

    # Multiple triggers → minimum rank
    if first_trigger_rank(["a", "t2", "b", "t1"], ["t1", "t2"]) != 2:
        fail("multi_trigger", "expected min rank 2")
    else:
        ok("multi_trigger_min_rank")

    # McNemar zero discordance
    if mcnemar_exact_two_sided(b=0, c=0) != 1.0:
        fail("mcnemar_zero", "expected p=1")
    else:
        ok("mcnemar_zero_discordance")

    # Random aggregation present
    random_path = root / "results" / "phase8" / "random_metrics.json"
    if random_path.is_file():
        rnd = read_json(random_path)
        if rnd["counts"]["random_rows"] != HEADLINE_EVAL_BUGS:
            fail(
                "random_rows",
                f"expected {HEADLINE_EVAL_BUGS}, got {rnd['counts']['random_rows']}",
            )
        else:
            ok("random_113_rows")
        if "median_nftr" not in rnd["aggregates"]:
            fail("random_median_rule", "missing median NFTR")
        else:
            ok("random_median_nftr_present")
    else:
        fail("random_metrics", "missing random_metrics.json")

    # Statistics bootstrap config
    stats_path = root / "results" / "statistics.json"
    if stats_path.is_file():
        stats = read_json(stats_path)
        cfg = stats.get("configuration") or {}
        if cfg.get("bootstrap_samples") != 10000:
            fail("bootstrap_n", f"expected 10000, got {cfg.get('bootstrap_samples')}")
        else:
            ok("bootstrap_10000")
        if cfg.get("bootstrap_seed") != 20260922:
            fail("bootstrap_seed", f"expected 20260922, got {cfg.get('bootstrap_seed')}")
        else:
            ok("bootstrap_seed")
        table = stats["primary"]["paired_detection_fdr_at_10pct"]
        total = (
            table["both"]
            + table["jev_only"]
            + table["other_only"]
            + table["neither"]
        )
        if total != HEADLINE_EVAL_BUGS:
            fail("mcnemar_table", f"cells sum to {total}, not {HEADLINE_EVAL_BUGS}")
        else:
            ok("mcnemar_table_113")
    else:
        fail("statistics", "missing statistics.json")

    # Cohort denominators
    cohort_path = root / "results" / "phase8" / "cohort_summaries.json"
    if cohort_path.is_file():
        cohort = read_json(cohort_path)
        for method, block in cohort["cohort"].items():
            if block.get("denominator") != HEADLINE_EVAL_BUGS:
                fail(
                    "cohort_denom",
                    f"{method} denominator {block.get('denominator')}",
                )
                break
        else:
            ok("cohort_denom_113")
        recall = cohort["candidate_ceiling"]["recall"]
        if not (0.0 <= float(recall) <= 1.0):
            fail("candidate_recall", f"out of range {recall}")
        else:
            ok("candidate_recall_range")
    else:
        fail("cohort", "missing cohort_summaries.json")

    # Figures exist
    fig_dir = root / "results" / "phase8" / "figures"
    for name in (
        "figure1_budget_curve.svg",
        "figure2_nftr_cdf.svg",
        "figure3_project_fdr10.svg",
        "figure4_quality_vs_cost.svg",
    ):
        if not (fig_dir / name).is_file():
            fail("figures", f"missing {name}")
            break
    else:
        ok("figures_present")

    return {
        "ok": not failures,
        "n_checks": len(passed) + len(failures),
        "n_passed": len(passed),
        "n_failed": len(failures),
        "passed": passed,
        "failures": failures,
    }
