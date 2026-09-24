# Phase 9 offline reproduction (P9-06)

**Overall: `PASS`**

Clean offline regeneration of sealed metrics, statistics, headline table, and
figures via `scripts/evaluate.py` / `scripts/reproduce_phase9.py` with
`--network=none` and API credentials cleared.

## Artifacts

| Output | Path |
| --- | --- |
| Reproduction record | [`results/phase9/reproduction_record.json`](../results/phase9/reproduction_record.json) |
| Reproduction (Markdown) | [`results/phase9/reproduction_record.md`](../results/phase9/reproduction_record.md) |
| Final inventory | [`results/phase9/final_artifact_inventory.json`](../results/phase9/final_artifact_inventory.json) |

## Checks

- Byte-identical: `metrics.csv`, `statistics.json`, Phase 8 headline table, `figure_data.json`, four Phase 8 SVGs
- Evaluate checks: 16/16
- Inventory: required README/report/figures/failure analysis/predictions/manifest present
- Report text reconciled to cohort FDR@10% 0.9558 vs 0.7345 (+22.1 pp)
- Metrics split evaluation-only; paid requests during reproduction: **0**

## Commands

```bash
docker run --rm --platform linux/amd64 --network=none \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 python -u scripts/reproduce_phase9.py
```

Or evaluate alone:

```bash
docker run --rm --platform linux/amd64 --network=none \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 python -u scripts/evaluate.py
```
