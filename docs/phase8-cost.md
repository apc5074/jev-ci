# Phase 8 cost and latency (P8-04)

**Overall: `PASS`**

Offline costs from the frozen usage ledger + dated
[`results/pricing_snapshot.json`](../results/pricing_snapshot.json). Request
latency from sealed `predictions.jsonl` cache fields. Shortlist wall times are
**reconstructed** at concurrency 16 (Phase 7 did not persist end-to-end walls).

## Cost basis (≤30% criterion)

`effective_prepaid_credits_usd` = list-price inference + platform fee at snapshot
rates. Promotional `actual_cash_usd` is recorded separately and is **not** treated
as zero inference cost.

Embedding vectors reused across bugs use **equal-share** attribution over unique
cache keys; per-bug shares reconcile to the unique-key cohort total.

## Cohort (evaluation)

| Method | Effective USD | USD / bug | Req. latency mean / p50 / p95 (ms) |
| --- | ---: | ---: | --- |
| Embedding | 0.158 | 0.00126 | 55 / 47 / 106 |
| Jev | 1.568 | 0.01255 | 542 / 412 / 821 |
| GPT-Nano | 6.347 | 0.05078 | 1359 / 1240 / 1969 |
| BM25 / Random | 0 | 0 | — |

**Jev / GPT effective cost ratio = 0.247** (≤ 0.30 → **pass**).  
Numerator `$1.568`, denominator `$6.347`.

## Commands

```bash
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 python -u scripts/compute_cost_latency.py

docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 python -m unittest tests.test_phase8_cost -v
```

## Artifacts

- [`src/cost_metrics.py`](../src/cost_metrics.py)
- [`results/phase8/cost_latency.json`](../results/phase8/cost_latency.json)
- [`tests/test_phase8_cost.py`](../tests/test_phase8_cost.py)
