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
| metrics_csv | `results/metrics.csv` | `5db4b0a49f6261ebe1d158c642cf7ca1ba3fdea2f0252757d4d74a57ae07bd91` |
| statistics_json | `results/statistics.json` | `44210263c95624cee2606aad91d693ec6b79f1e9654fc0d739b3254eefaf7138` |
| headline_table | `results/phase8/headline_table.md` | `f00fed0f1bd5f2537045a6bbd4bf29e6a7e7e280facded9cbddcc6b3d57f1dc5` |
| figure_data | `results/phase8/figure_data.json` | `0eb4ef4c28761c168c26f9a4e508d16c14065a27bb8f96fa07191079ec28b004` |
| cohort_summaries | `results/phase8/cohort_summaries.json` | `744f8f31d2ba21382b1a13e633344ace5865371c48d5308edfeb185b4a08fdc5` |
| cost_latency | `results/phase8/cost_latency.json` | `e2ee4beb48c0acdb8ee5519f50e0487cab65f8cc57f92f75bb31986f9bb5d1b3` |
| evaluate_regeneration | `results/phase8/evaluate_regeneration.json` | `78f41cd2651c8471909f7c2b22525678680a3f8f1e4895b90cdde785487e56be` |
| case20_deltas | `results/phase8/case20_deltas.json` | `93caed0cdefdc3442f9668b6a1e914fdcb71cf1449ad5ab3ab5ec567a3f1cebe` |
| figure figure1_budget_curve.svg | `results/phase8/figures/figure1_budget_curve.svg` | `29a926cf4fd3297596c8e6843acb41940815291effab0f5caad5bdcb94b68f4f` |
| figure figure2_nftr_cdf.svg | `results/phase8/figures/figure2_nftr_cdf.svg` | `ab2abc4b50dc73dcec4cc289a28c8e210383d0dd75682239aa539fd3322bb054` |
| figure figure3_project_fdr10.svg | `results/phase8/figures/figure3_project_fdr10.svg` | `61174209e8164049da7e8606e5bf9d697d0d74202a4654111a670b71ff5cafd8` |
| figure figure4_quality_vs_cost.svg | `results/phase8/figures/figure4_quality_vs_cost.svg` | `cb8c712fed4900b58b870b6ba4a210217cbb2286984993241a28a1f4b353f843` |

## Practical success

- **Result:** `PASS`
- Winning alternative: `alt1`
- FDR@10% Jev=0.8640, BM25=0.7360, GPT-Nano=0.9120
- Alt1 Δpp Jev−BM25: 12.8
- Alt2 cost ratio Jev/GPT: 0.2471

## Candidate ceiling

- BM25 trigger recall@min(200,N): **125/125 = 1.0000**

## Jev misses @10%

- Detections: 108
- Misses: 17
- Candidate-generation: 0
- Reranker: 17
- Reranker IDs: `Cli-13, Cli-27, Cli-28, Jsoup-33, Jsoup-40, Jsoup-47, Jsoup-54, Jsoup-69, Jsoup-72, Jsoup-75, Jsoup-78, Jsoup-81, Jsoup-84, Jsoup-85, Jsoup-86, Lang-6, Math-104`

## 20-case qualitative review list

- Path: `results/phase8/case20_deltas.json`
- Rule: delta = BM25_first_trigger_rank - Jev_first_trigger_rank; 10 largest deltas (Jev gains) + 10 smallest (Jev losses); tie-break: project name then numeric bug_id (manifest order family)
- IDs: `JacksonDatabind-62, JacksonDatabind-35, JacksonDatabind-38, JacksonDatabind-49, JacksonDatabind-47, JacksonDatabind-72, JacksonDatabind-15, Cli-21, Math-13, Math-14, Jsoup-75, Jsoup-84, Jsoup-86, Jsoup-69, Jsoup-78, Jsoup-72, Jsoup-81, Jsoup-33, Jsoup-47, Jsoup-54`

## Offline regenerate

```bash
docker run --rm --platform linux/amd64 --network=none -v "$(pwd):/workspace" -w /workspace jev-ci:phase1 python -u scripts/evaluate.py
```

## Deviations (transparent)

- **A-001-eval** (availability): 12 Jsoup evaluation bugs lack Jev rankings (OpenRouter WAF). Phase 8 imputes non-detection with r=N for denom-125 headlines.
- **D-wallclock** (measurement): Shortlist wall times reconstructed from per-request latencies at concurrency 16; Phase 7 did not persist end-to-end walls.
- **D-tag-name** (naming): Freeze tag is experiment-v1 (overall.md historically said experiment-v1-frozen).
