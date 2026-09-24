# EXPERIMENT.md — Preregistered study design (v1)

**Status:** Frozen at annotated git tag `experiment-v1` (`edc70bacd23f2fc5f511ef4d97a33376e7b20bf8`). Write `results/phase6/freeze_lock.json` via `scripts/write_freeze_lock.py` to unlock evaluation.

**Machine companion:** [`experiment.yaml`](experiment.yaml) · [`results/phase6/experiment.json`](results/phase6/experiment.json)  
**Prompt files:** [`prompts/jev/v1.json`](prompts/jev/v1.json) · [`prompts/gpt/v1.json`](prompts/gpt/v1.json)  
**Human summary of outcomes:** [`README.md`](README.md)

This document is the human-readable freeze of the study. An independent reader must be able to reconstruct the design and decide in advance whether Jev met the success criteria. **No evaluation bugs may be scored until the freeze tag exists.**

---

## 1. Claim limits

This experiment measures **rankings of known fault-revealing test classes** under a **test-class count budget**.

It does **not** claim:

- CI wall-clock or runtime reduction
- Classification of unlabeled tests as triggering / non-triggering
- That non-triggering classes are negatives for precision-style metrics

---

## 2. Hypotheses

### H1 (primary)

At a test budget of **10% of all test classes**, BM25→Jev detects a larger fraction of Defects4J regressions than BM25 alone.

Primary metric: **Fault Detection Recall @ 10% test budget (FDR@10%)**.

### H2

Jev places the first known triggering test earlier in the ranking than BM25 and embedding similarity.

Measured with **MRR**, **normalized first-trigger rank (NFTR)**, and **APFD**.

### H3

Jev approaches or exceeds the ranking performance of a cheap generative LLM reranker (**GPT-Nano**) while requiring substantially less inference cost.

---

## 3. Practical-success criterion (frozen)

Call Jev practically successful if **either**:

1. `Jev FDR@10% ≥ BM25 FDR@10% + 5` absolute percentage points, **or**
2. Jev FDR@10% is within **2** absolute percentage points of GPT-Nano **and** Jev reranking cost ≤ **30%** of GPT-Nano reranking cost.

These thresholds must not change after evaluation results are visible.

**Cost basis for the ≤30% clause:** `effective_prepaid_credits_usd` (= list-price inference × (1 + platform fee)) at the dated rates in [`results/pricing_snapshot.json`](results/pricing_snapshot.json) (**2026-09-23**). Promotional `actual_cash_usd` is recorded separately and is **not** the intrinsic price for this criterion. Gateway free tiers alone do not make Jev “free.”

---

## 4. Dataset

| Field | Value |
| --- | --- |
| Suite | Defects4J |
| Version | **3.0.1** |
| Upstream commit | `6d54320e0db5a357f9ab38a8e4d2e5aead7e1c09` |
| Selection seed | `20260922` |
| Project order | Cli, Lang, Math, Jsoup, JacksonDatabind |
| Manifest | [`data/manifest.json`](data/manifest.json) |
| Development | **25** bugs |
| Evaluation | **125** bugs |
| Direction | Base **Bf** (fixed) → proposed **Bb** (buggy); `patch_meta.direction = fixed_to_buggy` |

IDs are listed in §15. Evaluation IDs may appear in the manifest and this file; their examples, rankings, and scores remain **untouched** until after freeze.

---

## 5. Five ranking systems

| Name | Role |
| --- | --- |
| **Random** | 1,000 full-suite permutations; eval seed `1337 + i` (zero-based); dev seed `1001337 + i` |
| **BM25** | Full-suite lexical ranking |
| **Embedding** | Full-suite `text-embedding-3-small` cosine ranking (not shortlist-restricted) |
| **Jev** | BM25 top-`K` semantic rerank; Noul `would_detect_regression` |
| **GPT-Nano** | Same shortlist/state as Jev; structured probability; snapshot below |

Development-only comparison models (not headline systems): `gpt-4.1-nano`, `gpt-4o-mini`, `gpt-luna`.

