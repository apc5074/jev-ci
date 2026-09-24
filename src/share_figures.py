"""Public / tweet share figures — plain English, sealed numbers only."""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.example_contract import WORKSPACE, atomic_write_json, atomic_write_text, read_json

OUT_DIR = WORKSPACE / "results" / "share"
FONT = "ui-sans-serif, system-ui, -apple-system, Helvetica Neue, Helvetica, Arial, sans-serif"

# Punchy palette (not the report slate stack)
BG = "#0B1220"
PANEL = "#121A2B"
INK = "#F8FAFC"
MUTED = "#94A3B8"
GRID = "#1E293B"
JEV = "#22D3EE"  # cyan — hero
BM25 = "#94A3B8"
EMB = "#A78BFA"
GPT = "#FBBF24"
RANDOM = "#475569"


def _esc(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _text(
    x: float,
    y: float,
    text: str,
    *,
    size: int = 16,
    anchor: str = "start",
    weight: str = "500",
    fill: str = INK,
) -> str:
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" '
        f'font-family="{FONT}" font-size="{size}" font-weight="{weight}" '
        f'fill="{fill}">{_esc(text)}</text>'
    )


def _pct(x: float) -> str:
    return f"{100.0 * x:.0f}%"


def tweet_catch_rate(cohort: dict[str, Any]) -> str:
    """Hero bar chart: % of bugs caught in the first 10% of tests."""
    w, h = 1200, 675
    methods = [
        ("Random", float(cohort["Random"]["primary_fdr_at_10pct"]), RANDOM),
        ("BM25", float(cohort["BM25"]["primary_fdr_at_10pct"]), BM25),
        ("Embedding", float(cohort["Embedding"]["primary_fdr_at_10pct"]), EMB),
        ("GPT-5.4 nano", float(cohort["GPT-Nano"]["primary_fdr_at_10pct"]), GPT),
        ("Jev", float(cohort["Jev"]["primary_fdr_at_10pct"]), JEV),
    ]
    left, right, top, bottom = 80, 1140, 140, 580
    plot_w = right - left
    plot_h = bottom - top
    n = len(methods)
    gap = 28
    bar_w = (plot_w - gap * (n - 1)) / n

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
        f'<rect width="100%" height="100%" fill="{BG}"/>',
        _text(60, 58, "Which tests catch the regression first?", size=34, weight="700"),
        _text(
            60,
            92,
            "Share of bugs where a known failing test lands in the first 10% of the suite  ·  n = 113",
            size=18,
            fill=MUTED,
        ),
    ]

    # soft panel
    parts.append(
        f'<rect x="40" y="118" width="1120" height="500" rx="20" fill="{PANEL}"/>'
    )

    # horizontal grid at 25/50/75/100
    for frac in (0.25, 0.5, 0.75, 1.0):
        y = bottom - frac * plot_h
        parts.append(
            f'<line x1="{left}" y1="{y:.1f}" x2="{right}" y2="{y:.1f}" '
            f'stroke="{GRID}" stroke-width="1"/>'
        )
        parts.append(_text(left - 12, y + 5, _pct(frac), size=14, anchor="end", fill=MUTED))

    for i, (name, val, color) in enumerate(methods):
        x = left + i * (bar_w + gap)
        bh = val * plot_h
        y = bottom - bh
        # bar
        parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{bh:.1f}" '
            f'rx="10" fill="{color}"/>'
        )
        # value on / above bar
        label_y = y - 14 if bh > 80 else y - 14
        parts.append(
            _text(
                x + bar_w / 2,
                label_y,
                _pct(val),
                size=28 if name == "Jev" else 22,
                anchor="middle",
                weight="700",
                fill=JEV if name == "Jev" else INK,
            )
        )
        parts.append(
            _text(
                x + bar_w / 2,
                bottom + 36,
                name,
                size=18 if name != "GPT-5.4 nano" else 16,
                anchor="middle",
                weight="600" if name == "Jev" else "500",
                fill=JEV if name == "Jev" else INK,
            )
        )

    # callout
    jev = float(cohort["Jev"]["primary_fdr_at_10pct"])
    bm25 = float(cohort["BM25"]["primary_fdr_at_10pct"])
    delta = 100.0 * (jev - bm25)
    parts.append(
        _text(
            60,
            650,
            f"Jev vs BM25: +{delta:.0f} percentage points  ·  same bugs, paired comparison",
            size=16,
            fill=MUTED,
        )
    )
    parts.append("</svg>")
    return "\n".join(parts)


