# Semantic cache and usage ledger (Phase 5 / P5-02)

Shared helpers in [`src/semantic_cache.py`](../src/semantic_cache.py).

## Layout

| Path | Contents |
| --- | --- |
| `cache/jev/<sha256>.json` | Successful Jev Noul scores |
| `cache/gpt/<sha256>.json` | Successful GPT probabilities |
| `cache/embeddings/<sha256>.json` | Embedding vectors |
| `cache/failures/<sha256>.json` | Failed attempts (never treated as scores) |
| `results/usage_ledger.jsonl` | Append-only usage / cost events |

`cache/*` stays gitignored (except `.gitkeep`).

## Cache key

SHA-256 of canonical JSON:

```json
{
  "provider": "...",
  "model_id": "...",
  "prompt_version": "...",
  "state": { "code_change": "...", "candidate_test": "..." },
  "question": { "id": "would_detect_regression", "type": "noul", "...": "..." }
}
```

Embeddings use `{ "kind": "embedding", "model_id", "input_text" }`.

A change to provider, model, prompt version, or representation text yields a new
key. Exact hits are reused before any paid call.

## Model-visible vs metadata

- **State / question:** patch + test strings and rubric only.
- **Metadata** (optional on the cache record): `qualified_id`, `test_class`, etc.
  Never inserted into `state`.

## Success validation

Before treating an entry as a score: finite `score ∈ [0,1]`,
`usage.input_tokens` present, `schema_version` match, and recomputed
`cache_key` equals the stored key. Corrupt files raise `CacheError`.

## Cost ledger

Each successful paid call appends one ledger row keyed by `attempt_id`
(normally the `cache_key`). Resume does **not** double-count. Each row can
carry:

| Field | Meaning |
| --- | --- |
| `list_price_inference_usd` | Published token rate × tokens |
| `platform_fee_usd` | Credit-purchase fee estimate (e.g. OpenRouter 5.5%) |
| `provider_reported_cost_usd` | Provider `usage.cost` when present |
| `actual_cash_usd` | Optional cash after promotions |

## Prompt versions

| Constant | Value |
| --- | --- |
| `JEV_PROMPT_VERSION` | `jev-would_detect_regression-v1` |
| `GPT_PROMPT_VERSION` | `gpt-would_detect_regression-v1` |

Bump when instructions/criteria change (invalidates cache keys).
