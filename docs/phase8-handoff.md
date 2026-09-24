# Phase 8 → Phase 9 handoff

**Overall: `PASS`**

Phase 8 analyzed results are sealed. Phase 9 interprets and presents them
without changing methods, raw data, metrics, or the headline lineup.

## Freeze identity

- `freeze_tag`: `experiment-v1`
- `experiment_commit`: `edc70bacd23f2fc5f511ef4d97a33376e7b20bf8`
- `run_id`: `eval-v1-20260923T035853+0000`
- `sealed_at`: `2026-09-23T15:24:01+00:00`

## Canonical outputs

| Artifact | Path | SHA-256 |
| --- | --- | --- |
| metrics_csv | `results/metrics.csv` | `4bd4be3cc3f59e8d90b6fb4c847d45995bf6f97697a0a0d6b6dadb2ab9ecb32e` |
| statistics_json | `results/statistics.json` | `9df933050134bf6eaa3aaca46534e07e41b5c5662ae4a0e75128d06f6bb3bdd7` |
| headline_table | `results/phase8/headline_table.md` | `3f8aa21f8ab7aff80fc9901c22728ca8e24470fe947b6988b19033a1a0653f44` |
| figure_data | `results/phase8/figure_data.json` | `739c36b66f34afd366f5a43a2c4052c505abbce60378c4ef88e2caaf504bc7e3` |
| cohort_summaries | `results/phase8/cohort_summaries.json` | `71b8f3d7e09930503a9262b383da26c3cba75a459e94f54a3cf0d479d85bd20f` |
| cost_latency | `results/phase8/cost_latency.json` | `e2ee4beb48c0acdb8ee5519f50e0487cab65f8cc57f92f75bb31986f9bb5d1b3` |
| evaluate_regeneration | `results/phase8/evaluate_regeneration.json` | `cd7b7687bc7e55e20c7d2bb16fe8ba973dfd8338638c389dc9f1f4da5c18c690` |
| case20_deltas | `results/phase8/case20_deltas.json` | `636ea6259ac1df751c44d522d15bfb76d3adc2581ba63ab3cc2c15272cfd3b56` |
| figure figure1_budget_curve.svg | `results/phase8/figures/figure1_budget_curve.svg` | `0b268610fa24feb28bfcc89d4d0f0aab634d53616cad41404e5d432b989b1903` |
| figure figure2_nftr_cdf.svg | `results/phase8/figures/figure2_nftr_cdf.svg` | `a89cbb28faba85b8f5907bae8ed00b54e4c22db24481e354cd934d86d1005e3d` |
| figure figure3_project_fdr10.svg | `results/phase8/figures/figure3_project_fdr10.svg` | `68d81fa43c04e3bbfe42488443ba0b6c3c5ca09f3d27b038ea1c8030bcc82b3e` |
| figure figure4_quality_vs_cost.svg | `results/phase8/figures/figure4_quality_vs_cost.svg` | `4228fcb679f5d806b25c88099f8b9430f17b3b8fdfb954eeefef8450c3672bd7` |

## Practical success

- **Result:** `PASS`
- Winning alternative: `alt1`
- FDR@10% Jev=0.9558, BM25=0.7345, GPT-Nano=0.9204
- Alt1 Δpp Jev−BM25: 22.1
- Alt2 cost ratio Jev/GPT: 0.2536

## Candidate ceiling

- BM25 trigger recall@min(200,N): **113/113 = 1.0000**

## Jev misses @10%

- Detections: 108
- Misses: 5
- Candidate-generation: 0
- Reranker: 5
- Reranker IDs: `Cli-13, Cli-27, Cli-28, Lang-6, Math-104`

## 20-case qualitative review list

- Path: `results/phase8/case20_deltas.json`
- Rule: delta = BM25_first_trigger_rank - Jev_first_trigger_rank; 10 largest deltas (Jev gains) + 10 smallest (Jev losses); tie-break: project name then numeric bug_id (manifest order family)
- IDs: `JacksonDatabind-62, JacksonDatabind-35, JacksonDatabind-38, JacksonDatabind-49, JacksonDatabind-47, JacksonDatabind-72, JacksonDatabind-15, Cli-21, Math-13, Math-14, JacksonDatabind-103, Math-104, JacksonDatabind-51, Lang-6, Lang-61, Cli-28, Lang-26, Cli-32, JacksonDatabind-100, Lang-47`

## Offline regenerate

```bash
docker run --rm --platform linux/amd64 --network=none -v "$(pwd):/workspace" -w /workspace jev-ci:phase1 python -u scripts/evaluate.py
```

## Deviations (transparent)

- **A-001-eval** (availability_cohort): 12 Jsoup evaluation bugs lack complete Jev rankings (OpenRouter WAF). Headline analysis excludes those 12 bugs from every method (paired denom=113). Listed in README.
- **D-wallclock** (measurement): Shortlist wall times reconstructed from per-request latencies at concurrency 16; Phase 7 did not persist end-to-end walls.
- **D-tag-name** (naming): Freeze tag is experiment-v1 (overall.md historically said experiment-v1-frozen).