def tweet_better_cheaper(cohort: dict[str, Any]) -> str:
    """Quality vs cost — Embedding / Jev / GPT with big labels."""
    w, h = 1200, 675
    points = [
        (
            "Embedding",
            float(cohort["Embedding"]["primary_fdr_at_10pct"]),
            float(cohort["Embedding"]["cost_usd_per_bug"]),
            EMB,
        ),
        (
            "Jev",
            float(cohort["Jev"]["primary_fdr_at_10pct"]),
            float(cohort["Jev"]["cost_usd_per_bug"]),
            JEV,
        ),
        (
            "GPT-5.4 nano",
            float(cohort["GPT-Nano"]["primary_fdr_at_10pct"]),
            float(cohort["GPT-Nano"]["cost_usd_per_bug"]),
            GPT,
        ),
    ]
    left, right, top, bottom = 110, 1080, 150, 560
    plot_w = right - left
    plot_h = bottom - top
    # axes ranges with padding
    costs = [p[2] for p in points]
    fdrs = [p[1] for p in points]
    xmin, xmax = 0.0, max(costs) * 1.15
    ymin, ymax = 0.82, 1.0

    def sx(c: float) -> float:
        return left + (c - xmin) / (xmax - xmin) * plot_w

    def sy(f: float) -> float:
        return bottom - (f - ymin) / (ymax - ymin) * plot_h

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
        f'<rect width="100%" height="100%" fill="{BG}"/>',
        _text(60, 58, "Better detection. Lower cost.", size=34, weight="700"),
        _text(
            60,
            92,
            "Catch rate in the first 10% of tests  vs  mean rerank cost per bug",
            size=18,
            fill=MUTED,
        ),
        f'<rect x="40" y="118" width="1120" height="500" rx="20" fill="{PANEL}"/>',
    ]

    # grid
    for f in (0.85, 0.90, 0.95, 1.00):
        y = sy(f)
        parts.append(
            f'<line x1="{left}" y1="{y:.1f}" x2="{right}" y2="{y:.1f}" '
            f'stroke="{GRID}" stroke-width="1"/>'
        )
        parts.append(_text(left - 14, y + 5, _pct(f), size=14, anchor="end", fill=MUTED))
    for c in (0.0, 0.02, 0.04, 0.06):
        if c > xmax:
            continue
        x = sx(c)
        parts.append(
            f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{bottom}" '
            f'stroke="{GRID}" stroke-width="1"/>'
        )
        parts.append(_text(x, bottom + 28, f"${c:.2f}", size=14, anchor="middle", fill=MUTED))

    parts.append(
        _text((left + right) / 2, bottom + 56, "cost per bug →", size=15, anchor="middle", fill=MUTED)
    )
    parts.append(
        _text(48, (top + bottom) / 2, "catch rate", size=15, anchor="middle", fill=MUTED)
    )
    # rotate label via transform - simpler: skip rotate, put in title

    # "better" / "cheaper" quadrant hints
    parts.append(_text(right - 8, top + 24, "better ↑", size=14, anchor="end", fill=MUTED))
    parts.append(_text(left + 8, bottom - 12, "cheaper ←", size=14, fill=MUTED))

    for name, fdr, cost, color in points:
        x, y = sx(cost), sy(fdr)
        r = 18 if name == "Jev" else 14
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{color}"/>')
        # label with metrics
        lx = x + 26
        ly = y - 8
        if name == "Embedding":
            lx, ly = x + 22, y + 6
        if name == "GPT-5.4 nano":
            lx, ly = x - 26, y - 28
            anchor = "end"
        else:
            anchor = "start"
        parts.append(
            _text(lx, ly, name, size=20, anchor=anchor, weight="700", fill=color)
        )
        parts.append(
            _text(
                lx,
                ly + 22,
                f"{_pct(fdr)}  ·  ${cost:.3f}/bug",
                size=15,
                anchor=anchor,
                fill=MUTED,
            )
        )

    parts.append(
        _text(
            60,
            650,
            "Jev beats GPT-5.4 nano on catch rate while costing ~4× less  ·  sealed prepaid-credit prices",
            size=16,
            fill=MUTED,
        )
    )
    parts.append("</svg>")
    return "\n".join(parts)


