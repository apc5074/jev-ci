# Phase 9 final artifact index (P9-07)

**Phase complete: `True`** · consistency OK: `True`

## Main finding

See [`main_finding.md`](main_finding.md). Jev FDR@10%=0.9558 vs BM25=0.7345 (+22.1 pp); practical success=`True`.

## Artifact index

| Role | Path |
| --- | --- |
| manifest | `data/manifest.json` |
| preregistration | `EXPERIMENT.md` |
| metrics | `results/metrics.csv` |
| predictions | `results/predictions.jsonl` |
| statistics | `results/statistics.json` |
| headline_table | `results/phase9/headline_table.md` |
| figures | `results/figures/` |
| failure_cases | `results/failure_cases.json` |
| failure_analysis | `results/failure_analysis.json` |
| readme | `README.md` |
| report | `docs/phase9-report.md` |
| reproduction | `results/phase9/reproduction_record.json` |
| inventory | `results/phase9/final_artifact_inventory.json` |
| main_finding | `results/phase9/main_finding.md` |

## Freeze

- Tag: `experiment-v1`
- Commit: `edc70bacd23f2fc5f511ef4d97a33376e7b20bf8`
- Phase 7 seal: `bf9ba9ff9dee9ae91a344ae0079a63e07a6763c01ae07c2e5d9c0b73e3ffffd2`
- Phase 8 seal: `6d3bf370b2b901dbb44608243e3684792a7a13e6845746314035c6a8974b10f1`

## Deviations / post-hoc

- A-001-eval: 12 Jsoup WAF gaps excluded from all methods (n=113)
- D-wallclock: shortlist walls reconstructed from per-request latencies
- D-tag-name: freeze tag experiment-v1
- Post-hoc: P9-04 qualitative categories on mechanical 20-case list (explanatory only)
