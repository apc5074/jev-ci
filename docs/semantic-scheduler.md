# Semantic scheduler (Phase 5 / P5-07)

Shared concurrency / retry / spend controls for Jev and GPT scoring.
Implementation: [`src/semantic_scheduler.py`](../src/semantic_scheduler.py).

## Rules

| Control | Value |
| --- | --- |
| Max concurrency | **16** per batch (never higher) |
| Retries | **3** after first attempt |
| Retry statuses | 429, 500, 502, 503, 529 + network timeouts |
| Backoff | 1s / 2s / 4s, or longer `Retry-After` |
| Spend ceiling | Optional reservation gate using estimated USD before each attempt |
| In-flight dedupe | Same `cache_key` shares one request |
| Provider switch | Never — optional `max_rpm` queues instead |

Failed jobs leave the candidate **unscored** (no `0.5` substitute). Final
failures are persisted under `cache/failures/` by the ranker. The scheduler
owns shortlist retries, so each attempt passes through rate and spend controls.

## Usage

`score_shortlist` on [`src/jev_ranker.py`](../src/jev_ranker.py) and
[`src/gpt_ranker.py`](../src/gpt_ranker.py) uses `run_score_batch`:

```python
from src.jev_ranker import score_shortlist

rows = score_shortlist(
    "Cli-30",
    max_concurrency=16,
    max_rpm=18,              # optional new-account throttle
    spend_ceiling_usd=1.00,  # optional cash gate
)
```

Resume: jobs whose cache entries already exist are treated as cached and do not
re-pay. Exact experiment cache always wins over provider/Gateway caching.

## Audit clarification

Budget reservations are atomic across concurrent workers in one batch. Failed
attempts with unknown billing retain their estimate; successful attempts settle
against measured input/output tokens and list prices including platform fees.
This is an estimate-based control, not a guaranteed provider invoice cap: current
call estimates can understate actual usage, and controllers are scoped to a batch.
Use provider account limits for an absolute cash ceiling. Cross-batch budgets,
token-rate limits, and durable accounting for all failed attempts remain P5-09
hardening work. Completed futures stay deduplicated for the entire batch.