def tweet_budget_curve(figure_data: dict[str, Any]) -> str:
    """Simplified detection-vs-budget: BM25 vs Jev vs GPT, plain English."""
    w, h = 1200, 675
    series = {
        "BM25": (figure_data["figure1_budget_curve"]["BM25"], BM25),
        "GPT-5.4 nano": (figure_data["figure1_budget_curve"]["GPT-Nano"], GPT),
        "Jev": (figure_data["figure1_budget_curve"]["Jev"], JEV),
    }
    budgets = [0.01, 0.02, 0.05, 0.10, 0.20, 0.50, 1.0]
    left, right, top, bottom = 90, 1100, 150, 560
    plot_w = right - left
    plot_h = bottom - top

    def sx(b: float) -> float:
        # log-ish visual: map via index for readability at low budgets
        # use log10 scale from 0.01..1
        t = (math.log10(b) - math.log10(0.01)) / (math.log10(1.0) - math.log10(0.01))
        return left + t * plot_w

    def sy(f: float) -> float:
        return bottom - f * plot_h

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
        f'<rect width="100%" height="100%" fill="{BG}"/>',
        _text(60, 58, "Run fewer tests. Still catch the bug.", size=34, weight="700"),
        _text(
            60,
            92,
            "% of the test suite you run  →  % of regressions you catch  ·  n = 113",
            size=18,
            fill=MUTED,
        ),
        f'<rect x="40" y="118" width="1120" height="500" rx="20" fill="{PANEL}"/>',
    ]

    for f in (0.25, 0.5, 0.75, 1.0):
        y = sy(f)
        parts.append(
            f'<line x1="{left}" y1="{y:.1f}" x2="{right}" y2="{y:.1f}" '
            f'stroke="{GRID}" stroke-width="1"/>'
        )
        parts.append(_text(left - 12, y + 5, _pct(f), size=14, anchor="end", fill=MUTED))

    # 10% marker
    x10 = sx(0.10)
    parts.append(
        f'<line x1="{x10:.1f}" y1="{top}" x2="{x10:.1f}" y2="{bottom}" '
        f'stroke="{JEV}" stroke-width="2" stroke-dasharray="6 6" opacity="0.7"/>'
    )
    parts.append(_text(x10 + 8, top + 22, "10% budget", size=14, fill=JEV, weight="600"))

    for name, (pts, color) in series.items():
        by_b = {float(p["budget_fraction"]): float(p["fdr"]) for p in pts}
        coords = []
        for b in budgets:
            coords.append(f"{sx(b):.1f},{sy(by_b[b]):.1f}")
        width = 4.5 if name == "Jev" else 3
        parts.append(
            f'<polyline points="{" ".join(coords)}" fill="none" stroke="{color}" '
            f'stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round"/>'
        )
        for b in budgets:
            parts.append(
                f'<circle cx="{sx(b):.1f}" cy="{sy(by_b[b]):.1f}" r="5" '
                f'fill="{BG}" stroke="{color}" stroke-width="2.5"/>'
            )

    # Legend (avoids colliding end labels)
    legend = [
        ("Jev", JEV),
        ("GPT-5.4 nano", GPT),
        ("BM25", BM25),
    ]
    lx, ly = 860, 160
    for i, (name, color) in enumerate(legend):
        yy = ly + i * 32
        parts.append(
            f'<line x1="{lx}" y1="{yy}" x2="{lx + 36}" y2="{yy}" '
            f'stroke="{color}" stroke-width="4" stroke-linecap="round"/>'
        )
        parts.append(_text(lx + 48, yy + 5, name, size=16, weight="600", fill=color))

    for b, label in (
        (0.01, "1%"),
        (0.02, "2%"),
        (0.05, "5%"),
        (0.10, "10%"),
        (0.20, "20%"),
        (0.50, "50%"),
        (1.0, "100%"),
    ):
        parts.append(_text(sx(b), bottom + 28, label, size=14, anchor="middle", fill=MUTED))

    parts.append(
        _text(
            60,
            650,
            "Primary result is at 10%: Jev 96% vs BM25 73%",
            size=16,
            fill=MUTED,
        )
    )
    parts.append("</svg>")
    return "\n".join(parts)


def publish_share_figures(*, workspace: Path | None = None) -> dict[str, Any]:
    root = workspace or WORKSPACE
    cohort = read_json(root / "results/phase8/cohort_summaries.json")["cohort"]
    fig_data = read_json(root / "results/phase8/figure_data.json")
    out = root / "results" / "share"
    out.mkdir(parents=True, exist_ok=True)

    files = {
        "tweet_catch_rate.svg": tweet_catch_rate(cohort),
        "tweet_better_cheaper.svg": tweet_better_cheaper(cohort),
        "tweet_budget_curve.svg": tweet_budget_curve(fig_data),
    }
    written = []
    for name, svg in files.items():
        path = out / name
        atomic_write_text(path, svg)
        written.append(str(path.relative_to(root)))

    captions = "\n".join(
        [
            "# Share / tweet figures",
            "",
            "Plain-English charts for social. Numbers match sealed Phase 8 cohort (n=113).",
            "",
            "## tweet_catch_rate.svg",
            "Hero bar chart — % of bugs where a known failing test is in the first 10% of the suite.",
            "",
            "## tweet_better_cheaper.svg",
            "Catch rate vs $/bug for Embedding, Jev, GPT-5.4 nano.",
            "",
            "## tweet_budget_curve.svg",
            "Detection vs % of suite run (BM25 / GPT / Jev), with 10% budget marked.",
            "",
            "## Suggested tweet pairing",
            "1. Lead with catch_rate",
            "2. Reply with better_cheaper",
            "3. Optional thread: budget_curve",
            "",
        ]
    )
    atomic_write_text(out / "README.md", captions)
    manifest = {
        "schema_version": "jev-share-figures-v1",
        "ok": True,
        "n_evaluation_bugs": 113,
        "files": written,
    }
    atomic_write_json(out / "manifest.json", manifest)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Publish tweet/share figures")
    parser.add_argument("--workspace", type=Path, default=None)
    args = parser.parse_args(argv)
    man = publish_share_figures(workspace=args.workspace)
    print(f"OK share_figures files={len(man['files'])} dir=results/share/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