---

## 6. Representations

### Patch (model-visible)

- Source: `data/patches/<slug>/representation.txt`
- Cap: **12,000** Unicode code points (`len()`); equal prefix/suffix with truncation marker `[...PATCH TRUNCATED...]`
- BM25 query uses this same model-visible representation (not the untruncated audit diff)

### Tests (model-visible)

- Compact representations under `data/tests/<slug>/reps/`
- Cap: **12,000** code points; long sources use BM25 top-3 windows (`parseHTTPResponse_v2`)
- Missing source: retained in inventory; BM25 document is FQCN-only; ambiguous resolution hard-fails

### Extraction exceptions

Documented Defects4J / source-map anomalies stay in the study with evidence; bugs are not dropped to make checks pass. Nested/ambiguous sources never pick arbitrarily.

---

## 7. Tokenizer and BM25

| Setting | Value |
| --- | --- |
| Tokenizer | `jev-code-tokenizer-v1` |
| Config SHA-256 | `e8f04897083a9ecf43c92e6612d7b16882e7ac713a00bd1de57e63b5efaa7382` |
| BM25 version | `jev-bm25-v1` |
| k1 / b | **1.5** / **0.75** |
| Document | FQCN + full fixed-revision source |
| Query | Model-visible patch representation |
| Order | score ↓, FQCN ↑ |
| Lexical contract | `jev-bm25-lexical-v1` |

---

## 8. Candidate generation ceiling

```text
K = min(200, N)
```

The shortlist is the **exact prefix** of the saved BM25 ranking (`shortlist_sha256`). Jev and GPT-Nano must consume the **same** ordered IDs and must **not** regenerate candidates.

Report **BM25 trigger recall@200**. If no trigger is in the top-`K`, classify a Jev miss as **candidate-generation failure**; if a trigger was in top-`K` but ranked poorly, **reranker failure**.

---

## 9. Semantic assembly

1. Require one valid score in `[0,1]` per shortlisted class  
2. Reorder prefix by score ↓, original BM25 rank ↑  
3. Append BM25 ranks `K+1..N` unchanged  

Missing / non-finite / wrong-model scores fail closed (no fabricated scores).

---

## 10. Jev (v1 — retained original)

| Field | Value |
| --- | --- |
| Provider | OpenRouter |
| Request model | `typesafe/jev-1.13` |
| Observed (development) | `typesafe/jev-1.13-20260917` |
| Forbidden aliases | `jev-latest`, `jev-preview`, `~typesafe/jev-latest` |
| Prompt file | [`prompts/jev/v1.json`](prompts/jev/v1.json) |
| Cache prompt version | `jev-would_detect_regression-v1` |
| Semantic revision count | **0** (retain original) |
| File SHA-256 | `2687635cea341f22e88ad848de09be711b6e80fe45f46d93da72e0ca4a477401` |
| Question object SHA-256 | `3b0c683653e62f3d3964ad0663f8b28e9470f88ecc60b7ca48f9eb7cbf5b40f8` |
| State fields | `code_change`, `candidate_test` |
| Granularity | One test class per request |

Question text and criteria are exactly those in `prompts/jev/v1.json` (and the matching code builders). One-pair Noul; score = `answer.noul` ∈ `[0,1]`.

---

## 11. GPT-Nano (v1)

| Field | Value |
| --- | --- |
| Canonical snapshot | `gpt-5.4-nano-2026-03-17` |
| OpenRouter request | `openai/gpt-5.4-nano` |
| Reasoning | `effort=none` |
| Prompt file | [`prompts/gpt/v1.json`](prompts/gpt/v1.json) |
| Cache prompt version | `gpt-would_detect_regression-v1` |
| File SHA-256 | `a5e7c1590f560dc6faf1b81fc84bbc4a1cb75d125c370bfa23f2724a6e71fd90` |
| Question object SHA-256 | `bcd293f79f5826ab8be4296b8a77d3cbf1139c4dfe3d113d9180c5d7711b2caa` |
| Output | Structured `{ "probability": number }` in `[0,1]`; no chain-of-thought |
| State | Byte-for-byte same patch/test strings as Jev |

