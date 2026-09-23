"""Write metrics.csv, headline table, and figure data (P8-07).

Consumes sealed Phase 8 artifacts only — no provider calls. ``statistics.json``
is produced by P8-06; this module refreshes display outputs and the 625-row CSV.
"""

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

from src.cohort_summaries import (
    index_nonrandom_records,
    materialize_jev_record,
)
from src.example_contract import (
    WORKSPACE,
    ExampleId,
    atomic_write_json,
    atomic_write_text,
    read_json,
    sha256_file,
)

METRICS_CSV = WORKSPACE / "results" / "metrics.csv"
METRICS_SIDECAR = WORKSPACE / "results" / "phase8" / "metrics_csv_sidecar.json"
HEADLINE_MD = WORKSPACE / "results" / "phase8" / "headline_table.md"
FIGURE_DATA = WORKSPACE / "results" / "phase8" / "figure_data.json"
FIGURES_DIR = WORKSPACE / "results" / "phase8" / "figures"

METHODS = ("Random", "BM25", "Embedding", "Jev", "GPT-Nano")
CSV_COLUMNS = [
    "project",
    "bug_id",
    "split",
    "method",
    "num_test_classes",
    "num_trigger_classes",
    "first_trigger_rank",
    "normalized_first_trigger_rank",
    "detected_at_1pct",
    "detected_at_2pct",
    "detected_at_5pct",
    "detected_at_10pct",
    "detected_at_20pct",
    "detected_at_50pct",
    "detected_at_100pct",
    "reciprocal_rank",
    "apfd",
    "candidate_trigger_in_top200",
    "reranker_input_tokens",
    "reranker_output_tokens",
    "reranker_cost_usd",
    "reranker_wall_ms",
    "patch_truncated",
    "missing_test_source_count",
    "qualified_id",
    "experiment_commit",
    "run_id",
    "available",
]


class ReportError(Exception):
    """Report output generation failed."""


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


def _load_bug_meta(workspace: Path, example: ExampleId) -> dict[str, Any]:
    ranking = read_json(workspace / "results" / "rankings" / f"{example.slug}.json")
    patch_meta = read_json(
        workspace / "data" / "patches" / example.slug / "patch_meta.json"
    )
    return {
        "missing_test_source_count": int(ranking.get("source_missing_count") or 0),
        "patch_truncated": bool(patch_meta.get("patch_truncated")),
    }


def _cost_fields(
    *,
    method: str,
    qid: str,
    cost_doc: Mapping[str, Any],
) -> dict[str, Any]:
    if method in {"Random", "BM25"}:
        return {
            "reranker_input_tokens": "",
            "reranker_output_tokens": "",
            "reranker_cost_usd": 0.0,
            "reranker_wall_ms": "",
        }
    block = cost_doc["methods"][method]
    per_bug = block["cost"].get("per_bug") or {}
    row = per_bug.get(qid)
    wall_map = (
        ((block.get("latency") or {}).get("shortlist_wall_ms") or {}).get("per_bug")
        or {}
    )
    if row is None:
        return {
            "reranker_input_tokens": "",
            "reranker_output_tokens": "",
            "reranker_cost_usd": "",
            "reranker_wall_ms": wall_map.get(qid, ""),
        }
    return {
        "reranker_input_tokens": row.get("input_tokens"),
        "reranker_output_tokens": row.get("output_tokens"),
        "reranker_cost_usd": row.get("effective_prepaid_credits_usd"),
        "reranker_wall_ms": wall_map.get(qid, ""),
    }


