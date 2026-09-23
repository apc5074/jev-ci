# Phase 8 per-bug ranking metrics (P8-02)

**Overall: `PASS`**

Pure metric functions and sealed per-bug records for BM25, Embedding, Jev, and
GPT-Nano. No Random aggregation (P8-03) and no cost fields (P8-04).

## Primary outcome (available rows)

| Method | FDR@10% | MRR | mean APFD | median NFTR | n |
| --- | ---: | ---: | ---: | ---: | ---: |
| BM25 | 0.7360 | — | — | — | 125 |
| Embedding | 0.8800 | — | — | — | 125 |
| Jev | 0.9558 | — | — | — | 113 |
| GPT-Nano | 0.9120 | — | — | — | 125 |

Jev denominator excludes the 12 accepted A-001 gaps (`available=false` rows still
present so every bug has one record per method). Full headline table is P8-07.

## Commands

```bash
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 python -u scripts/compute_per_bug_metrics.py

docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 python -m unittest tests.test_phase8_metrics -v
```

## Artifacts

- [`src/metrics.py`](../src/metrics.py) — `budget_k`, `first_trigger_rank`, APFD/RR/NFTR, detection budgets
- [`results/phase8/per_bug_metrics.json`](../results/phase8/per_bug_metrics.json) — 500 records
- [`tests/test_phase8_metrics.py`](../tests/test_phase8_metrics.py) — hand-worked cases + sealed coverage
