# Phase 6 defect triage log (P6-02)

Dated review of the P6-01 development baseline. Scope: implementation defects
only (checkout/source, diffs, triggers, truncation, model-visible state,
tokenizer/BM25, candidates, API parse/cache, assembly). Methodological changes
and the single allowed Jev prompt revision are **out of scope** (P6-03 / P6-04).

Machine companion: [`results/phase6/defect_triage.json`](../results/phase6/defect_triage.json).

## Summary

| Class | Count | Action |
| --- | ---: | --- |
| Implementation defects fixed | 1 | Code fix + regenerate baseline usage summary |
| Availability / provider issues (not code defects) | 1 | Accepted earlier; keep all 25 bugs |
| Transient API errors (recovered) | 1 | No code change |
| Areas reviewed with no defect found | 8 | Documented below |

No bug was dropped. No system, `K` cap, threshold, or prompt search was added
from development scores.

## Findings

### D-001 — Usage ledger summary ignored flat cost fields (implementation)

| Field | Value |
| --- | --- |
| Evidence | `results/phase6/development_baseline.json` showed `list_price_usd: 0` for jev/gpt/embedding while `usage_ledger.jsonl` rows carry nonzero `list_price_inference_usd` |
| Affected | Audit/baseline reporting only (not rankings or caches) |
| Class | Implementation defect |
| Correction | [`src/audit_phase5.py`](../src/audit_phase5.py) `summarize_usage_ledger` now reads flat ledger fields (`list_price_inference_usd`, `platform_fee_usd`, `effective_prepaid_credits_usd`) as well as nested `costs` |
| Rerun | Regenerated development baseline JSON/MD so Phase 6 cost diagnostics are truthful |

### A-001 — OpenRouter WAF blocks one Jev pair (availability)

| Field | Value |
| --- | --- |
| Evidence | `cache/failures/*` Jev HTTP 403 Cloudflare HTML; probe isolates trigger substring `file://etc/passwd` |
| Affected | **Jsoup-70** / `org.jsoup.integration.ConnectTest` (Jev only) |
| Class | Provider availability — **not** an implementation defect |
| Correction | None in-repo (must not rewrite Phase-3 text). Accepted 2026-09-22; revisit before evaluation freeze ([phase5-handoff.md](phase5-handoff.md)) |
| Keep in study | Yes |

### A-002 — Transient GPT-Luna 429 on Cli-30 (recovered)

| Field | Value |
| --- | --- |
| Evidence | `cache/failures/*` GPT HTTP 429 `new-account-rpm` for GPT-Luna during multi-model Cli-30 scoring |
| Affected | Historical attempt only; Cli-30 GPT-Luna and primary GPT-Nano shortlists are complete in cache |
| Class | Transient rate limit |
| Correction | None required; scheduler retries + later paced runs recovered |

## Reviewed with no defect

| Area | Result |
| --- | --- |
| Checkout / source mapping | Inventory `source_missing=0` for all 25; no unresolved ambiguities in baseline |
| Fixed→buggy diffs | All `patch_meta.direction == fixed_to_buggy`; base `Bf` / proposed `Bb` |
| Trigger parsing | Label consistency anomalies empty; positives ⊆ inventory |
| Truncation | No development bug flagged `patch_truncated`; representations within 12k cap |
| Model-visible state | Captured Jev/GPT requests have no private label fields |
| Tokenizer / BM25 / candidates | Shortlists are BM25 prefixes; Phase-4 integrity ok for all 25; candidate recall@K = 25/25 |
| Ranking assembly | Jev/GPT tails match BM25 where both exist; scores in `[0,1]` |
| Fabricated scores | Fail-closed assembly; no substitute scores for the WAF gap |

## Explicit non-actions (guardrails)

- Did **not** drop Jsoup-70 or any other development bug
- Did **not** change `K=min(200,N)`, add systems, or tune probability thresholds
- Did **not** revise the Jev prompt (reserved for P6-03)
- Did **not** invalidate or rewrite semantic caches for score chasing