def build_metrics_rows(
    *,
    workspace: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    per_bug = read_json(workspace / "results" / "phase8" / "per_bug_metrics.json")
    random_doc = read_json(workspace / "results" / "phase8" / "random_metrics.json")
    cost_doc = read_json(workspace / "results" / "phase8" / "cost_latency.json")
    seal = read_json(workspace / "results" / "phase7" / "raw_evaluation_seal.json")
    commit = seal["experiment_commit"]
    run_id = seal["run_id"]

    by_bug = index_nonrandom_records(per_bug["records"])
    random_by = {r["qualified_id"]: r for r in random_doc["records"]}
    ordered = sorted(
        by_bug.keys(),
        key=lambda x: (x.split("-")[0], int(x.split("-")[1])),
    )
    if len(ordered) != 125:
        raise ReportError(f"expected 125 bugs, got {len(ordered)}")

    meta_cache: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    for qid in ordered:
        ex = ExampleId.parse(qid)
        if qid not in meta_cache:
            meta_cache[qid] = _load_bug_meta(workspace, ex)
        meta = meta_cache[qid]
        method_recs: dict[str, Mapping[str, Any]] = {
            "Random": random_by[qid],
            "BM25": by_bug[qid]["BM25"],
            "Embedding": by_bug[qid]["Embedding"],
            "Jev": materialize_jev_record(by_bug[qid]["Jev"]),
            "GPT-Nano": by_bug[qid]["GPT-Nano"],
        }
        for method in METHODS:
            rec = method_recs[method]
            costs = _cost_fields(method=method, qid=qid, cost_doc=cost_doc)
            row = {
                "project": rec["project"] if "project" in rec else ex.project,
                "bug_id": rec["bug_id"] if "bug_id" in rec else ex.bug_id,
                "split": "evaluation",
                "method": method,
                "num_test_classes": rec["num_test_classes"],
                "num_trigger_classes": rec["num_trigger_classes"],
                "first_trigger_rank": rec["first_trigger_rank"],
                "normalized_first_trigger_rank": rec["normalized_first_trigger_rank"],
                "detected_at_1pct": rec["detected_at_1pct"],
                "detected_at_2pct": rec["detected_at_2pct"],
                "detected_at_5pct": rec["detected_at_5pct"],
                "detected_at_10pct": rec["detected_at_10pct"],
                "detected_at_20pct": rec["detected_at_20pct"],
                "detected_at_50pct": rec["detected_at_50pct"],
                "detected_at_100pct": rec.get("detected_at_100pct"),
                "reciprocal_rank": rec["reciprocal_rank"],
                "apfd": rec["apfd"],
                "candidate_trigger_in_top200": rec["candidate_trigger_in_top200"],
                **costs,
                "patch_truncated": meta["patch_truncated"],
                "missing_test_source_count": meta["missing_test_source_count"],
                "qualified_id": qid,
                "experiment_commit": commit,
                "run_id": run_id,
                "available": rec.get("available", True),
            }
            rows.append(row)

    if len(rows) != 625:
        raise ReportError(f"expected 625 rows, got {len(rows)}")
    provenance = {
        "experiment_commit": commit,
        "run_id": run_id,
        "n_rows": len(rows),
        "methods": list(METHODS),
    }
    return rows, provenance


def write_metrics_csv(
    rows: Sequence[Mapping[str, Any]],
    *,
    path: Path,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=CSV_COLUMNS,
                extrasaction="ignore",
                lineterminator="\n",
            )
            writer.writeheader()
            for row in rows:
                out = {}
                for col in CSV_COLUMNS:
                    val = row.get(col)
                    if isinstance(val, bool):
                        out[col] = "true" if val else "false"
                    elif val is None:
                        out[col] = ""
                    else:
                        out[col] = val
                writer.writerow(out)
        tmp.replace(path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def build_headline_table(
    *,
    workspace: Path,
) -> dict[str, Any]:
    cohort = read_json(workspace / "results" / "phase8" / "cohort_summaries.json")
    methods = {}
    for method in METHODS:
        block = cohort["cohort"][method]
        methods[method] = {
            "fdr_at_5pct": float(block["fdr_at_5pct"]),
            "fdr_at_10pct": float(block["primary_fdr_at_10pct"]),
            "fdr_at_20pct": float(block["fdr_at_20pct"]),
            "mrr": float(block["mrr"]),
            "apfd": float(block["mean_apfd"]),
            "median_nftr": float(block["median_nftr"]),
            "cost_usd_per_bug": block.get("cost_usd_per_bug"),
        }
    quality_cols = [
        "fdr_at_5pct",
        "fdr_at_10pct",
        "fdr_at_20pct",
        "mrr",
        "apfd",
    ]
    # Higher is better for quality_cols; lower is better for median_nftr.
    best: dict[str, str] = {}
    for col in quality_cols:
        best[col] = max(METHODS, key=lambda m: methods[m][col])
    best["median_nftr"] = min(METHODS, key=lambda m: methods[m]["median_nftr"])
    return {
        "methods": methods,
        "best_quality": best,
        "display_name": {
            "Random": "Random",
            "BM25": "BM25",
            "Embedding": "Embedding",
            "Jev": "Jev",
            "GPT-Nano": "GPT-5.4 nano",
        },
    }


def render_headline_markdown(table: Mapping[str, Any]) -> str:
    best = table["best_quality"]
    names = table["display_name"]
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
        "# Headline results (evaluation, n=125)",
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
                    cells.append(_fmt_usd(table["methods"][method][key]))
                continue
            val = table["methods"][method][key]
            text = _fmt_rate(val)
            if best.get(key) == method:
                text = f"**{text}**"
            cells.append(text)
        lines.append("| " + " | ".join(cells) + " |")
    lines.extend(
        [
            "",
            "Bold marks the numerically best quality value in each column "
            "(highest FDR/MRR/APFD; lowest median NFTR). Cost is not bolded.",
            "",
        ]
    )
    return "\n".join(lines)


def _empirical_cdf(values: Sequence[float]) -> list[dict[str, float]]:
    ordered = sorted(float(v) for v in values)
    n = len(ordered)
    points: list[dict[str, float]] = []
    for i, v in enumerate(ordered, start=1):
        points.append({"nftr": v, "fraction_bugs": i / float(n)})
    return points


def build_figure_data(*, workspace: Path) -> dict[str, Any]:
    cohort = read_json(workspace / "results" / "phase8" / "cohort_summaries.json")
    random_doc = read_json(workspace / "results" / "phase8" / "random_metrics.json")
    per_bug = read_json(workspace / "results" / "phase8" / "per_bug_metrics.json")
    by_bug = index_nonrandom_records(per_bug["records"])

    budgets = [0.01, 0.02, 0.05, 0.10, 0.20, 0.50, 1.00]
    labels = ["1pct", "2pct", "5pct", "10pct", "20pct", "50pct", "100pct"]
    budget_curve = {}
    for method in METHODS:
        block = cohort["cohort"][method]
        budget_curve[method] = [
            {
                "budget_fraction": frac,
                "fdr": float(block[f"fdr_at_{lab}"]),
            }
            for frac, lab in zip(budgets, labels, strict=True)
        ]

    # NFTR CDF
    nftr_cdf: dict[str, Any] = {
        "Random": random_doc["cdf"],
    }
    for method in ("BM25", "Embedding", "Jev", "GPT-Nano"):
        vals = []
        for qid, recs in by_bug.items():
            row = (
                materialize_jev_record(recs[method])
                if method == "Jev"
                else recs[method]
            )
            vals.append(float(row["normalized_first_trigger_rank"]))
        nftr_cdf[method] = _empirical_cdf(vals)

    project_fdr = {
        project: {
            method: float(block["methods"][method]["primary_fdr_at_10pct"])
            for method in METHODS
        }
        for project, block in cohort["projects"].items()
    }

    quality_cost = []
    for method in ("Embedding", "Jev", "GPT-Nano"):
        quality_cost.append(
            {
                "method": method,
                "fdr_at_10pct": float(
                    cohort["cohort"][method]["primary_fdr_at_10pct"]
                ),
                "cost_usd_per_bug": float(
                    cohort["cohort"][method]["cost_usd_per_bug"]
                ),
            }
        )

    return {
        "schema_version": "jev-phase8-figure-data-v1",
        "created_at": (
            str(
                read_json(
                    workspace / "results" / "phase7" / "raw_evaluation_seal.json"
                ).get("sealed_at")
            )
            if (workspace / "results" / "phase7" / "raw_evaluation_seal.json").is_file()
            else _utcnow()
        ),
        "figure1_budget_curve": budget_curve,
        "figure2_nftr_cdf": nftr_cdf,
        "figure3_project_fdr10": project_fdr,
        "figure4_quality_vs_cost": quality_cost,
        "notes": [
            "Phase 9 may refine layout/captions; numeric content is frozen here",
            "Random NFTR CDF uses P8-03 replicate-averaged grid",
        ],
    }


# --- Professional SVG charting (no external deps; deterministic) ---

METHOD_COLORS: dict[str, str] = {
    "Random": "#64748B",
    "BM25": "#2563EB",
    "Embedding": "#059669",
    "Jev": "#DC2626",
    "GPT-Nano": "#7C3AED",
}
METHOD_DISPLAY: dict[str, str] = {
    "Random": "Random",
    "BM25": "BM25",
    "Embedding": "Embedding",
    "Jev": "Jev",
    "GPT-Nano": "GPT-5.4 nano",
}
_FONT = "ui-sans-serif,system-ui,Helvetica Neue,Helvetica,Arial,sans-serif"
_INK = "#0F172A"
_MUTED = "#64748B"
_GRID = "#E2E8F0"
_AXIS = "#94A3B8"


def _esc(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _fmt_pct(value: float, *, digits: int = 1) -> str:
    return f"{100.0 * value:.{digits}f}%"


def _fmt_fdr(value: float) -> str:
    return f"{value:.3f}"


def _nice_ticks(lo: float, hi: float, n: int = 6) -> list[float]:
    if hi <= lo:
        return [lo]
    span = hi - lo
    step = span / max(1, n - 1)
    # Snap common 0–1 axes to tenths.
    if lo == 0.0 and 0.9 <= hi <= 1.0 + 1e-12:
        return [i / 10 for i in range(0, 11, 2)]
    return [lo + i * step for i in range(n)]


def _svg_open(width: int, height: int) -> list[str]:
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        f'<rect width="100%" height="100%" fill="#FFFFFF"/>',
    ]


def _text(
    x: float,
    y: float,
    text: str,
    *,
    size: int = 12,
    anchor: str = "start",
    weight: str = "400",
    fill: str = _INK,
    dy: str | None = None,
) -> str:
    attrs = (
        f'x="{x:.2f}" y="{y:.2f}" text-anchor="{anchor}" '
        f'font-family="{_FONT}" font-size="{size}" font-weight="{weight}" '
        f'fill="{fill}"'
    )
    if dy:
        attrs += f' dy="{dy}"'
    return f"<text {attrs}>{_esc(text)}</text>"


def _legend_panel(
    *,
    x: float,
    y: float,
    entries: Sequence[tuple[str, str, str | None]],
    swatch: str = "line",
    box_w: float = 188,
) -> list[str]:
    """Right-side legend. entries: (label, color, optional metric suffix)."""
    parts: list[str] = []
    row_h = 22
    pad = 12
    header = 18
    box_h = pad + header + len(entries) * row_h + pad - 4
    parts.append(
        f'<rect x="{x:.2f}" y="{y:.2f}" width="{box_w}" height="{box_h}" '
        f'rx="6" fill="#F8FAFC" stroke="{_GRID}"/>'
    )
    parts.append(
        _text(x + pad, y + pad + 2, "Method", size=10, weight="600", fill=_MUTED)
    )
    for i, (label, color, metric) in enumerate(entries):
        cy = y + pad + header + i * row_h
        if swatch == "line":
            parts.append(
                f'<line x1="{x + pad:.2f}" y1="{cy:.2f}" '
                f'x2="{x + pad + 22:.2f}" y2="{cy:.2f}" '
                f'stroke="{color}" stroke-width="2.5" stroke-linecap="round"/>'
            )
            parts.append(
                f'<circle cx="{x + pad + 11:.2f}" cy="{cy:.2f}" r="3.2" '
                f'fill="#FFFFFF" stroke="{color}" stroke-width="2"/>'
            )
        else:
            parts.append(
                f'<rect x="{x + pad:.2f}" y="{cy - 6:.2f}" width="14" height="12" '
                f'rx="2" fill="{color}"/>'
            )
        parts.append(_text(x + pad + 30, cy + 4, label, size=12, weight="500"))
        if metric:
            parts.append(
                _text(
                    x + box_w - pad,
                    cy + 4,
                    metric,
                    size=11,
                    anchor="end",
                    fill=_MUTED,
                )
            )
    return parts


def _axes_frame(
    *,
    pad_l: float,
    pad_t: float,
    plot_w: float,
    plot_h: float,
    x_ticks: Sequence[tuple[float, str]],
    y_ticks: Sequence[tuple[float, str]],
    xmin: float,
    xmax: float,
    ymin: float,
    ymax: float,
) -> tuple[list[str], Any, Any]:
    """Grid + spines + tick labels. Returns (parts, sx, sy)."""

    def sx(x: float) -> float:
        if xmax == xmin:
            return pad_l + plot_w / 2
        return pad_l + (x - xmin) / (xmax - xmin) * plot_w

    def sy(y: float) -> float:
        if ymax == ymin:
            return pad_t + plot_h / 2
        return pad_t + (1.0 - (y - ymin) / (ymax - ymin)) * plot_h

    parts: list[str] = [
        f'<rect x="{pad_l:.2f}" y="{pad_t:.2f}" width="{plot_w:.2f}" '
        f'height="{plot_h:.2f}" fill="#FFFFFF" stroke="{_AXIS}" stroke-width="1"/>'
    ]
    for y, label in y_ticks:
        yy = sy(y)
        parts.append(
            f'<line x1="{pad_l:.2f}" y1="{yy:.2f}" x2="{pad_l + plot_w:.2f}" '
            f'y2="{yy:.2f}" stroke="{_GRID}" stroke-width="1"/>'
        )
        parts.append(
            f'<line x1="{pad_l - 5:.2f}" y1="{yy:.2f}" x2="{pad_l:.2f}" '
            f'y2="{yy:.2f}" stroke="{_AXIS}" stroke-width="1"/>'
        )
        parts.append(
            _text(pad_l - 8, yy + 4, label, size=11, anchor="end", fill=_MUTED)
        )
    for x, label in x_ticks:
        xx = sx(x)
        parts.append(
            f'<line x1="{xx:.2f}" y1="{pad_t:.2f}" x2="{xx:.2f}" '
            f'y2="{pad_t + plot_h:.2f}" stroke="{_GRID}" stroke-width="1"/>'
        )
        parts.append(
            f'<line x1="{xx:.2f}" y1="{pad_t + plot_h:.2f}" x2="{xx:.2f}" '
            f'y2="{pad_t + plot_h + 5:.2f}" stroke="{_AXIS}" stroke-width="1"/>'
        )
        parts.append(
            _text(
                xx,
                pad_t + plot_h + 18,
                label,
                size=11,
                anchor="middle",
                fill=_MUTED,
            )
        )
    return parts, sx, sy


def _svg_budget_curve(figure_data: Mapping[str, Any]) -> str:
    """Equal-spaced budget categories so 1%–10% remain readable."""
    width, height = 960, 560
    pad_l, pad_r, pad_t, pad_b = 72, 210, 72, 64
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    budgets = [0.01, 0.02, 0.05, 0.10, 0.20, 0.50, 1.00]
    labels = ["1%", "2%", "5%", "10%", "20%", "50%", "100%"]
    idx_of = {b: i for i, b in enumerate(budgets)}
    xmin, xmax, ymin, ymax = 0.0, float(len(budgets) - 1), 0.0, 1.0
    x_ticks = [(float(i), lab) for i, lab in enumerate(labels)]
    y_ticks = [(v, f"{v:.1f}") for v in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)]

    parts = _svg_open(width, height)
    parts.append(
        _text(
            width / 2,
            28,
            "Fault detection vs test-class budget",
            size=18,
            anchor="middle",
            weight="700",
        )
    )
    parts.append(
        _text(
            width / 2,
            48,
            "Evaluation set · n = 125 bugs · primary outcome FDR@10%",
            size=12,
            anchor="middle",
            fill=_MUTED,
        )
    )
    frame, sx, sy = _axes_frame(
        pad_l=pad_l,
        pad_t=pad_t,
        plot_w=plot_w,
        plot_h=plot_h,
        x_ticks=x_ticks,
        y_ticks=y_ticks,
        xmin=xmin,
        xmax=xmax,
        ymin=ymin,
        ymax=ymax,
    )
    parts.extend(frame)

    # Primary budget marker at 10% (index 3)
    x10 = sx(float(idx_of[0.10]))
    parts.append(
        f'<line x1="{x10:.2f}" y1="{pad_t:.2f}" x2="{x10:.2f}" '
        f'y2="{pad_t + plot_h:.2f}" stroke="#F59E0B" stroke-width="1.5" '
        f'stroke-dasharray="5 4"/>'
    )
    parts.append(
        _text(
            x10 + 6,
            pad_t + 14,
            "primary",
            size=10,
            weight="600",
            fill="#B45309",
        )
    )

    legend_entries: list[tuple[str, str, str | None]] = []
    for method in METHODS:
        pts = figure_data["figure1_budget_curve"][method]
        xy = []
        for p in pts:
            frac = float(p["budget_fraction"])
            # Match preregistered budget grid (float equality on 0.01…1.00)
            matched = min(budgets, key=lambda b: abs(b - frac))
            xy.append((float(idx_of[matched]), float(p["fdr"])))
        color = METHOD_COLORS[method]
        d = "M " + " L ".join(f"{sx(x):.2f} {sy(y):.2f}" for x, y in xy)
        width_stroke = 3.0 if method == "Jev" else 2.25
        parts.append(
            f'<path d="{d}" fill="none" stroke="{color}" '
            f'stroke-width="{width_stroke}" stroke-linejoin="round" '
            f'stroke-linecap="round"/>'
        )
        for x, y in xy:
            parts.append(
                f'<circle cx="{sx(x):.2f}" cy="{sy(y):.2f}" r="4.2" '
                f'fill="#FFFFFF" stroke="{color}" stroke-width="2"/>'
            )
        fdr10 = next(
            float(p["fdr"])
            for p in pts
            if abs(float(p["budget_fraction"]) - 0.1) < 1e-12
        )
        legend_entries.append((METHOD_DISPLAY[method], color, _fmt_pct(fdr10)))

    parts.append(
        _text(
            pad_l + plot_w / 2,
            height - 18,
            "Percent of test classes executed",
            size=13,
            anchor="middle",
            weight="500",
        )
    )
    parts.append(
        f'<text x="22" y="{pad_t + plot_h / 2:.2f}" text-anchor="middle" '
        f'transform="rotate(-90 22 {pad_t + plot_h / 2:.2f})" '
        f'font-family="{_FONT}" font-size="13" font-weight="500" fill="{_INK}">'
        f"Fraction of regressions detected</text>"
    )
    parts.extend(
        _legend_panel(
            x=width - pad_r + 14,
            y=pad_t,
            entries=legend_entries,
            swatch="line",
        )
    )
    parts.append(
        _text(
            width - pad_r + 14,
            pad_t + 18 + 22 * len(legend_entries) + 28,
            "Legend values = FDR@10%",
            size=10,
            fill=_MUTED,
        )
    )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def _svg_nftr_cdf(figure_data: Mapping[str, Any]) -> str:
    width, height = 960, 560
    pad_l, pad_r, pad_t, pad_b = 72, 190, 72, 64
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    xmin, xmax, ymin, ymax = 0.0, 1.0, 0.0, 1.0
    x_ticks = [(v, f"{v:.1f}") for v in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)]
    y_ticks = [(v, f"{v:.1f}") for v in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)]

    parts = _svg_open(width, height)
    parts.append(
        _text(
            width / 2,
            28,
            "Normalized first-trigger rank CDF",
            size=18,
            anchor="middle",
            weight="700",
        )
    )
    parts.append(
        _text(
            width / 2,
            48,
            "Earlier detection = curve rises sooner (left). Random uses 1,000-permutation mean.",
            size=12,
            anchor="middle",
            fill=_MUTED,
        )
    )
    frame, sx, sy = _axes_frame(
        pad_l=pad_l,
        pad_t=pad_t,
        plot_w=plot_w,
        plot_h=plot_h,
        x_ticks=x_ticks,
        y_ticks=y_ticks,
        xmin=xmin,
        xmax=xmax,
        ymin=ymin,
        ymax=ymax,
    )
    parts.extend(frame)

    legend_entries: list[tuple[str, str, str | None]] = []
    for method in METHODS:
        pts = figure_data["figure2_nftr_cdf"][method]
        xy = [(float(p["nftr"]), float(p["fraction_bugs"])) for p in pts]
        color = METHOD_COLORS[method]
        d = "M " + " L ".join(f"{sx(x):.2f} {sy(y):.2f}" for x, y in xy)
        width_stroke = 3.0 if method == "Jev" else 2.0
        parts.append(
            f'<path d="{d}" fill="none" stroke="{color}" '
            f'stroke-width="{width_stroke}" stroke-linejoin="round"/>'
        )
        # Median NFTR ≈ where CDF crosses 0.5
        median = None
        for i in range(1, len(xy)):
            if xy[i - 1][1] <= 0.5 <= xy[i][1]:
                x0, y0 = xy[i - 1]
                x1, y1 = xy[i]
                if abs(y1 - y0) < 1e-12:
                    median = x1
                else:
                    t = (0.5 - y0) / (y1 - y0)
                    median = x0 + t * (x1 - x0)
                break
        metric = f"med≈{median:.3f}" if median is not None else None
        legend_entries.append((METHOD_DISPLAY[method], color, metric))

    parts.append(
        _text(
            pad_l + plot_w / 2,
            height - 18,
            "Normalized first-trigger rank (r / N) → later",
            size=13,
            anchor="middle",
            weight="500",
        )
    )
    parts.append(
        f'<text x="22" y="{pad_t + plot_h / 2:.2f}" text-anchor="middle" '
        f'transform="rotate(-90 22 {pad_t + plot_h / 2:.2f})" '
        f'font-family="{_FONT}" font-size="13" font-weight="500" fill="{_INK}">'
        f"Fraction of bugs detected</text>"
    )
    parts.extend(
        _legend_panel(
            x=width - pad_r + 12,
            y=pad_t,
            entries=legend_entries,
            swatch="line",
        )
    )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def _svg_project_bars(figure_data: Mapping[str, Any]) -> str:
    width, height = 960, 560
    pad_l, pad_r, pad_t, pad_b = 72, 190, 72, 72
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    projects = list(figure_data["figure3_project_fdr10"].keys())
    short = {
        "Cli": "Cli",
        "Lang": "Lang",
        "Math": "Math",
        "Jsoup": "Jsoup",
        "JacksonDatabind": "Jackson",
    }
    n_proj = len(projects)
    n_methods = len(METHODS)
    group_w = plot_w / n_proj
    bar_gap = 3.0
    bar_w = (group_w * 0.72 - bar_gap * (n_methods - 1)) / n_methods
    ymin, ymax = 0.0, 1.0
    y_ticks = [(v, f"{v:.1f}") for v in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)]

    parts = _svg_open(width, height)
    parts.append(
        _text(
            width / 2,
            28,
            "FDR@10% by project",
            size=18,
            anchor="middle",
            weight="700",
        )
    )
    parts.append(
        _text(
            width / 2,
            48,
            "Descriptive subsets · 25 evaluation bugs per project · not for significance claims",
            size=12,
            anchor="middle",
            fill=_MUTED,
        )
    )

    # Frame + y grid (x is categorical)
    parts.append(
        f'<rect x="{pad_l:.2f}" y="{pad_t:.2f}" width="{plot_w:.2f}" '
        f'height="{plot_h:.2f}" fill="#FFFFFF" stroke="{_AXIS}" stroke-width="1"/>'
    )

    def sy(y: float) -> float:
        return pad_t + (1.0 - (y - ymin) / (ymax - ymin)) * plot_h

    for y, label in y_ticks:
        yy = sy(y)
        parts.append(
            f'<line x1="{pad_l:.2f}" y1="{yy:.2f}" x2="{pad_l + plot_w:.2f}" '
            f'y2="{yy:.2f}" stroke="{_GRID}" stroke-width="1"/>'
        )
        parts.append(
            _text(pad_l - 8, yy + 4, label, size=11, anchor="end", fill=_MUTED)
        )

    for i, project in enumerate(projects):
        gx = pad_l + i * group_w + group_w * 0.14
        for j, method in enumerate(METHODS):
            val = float(figure_data["figure3_project_fdr10"][project][method])
            bx = gx + j * (bar_w + bar_gap)
            by = sy(val)
            bh = sy(0.0) - by
            color = METHOD_COLORS[method]
            parts.append(
                f'<rect x="{bx:.2f}" y="{by:.2f}" width="{bar_w:.2f}" '
                f'height="{bh:.2f}" fill="{color}" rx="1.5"/>'
            )
            # Value labels: inside bar when near the top to avoid clipping
            if val >= 0.35:
                label_y = by + 12 if val >= 0.92 else by - 4
                label_fill = "#FFFFFF" if val >= 0.92 else _MUTED
                parts.append(
                    _text(
                        bx + bar_w / 2,
                        label_y,
                        f"{val:.2f}",
                        size=9,
                        anchor="middle",
                        weight="600" if val >= 0.92 else "400",
                        fill=label_fill,
                    )
                )
        parts.append(
            _text(
                pad_l + i * group_w + group_w / 2,
                pad_t + plot_h + 22,
                short.get(project, project),
                size=12,
                anchor="middle",
                weight="600",
            )
        )
        parts.append(
            _text(
                pad_l + i * group_w + group_w / 2,
                pad_t + plot_h + 38,
                "n=25",
                size=10,
                anchor="middle",
                fill=_MUTED,
            )
        )

    parts.append(
        f'<text x="22" y="{pad_t + plot_h / 2:.2f}" text-anchor="middle" '
        f'transform="rotate(-90 22 {pad_t + plot_h / 2:.2f})" '
        f'font-family="{_FONT}" font-size="13" font-weight="500" fill="{_INK}">'
        f"FDR@10%</text>"
    )
    parts.extend(
        _legend_panel(
            x=width - pad_r + 12,
            y=pad_t,
            entries=[
                (METHOD_DISPLAY[m], METHOD_COLORS[m], None) for m in METHODS
            ],
            swatch="box",
        )
    )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def _svg_quality_cost(figure_data: Mapping[str, Any]) -> str:
    width, height = 960, 560
    pad_l, pad_r, pad_t, pad_b = 72, 48, 72, 72
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    rows = list(figure_data["figure4_quality_vs_cost"])
    costs = [float(r["cost_usd_per_bug"]) for r in rows]
    fdrs = [float(r["fdr_at_10pct"]) for r in rows]
    xmin = 0.0
    xmax = max(costs) * 1.18
    ymin = 0.80
    ymax = 1.0
    x_ticks = [
        (0.0, "$0"),
        (0.01, "$0.01"),
        (0.02, "$0.02"),
        (0.03, "$0.03"),
        (0.04, "$0.04"),
        (0.05, "$0.05"),
    ]
    x_ticks = [(x, lab) for x, lab in x_ticks if x <= xmax]
    y_ticks = [(v, f"{v:.2f}") for v in (0.80, 0.85, 0.90, 0.95, 1.00)]

    parts = _svg_open(width, height)
    parts.append(
        _text(
            width / 2,
            28,
            "Detection quality versus reranking cost",
            size=18,
            anchor="middle",
            weight="700",
        )
    )
    parts.append(
        _text(
            width / 2,
            48,
            "Mean effective prepaid credits per bug · Embedding / Jev / GPT-5.4 nano",
            size=12,
            anchor="middle",
            fill=_MUTED,
        )
    )
    frame, sx, sy = _axes_frame(
        pad_l=pad_l,
        pad_t=pad_t,
        plot_w=plot_w,
        plot_h=plot_h,
        x_ticks=x_ticks,
        y_ticks=y_ticks,
        xmin=xmin,
        xmax=xmax,
        ymin=ymin,
        ymax=ymax,
    )
    parts.extend(frame)

    # Soft connector in cost order (visual guide only)
    ordered = sorted(rows, key=lambda r: float(r["cost_usd_per_bug"]))
    if len(ordered) >= 2:
        d = "M " + " L ".join(
            f"{sx(float(r['cost_usd_per_bug'])):.2f} "
            f"{sy(float(r['fdr_at_10pct'])):.2f}"
            for r in ordered
        )
        parts.append(
            f'<path d="{d}" fill="none" stroke="{_GRID}" stroke-width="2" '
            f'stroke-dasharray="6 5"/>'
        )

    # Label offsets: keep all copy inside the plot
    label_offset = {
        "Embedding": (14, -18, "start"),
        "Jev": (14, 28, "start"),
        "GPT-Nano": (-14, -18, "end"),
    }
    for row in rows:
        method = str(row["method"])
        cost = float(row["cost_usd_per_bug"])
        fdr = float(row["fdr_at_10pct"])
        color = METHOD_COLORS[method]
        cx, cy = sx(cost), sy(fdr)
        parts.append(
            f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="9" fill="{color}" '
            f'stroke="#FFFFFF" stroke-width="2.5"/>'
        )
        dx, dy, anchor = label_offset.get(method, (10, -12, "start"))
        parts.append(
            _text(
                cx + dx,
                cy + dy,
                METHOD_DISPLAY[method],
                size=13,
                anchor=str(anchor),
                weight="700",
                fill=color,
            )
        )
        parts.append(
            _text(
                cx + dx,
                cy + dy + 14,
                f"FDR@10% {_fmt_fdr(fdr)} · ${_fmt_usd(cost)}/bug",
                size=11,
                anchor=str(anchor),
                fill=_MUTED,
            )
        )

    parts.append(
        _text(
            pad_l + plot_w / 2,
            height - 18,
            "Mean reranking cost per bug (USD, frozen Phase 6 price snapshot)",
            size=13,
            anchor="middle",
            weight="500",
        )
    )
    parts.append(
        f'<text x="22" y="{pad_t + plot_h / 2:.2f}" text-anchor="middle" '
        f'transform="rotate(-90 22 {pad_t + plot_h / 2:.2f})" '
        f'font-family="{_FONT}" font-size="13" font-weight="500" fill="{_INK}">'
        f"FDR@10%</text>"
    )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def write_figure_svgs(
    figure_data: Mapping[str, Any],
    *,
    out_dir: Path,
    workspace: Path,
) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}

    p1 = out_dir / "figure1_budget_curve.svg"
    atomic_write_text(p1, _svg_budget_curve(figure_data))
    paths["figure1"] = _rel(p1, workspace=workspace)

    p2 = out_dir / "figure2_nftr_cdf.svg"
    atomic_write_text(p2, _svg_nftr_cdf(figure_data))
    paths["figure2"] = _rel(p2, workspace=workspace)

    p3 = out_dir / "figure3_project_fdr10.svg"
    atomic_write_text(p3, _svg_project_bars(figure_data))
    paths["figure3"] = _rel(p3, workspace=workspace)

    p4 = out_dir / "figure4_quality_vs_cost.svg"
    atomic_write_text(p4, _svg_quality_cost(figure_data))
    paths["figure4"] = _rel(p4, workspace=workspace)
    return paths


