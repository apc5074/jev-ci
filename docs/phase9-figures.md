# Phase 9 figures (P9-02)

**Overall: `PASS`**

Final report figures live under [`results/figures/`](../results/figures/). They are
byte-identical copies of the sealed Phase 8 SVGs, cross-checked against cohort
summaries (n=113 headline cohort).

## Artifacts

| Figure | Path |
| --- | --- |
| 1 — Fault detection vs budget | [`results/figures/figure1_fault_detection_vs_budget.svg`](../results/figures/figure1_fault_detection_vs_budget.svg) |
| 2 — First-trigger rank CDF | [`results/figures/figure2_first_trigger_rank_cdf.svg`](../results/figures/figure2_first_trigger_rank_cdf.svg) |
| 3 — FDR@10% by project | [`results/figures/figure3_fdr10_by_project.svg`](../results/figures/figure3_fdr10_by_project.svg) |
| 4 — Quality vs cost | [`results/figures/figure4_quality_vs_cost.svg`](../results/figures/figure4_quality_vs_cost.svg) |
| Captions | [`results/figures/captions.md`](../results/figures/captions.md) |
| Manifest | [`results/phase9/figures_manifest.json`](../results/phase9/figures_manifest.json) |

## Notes

- Denominator: **113** evaluation bugs (A-001 gaps excluded for all methods).
- Figure 3: Jsoup **n=13**; other projects **n=25** (descriptive only).
- Figure 4 cost axis: mean **effective prepaid credits** / bug (frozen Phase 6 snapshot).
- Source generators: `scripts/evaluate.py` → `results/phase8/figures/`; publish with `scripts/publish_figures.py`.

## Commands

```bash
docker run --rm --platform linux/amd64 --network=none \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 python -u scripts/evaluate.py

docker run --rm --platform linux/amd64 --network=none \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 python -u scripts/publish_figures.py
```