---

## 12. Embedding baseline

| Field | Value |
| --- | --- |
| Model | `text-embedding-3-small` |
| Scope | Full suite (not BM25 shortlist) |
| Similarity | Cosine ↓, FQCN ↑ |
| Uses BM25 features | **No** |
| Over-limit | `fail_closed_no_truncate_v1` (8192 tokens; never truncate) |

---

## 13. Cache, retries, concurrency

| Rule | Value |
| --- | --- |
| Cache key | SHA-256 of canonical JSON `{provider, model_id, prompt_version, state, question}` |
| Roots | `cache/jev`, `cache/gpt`, `cache/embeddings`, `cache/failures` |
| Ledger | `results/usage_ledger.jsonl` (no double-count on resume) |
| Max concurrency | **16** |
| Retries | 3 after first; statuses 429/500/502/503/529 + timeouts; backoff 1/2/4s; honor `Retry-After` |
| Optional | `max_rpm`, `spend_ceiling_usd` |
| In-flight dedupe | Same cache key shares one request |

---

## 14. Outcomes and statistics

### Primary outcome

**FDR@10%** — fraction of bugs for which at least one known triggering class appears in the top `k` classes, where:

```text
k = max(1, ceil(0.10 * N))
```

### Secondary

- FDR @ 1%, 2%, 5%, 20%, 50%, 100% (same `k` rule)
- MRR = mean(`1 / r_b`) with `r_b` = 1-based first-trigger rank  
- NFTR = `r_b / N`; report mean and median  
- APFD = `1 - (r_b / N) + 1/(2*N)`  
- Candidate recall@200  
- Cost and client-observed latency (cost preferred over noisy latency)

### Statistics (paired by bug)

- Primary contrast: **Jev vs BM25** on FDR@10% — **McNemar exact**; report both/neither/Jev-only/BM25-only  
- **10,000** paired bootstrap samples; 95% percentile CIs for Δ FDR@10%, Δ MRR, Δ APFD, Δ median NFTR  
- Secondary contrasts: Jev vs Embedding; Jev vs GPT-Nano  

### Project-level analysis

Report FDR@10% (and key secondaries) **separately per project** (Cli, Lang, Math, Jsoup, JacksonDatabind).

### Output precision (tables)

Rates: 4 decimal places; ranks: integers; USD: 6 decimal places.

---

## 15. Selected bug IDs

### Development (25)

```text
Cli-30, Cli-15, Cli-39, Cli-1, Cli-7,
Lang-9, Lang-27, Lang-3, Lang-15, Lang-35,
Math-25, Math-7, Math-87, Math-27, Math-100,
Jsoup-2, Jsoup-51, Jsoup-29, Jsoup-70, Jsoup-4,
JacksonDatabind-56, JacksonDatabind-95, JacksonDatabind-12,
JacksonDatabind-105, JacksonDatabind-28
```

### Evaluation (125)