def run_report_outputs(
    *,
    workspace: Path | None = None,
) -> dict[str, Any]:
    root = workspace or WORKSPACE
    rows, provenance = build_metrics_rows(workspace=root)
    write_metrics_csv(rows, path=root / "results" / "metrics.csv")
    metrics_path = root / "results" / "metrics.csv"
    metrics_sha = sha256_file(metrics_path)

    table = build_headline_table(workspace=root)
    headline_md = render_headline_markdown(table)
    headline_path = root / "results" / "phase8" / "headline_table.md"
    atomic_write_text(headline_path, headline_md)

    fig_data = build_figure_data(workspace=root)
    fig_data_path = root / "results" / "phase8" / "figure_data.json"
    atomic_write_json(fig_data_path, fig_data)
    fig_paths = write_figure_svgs(
        fig_data,
        out_dir=root / "results" / "phase8" / "figures",
        workspace=root,
    )

    stats_path = root / "results" / "statistics.json"
    if not stats_path.is_file():
        raise ReportError("missing results/statistics.json (run P8-06 first)")

    sidecar = {
        "schema_version": "jev-phase8-metrics-csv-sidecar-v1",
        "created_at": _utcnow(),
        "metrics_csv": {
            "path": "results/metrics.csv",
            "sha256": metrics_sha,
            "n_rows": 625,
            "columns": CSV_COLUMNS,
        },
        "statistics_json": {
            "path": "results/statistics.json",
            "sha256": sha256_file(stats_path),
        },
        "headline_table": {
            "path": "results/phase8/headline_table.md",
            "sha256": sha256_file(headline_path),
        },
        "figure_data": {
            "path": "results/phase8/figure_data.json",
            "sha256": sha256_file(fig_data_path),
        },
        "figures": fig_paths,
        "provenance": provenance,
        "headline": table,
    }
    sidecar_path = root / "results" / "phase8" / "metrics_csv_sidecar.json"
    atomic_write_json(sidecar_path, sidecar)
    return sidecar


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=None)
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        sidecar = run_report_outputs(workspace=args.workspace)
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        f"OK metrics.csv rows={sidecar['metrics_csv']['n_rows']} "
        f"sha256={sidecar['metrics_csv']['sha256'][:16]}… "
        f"figures={list(sidecar['figures'].keys())}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
