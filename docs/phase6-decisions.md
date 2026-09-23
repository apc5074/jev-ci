# Phase 6 methodological decisions / deviations (P6-04)

Closes open interpretation choices so Phase 7 does not invent rules at
evaluation time. Machine config: [`experiment.yaml`](../experiment.yaml) and
[`results/phase6/experiment.json`](../results/phase6/experiment.json). Pricing:
[`results/pricing_snapshot.json`](../results/pricing_snapshot.json) (date
**2026-09-23**).

Frozen prompt bodies: `results/phase6/prompts/`.

## Prompt decision (P6-03 deferred by operator)

| Choice | Value |
| --- | --- |
| Decision | **Retain** initial Jev prompt (`jev-would_detect_regression-v1`) |
| Revision count | **0** |
| Final name for preregistration | `v1` (= original) |
| GPT rubric | Frozen alongside as `gpt-would_detect_regression-v1` (same instructions/criteria) |
| Note | P6-03 ticket was not run separately; retaining the original is the locked choice for P6-04. A later revision would require a new experiment version. |

## Locked interpretations

| Topic | Locked value | Source |
| --- | --- | --- |
| Patch / test char counting | `len()` Unicode code points | Phase 3 / `patch_meta` |
| Patch truncation | 12k cap; equal prefix/suffix; marker reservation; no silent truncate in eval embeddings | Phase 3–5 |
| BM25 query | Model-visible `representation.txt` (not full untruncated diff) | Phase 4 |
| BM25 docs | FQCN + full fixed source; missing source → FQCN-only | Phase 4 |
| BM25 formula | `jev-bm25-v1`, k1=1.5, b=0.75 | Phase 4 |
| Tie-break (BM25 / Embedding) | score ↓, FQCN ↑ | Phase 4–5 |
| Semantic prefix tie-break | score ↓, original BM25 rank ↑ | P5-08 |
| Shortlist | `K=min(200,N)` exact BM25 prefix; shared hash | Phase 4–5 |
| Nested / ambiguous sources | Hard-fail; no arbitrary pick | Phase 3 |
| Long-source windows | BM25 top-3 windows (`parseHTTPResponse_v2`) for compact reps | Phase 3 |
| Embedding over-limit | `fail_closed_no_truncate_v1` (8192 tokens) | P5-04 |
| Random index | **Zero-based**; eval `1337+i`; dev `1001337+i` | P5-03 |
| Output precision (planned tables) | rates 4 dp; ranks integer; USD 6 dp | this lock |
| Cache keys | `canonical_json` sorted keys, compact separators; fields provider/model/prompt/state/question | P5-02 |
| Scheduler | ≤16 concurrent; retries 429/5xx + timeouts; 1/2/4s; optional RPM/spend ceiling | P5-07 |
| Jev provider | OpenRouter `typesafe/jev-1.13` (dev observed `…-20260917`); no moving alias | P5-01 |
| GPT primary | `gpt-5.4-nano-2026-03-17`, `reasoning.effort=none` | overall.md §20 / P5-06 |
| Five systems | Random, BM25, Embedding, Jev, GPT-Nano | overall.md |
| Extra GPT models | 4.1-nano, 4o-mini, Luna — development review only | P5-06 extension |

## Outcomes & statistics (locked)

| Item | Value |
| --- | --- |
| Primary | FDR@10% with `k = max(1, ceil(0.10 * N))` |
| Secondary FDR | 1%, 2%, 5%, 20%, 50%, 100% |
| Secondary | MRR, NFTR / median NFTR, APFD, candidate recall@200, cost, latency |
| APFD | `1 - (r_b/N_b) + 1/(2*N_b)` |
| Primary contrast | Jev vs BM25, McNemar exact |
| Bootstrap | 10,000 paired samples; 95% percentile CIs |
| Secondary contrasts | Jev vs Embedding; Jev vs GPT-Nano |
| Practical success | FDR@10% ≥ BM25+5pp **or** within 2pp of GPT-Nano **and** cost ≤30% of GPT |

## Cost basis for the ≤30% criterion

Use **`effective_prepaid_credits_usd`** = list-price inference × (1 + platform fee) at the
dated snapshot rates in `results/pricing_snapshot.json`. Record promotional
`actual_cash_usd` separately; do **not** treat gateway free tiers or promo
credits as intrinsic zero inference cost.

## Deviations / open items

| ID | Kind | Detail |
| --- | --- | --- |
| A-001 | Availability | Jsoup-70 / `ConnectTest` Jev blocked by OpenRouter WAF (`file://etc/passwd`). Accepted for development continuation. **Must resolve or formally deviate before evaluation scoring.** |
| D-001 | Fixed (P6-02) | Ledger summary flat-cost fields — reporting only |
| TypeSafe direct | Unavailable | OpenRouter selected; Cloudflare Jev rejected until pin+price verified |

## Explicit non-changes

- Research question and five-system design unchanged from `overall.md`
- No quiet edit to hypotheses or practical-success thresholds
- No evaluation bugs scored or extracted under this lock