```text
Cli-13, Cli-11, Cli-4, Cli-37, Cli-9, Cli-29, Cli-27, Cli-22, Cli-35, Cli-21,
Cli-3, Cli-10, Cli-24, Cli-34, Cli-8, Cli-38, Cli-25, Cli-32, Cli-12, Cli-17,
Cli-19, Cli-23, Cli-28, Cli-40, Cli-26,
Lang-5, Lang-33, Lang-60, Lang-13, Lang-16, Lang-6, Lang-36, Lang-7, Lang-40,
Lang-23, Lang-26, Lang-61, Lang-30, Lang-28, Lang-63, Lang-10, Lang-21, Lang-19,
Lang-43, Lang-50, Lang-49, Lang-17, Lang-12, Lang-47, Lang-41,
Math-86, Math-77, Math-33, Math-14, Math-67, Math-58, Math-43, Math-89, Math-13,
Math-104, Math-41, Math-93, Math-64, Math-42, Math-92, Math-17, Math-28, Math-72,
Math-69, Math-85, Math-10, Math-19, Math-71, Math-62, Math-96,
Jsoup-33, Jsoup-54, Jsoup-13, Jsoup-78, Jsoup-21, Jsoup-87, Jsoup-81, Jsoup-64,
Jsoup-86, Jsoup-69, Jsoup-16, Jsoup-50, Jsoup-75, Jsoup-85, Jsoup-23, Jsoup-72,
Jsoup-24, Jsoup-40, Jsoup-48, Jsoup-5, Jsoup-47, Jsoup-84, Jsoup-6, Jsoup-20, Jsoup-7,
JacksonDatabind-15, JacksonDatabind-49, JacksonDatabind-108, JacksonDatabind-100,
JacksonDatabind-77, JacksonDatabind-110, JacksonDatabind-47, JacksonDatabind-86,
JacksonDatabind-74, JacksonDatabind-51, JacksonDatabind-42, JacksonDatabind-97,
JacksonDatabind-72, JacksonDatabind-111, JacksonDatabind-35, JacksonDatabind-38,
JacksonDatabind-103, JacksonDatabind-87, JacksonDatabind-44, JacksonDatabind-62,
JacksonDatabind-93, JacksonDatabind-5, JacksonDatabind-66, JacksonDatabind-99,
JacksonDatabind-78
```

---

## 16. Required figures

1. **Fault detection vs test budget** — FDR at 1/2/5/10/20/50/100% for Random, BM25, Embedding, Jev, GPT-Nano  
2. **First-trigger rank CDF** — NFTR on x; fraction of bugs detected on y  
3. **Performance by project** — FDR@10% grouped by project  
4. **Quality vs cost** — mean reranking cost/bug vs FDR@10% for Embedding, Jev, GPT-Nano  

---

## 17. Deterministic failure-case selection

Only after aggregate evaluation results are frozen. Select:

- 10 largest Jev improvements over BM25  
- 10 largest Jev regressions versus BM25  

using `BM25 first-trigger rank − Jev first-trigger rank` (and the inverse for losses). **No hand-picking.** Classify each case into the phenomenon list in `overall.md` §41.

---

## 18. Open availability (pre-eval gate)

| ID | Detail |
| --- | --- |
| A-001 | **Jsoup-70** / `org.jsoup.integration.ConnectTest` — OpenRouter Cloudflare WAF blocks Jev System One when state contains `file://etc/passwd`. Accepted for development continuation. **Must resolve (TypeSafe / allowlist) or record a formal deviation before evaluation Jev scoring.** GPT-Nano accepts the same bytes. |

TypeSafe direct API was unavailable at provider selection; Cloudflare Jev was rejected until pin + price are verified.

---

## 19. How to decide success in advance

After evaluation metrics are computed on the **125** evaluation bugs only:

1. Compute FDR@10% for BM25, Jev, and GPT-Nano.  
2. Compute Jev and GPT-Nano mean `effective_prepaid_credits_usd` per bug (shortlist scoring).  
3. Jev is **practically successful** iff the criterion in §3 holds.  
4. H1–H3 are interpreted with the paired McNemar / bootstrap analyses in §14; practical success is the predetermined threshold test in §3.

---

## 20. File hash checklist

| Artifact | Role |
| --- | --- |
| `EXPERIMENT.md` | This human preregistration |
| `experiment.yaml` | Machine-readable lock |
| `results/phase6/experiment.json` | Loadable twin (`src.experiment_config`) |
| `prompts/jev/v1.json` | Final Jev prompt v1 |
| `prompts/gpt/v1.json` | Final GPT prompt v1 |
| `data/manifest.json` | Locked split + Defects4J commit |
| `results/pricing_snapshot.json` | Dated price basis |

Code defaults in `src/` must match these values; P6-06 verifies integrity before any evaluation run.
