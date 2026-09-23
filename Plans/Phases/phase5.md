# Phase 5 tickets — Semantic rankers, baselines, and cost control

**Phase goal:** Produce complete, cached development rankings for Random, BM25, Embedding, BM25 → Jev, and BM25 → GPT-5.4 nano. Choose a Jev access route using verified total cost and the ability to pin the underlying model, then keep that route fixed for the evaluation. Phase 5 uses only the 25 development bugs; Phase 6 reviews and freezes the finished design.

**Source of truth:** [../overall.md](../overall.md), sections 15–23, 30–31, and 35–37; [../phases.md](../phases.md), Phase 5. Phase 4 supplies full BM25 rankings and immutable ordered top-`min(200,N)` candidate lists. The Jev and GPT model states must use the **same saved patch and compact test representations** from Phase 3. Do not use known trigger labels in a request.

## Current Jev access and cost finding (checked 2026-09-22)

| Route | What the published source establishes | Decision for this phase |
| --- | --- | --- |
| [TypeSafe direct API](https://typesafe.ai/blog/introducing-system-one-models-and-jev) | Jev input is listed at **$0.042 per million tokens**; output is free. [The API documents model discovery](https://api.typesafe.ai/docs) through `GET /v1/models`. | **Default cheapest verified route** if account access and a stable model ID are available. Confirm the account's actual rate before the first call. |
| [OpenRouter Jev 1.13](https://openrouter.ai/typesafe/jev-1.13/api) | The displayed inference rate is also **$0.042 per million input tokens**, output free. [Standard credit purchases carry a 5.5% platform fee](https://openrouter.ai/pricing). | Working alternative if it exposes the same pinned model and Noul response. Include credit fees in cash-cost comparisons. |
| [Cloudflare `typesafe/jev`](https://developers.cloudflare.com/ai/models/typesafe/jev/) | Jev is listed as a **third-party** model; public docs send pricing to the Cloudflare dashboard. [AI Gateway core features are free](https://developers.cloudflare.com/ai-gateway/reference/pricing/), while [Unified Billing credit purchases carry a 5% fee](https://developers.cloudflare.com/ai-gateway/features/unified-billing/). | Investigate account-specific Jev price, eligibility, and model pinning. **Do not infer that Jev inference is free** from the free Gateway or Workers AI allowance. Use it for the final study only if effective cost and exact-model reproducibility are verified. |

The [OpenAI Docs model page](https://developers.openai.com/api/docs/models/text-embedding-3-small) lists `text-embedding-3-small` at $0.02 per million input tokens. The [GPT-5.4 nano page](https://developers.openai.com/api/docs/models/gpt-5.4-nano) confirms the `gpt-5.4-nano-2026-03-17` snapshot, structured outputs, and `reasoning.effort=none`. These are planning snapshots, not historical prices for later result calculation; save a fresh dated pricing snapshot when development calls begin.

**Cost interpretation:** Keep three numbers distinct: published list-price inference cost, any platform/credit-purchase fees, and actual cash paid after promotional credits or free allowances. A promotional zero-dollar bill does not make inference intrinsically free. The preregistered Jev-vs-GPT cost comparison should use measured token usage and the frozen price basis, with actual cash outlay shown separately.

Tickets are ordered by dependency. Each must leave a reviewable artifact and a pass/fail check. No provider switch, model alias, prompt edit, or batching shortcut may silently change the experiment.

## P5-01 — Verify Jev routes and choose one provider before scoring ✅ COMPLETE

**Depends on:** Phases 1–4.

**Status:** Complete. Comparison + decision in [`docs/jev-provider-decision.md`](../../docs/jev-provider-decision.md); [`src/jev_providers.py`](../../src/jev_providers.py) / [`scripts/verify_jev_providers.py`](../../scripts/verify_jev_providers.py); dated [`results/pricing_snapshot.json`](../../results/pricing_snapshot.json) + [`results/jev_provider_decision.json`](../../results/jev_provider_decision.json). **Selected:** OpenRouter `typesafe/jev-1.13` (observed `typesafe/jev-1.13-20260917`); TypeSafe direct unavailable. Live probe **passed** (`ready_for_scoring=True`). Cloudflare rejected for eval until pin+price verified.

**Work**

- Inspect current TypeSafe direct, OpenRouter, and Cloudflare account terms. For each available route record: exact callable model ID and returned model version, Noul API/schema support, per-input/output-token rates, platform fees, free credits/allowances actually applicable to Jev, request limits, and how usage and request IDs are returned. Link dated primary sources and note account-only evidence separately.
- Make one small **development-only** schema/usage probe per viable route, after estimating its possible charge. Verify that the route can send the required `state` and `would_detect_regression` Noul and return a numeric `noul` score in `[0,1]`. Do not use probes as benchmark data.
- Determine whether Cloudflare's `typesafe/jev` route permits an immutable underlying Jev model pin. Its documented response example names a concrete version, but a response name alone does not prove future requests will use that version. Reject an alias-only route for final evaluation if it cannot guarantee the frozen model.
- Compare effective cost for the expected development and evaluation workload using representative **measured input tokens** from probes, including platform fees and any enforceable free allowance. Prefer the lowest-cost route that supports the same stable Jev model and full response accounting; if costs tie, prefer TypeSafe direct for simpler provenance.
- Record the selected provider, endpoint, exact model ID, observed version, rate-limit plan, price evidence, and decision date. Do not mix Jev providers within the evaluation. If direct TypeSafe access is unavailable, use the cheapest qualified alternative and document why.

**Deliverables:** A provider comparison and decision record, a dated `pricing_snapshot.json`, and the saved TypeSafe `GET /v1/models` response at `results/typesafe_models.json` when direct access exists.

**Acceptance:** The chosen route is demonstrably callable, returns the required typed probability and usage, has a stable model identity, and has a documented effective cost. No claim of free Cloudflare Jev usage appears without account-specific evidence.

## P5-02 — Build a shared request, cache, and usage ledger ✅ COMPLETE

**Depends on:** P5-01 for provider identity; Phase 3 representations.

**Status:** Complete. [`src/semantic_cache.py`](../../src/semantic_cache.py); docs [`docs/cache-ledger.md`](../../docs/cache-ledger.md); checks in [`tests/test_phase5_semantic_cache.py`](../../tests/test_phase5_semantic_cache.py). Canonical cache keys, atomic `cache/{jev,gpt,embeddings,failures}/`, append-only `results/usage_ledger.jsonl` with no double-count on resume; list-price vs platform fee vs actual cash split.

**Work**

- Define canonical serialization for the exact model-visible `state` and `question`, including prompt version. Key each semantic request by SHA-256 of provider, model ID, prompt version, serialized state, and serialized question, with unambiguous separators or structured serialization.
- Cache successful scores under `cache/jev` and `cache/gpt`; cache embeddings under `cache/embeddings` keyed by model and exact input text. Use atomic writes and read validation so interrupted processes cannot leave false cache hits.
- Record bug ID and class only as cache metadata; never insert them into model-visible state. Store score/vector, model/version, input/output tokens, latency, provider request ID, timestamp, input hash, and price basis. Store failed attempts separately with status/error and retry count.
- Reuse exact successful cache entries before any paid request, including after a restart. A changed provider/model/prompt/representation must create a different key. Validate that returned usage and score fields are well formed before treating a call as successful.
- Separate provider-billed token cost from platform fees and promotional credit effects so Phase 8 can calculate both normalized inference cost and actual cash outlay.

**Deliverables:** Shared cache/ledger helpers, schemas, and recovery checks.

**Acceptance:** Repeating a completed request makes no network call; corrupt or mismatched entries are rejected; failures cannot be mistaken for valid scores; a resumed run preserves previous usage records without double counting.

## P5-03 — Implement the seeded Random baseline ✅ COMPLETE

**Depends on:** Phase 2 manifest and Phase 3 test inventories.

**Status:** Complete. [`src/random_baseline.py`](../../src/random_baseline.py); docs [`docs/random-baseline.md`](../../docs/random-baseline.md); checks in [`tests/test_phase5_random_baseline.py`](../../tests/test_phase5_random_baseline.py). **Index basis: zero-based.** Evaluation seed `1337 + evaluation_bug_index`; development `1001337 + development_bug_index` (disjoint). Contracts at `results/random/<slug>.json` for all 25 development bugs; full permutations regenerate on demand.

**Work**

- Produce 1,000 independent full-suite permutations per bug. For final evaluation use `random.Random(1337 + evaluation_bug_index)` with the evaluation index defined by manifest order and recorded as zero- or one-based before Phase 6.
- Define a deterministic development index convention without changing the final evaluation seed rule. Never use positive labels to generate permutations.
- Preserve the permutation seeds or a reproducible generator contract. Phase 8 will average metrics over the 1,000 rankings rather than selecting a favorable permutation.

**Deliverables:** Random baseline module and development permutation artifacts or a deterministic regeneration path.

**Acceptance:** Each generated permutation contains every test class exactly once, repeated runs reproduce the same 1,000 permutations, and the evaluation index convention is ready for preregistration.

## P5-04 — Implement the full-suite Embedding baseline ✅ COMPLETE

**Depends on:** P5-02 and Phase 3 representations.

**Status:** Complete. [`src/embeddings.py`](../../src/embeddings.py); docs [`docs/embeddings.md`](../../docs/embeddings.md); checks in [`tests/test_phase5_embeddings.py`](../../tests/test_phase5_embeddings.py). Model `text-embedding-3-small` via OpenRouter (`openai/text-embedding-3-small`) with OpenAI-direct fallback. Over-limit rule `fail_closed_no_truncate_v1` (8192 tokens, never truncate). Full rankings for all 25 development bugs at `results/embeddings/<slug>.json`; vectors in `cache/embeddings/`.

**Work**

- Embed the compact regression patch representation and **every** compact test representation with `text-embedding-3-small`; do not restrict embeddings to BM25's top 200 or combine similarities with BM25 scores.
- Cache by exact model/input text and reuse an identical test embedding when possible. Validate returned dimensions, finiteness, and usage. Handle an input exceeding the provider's supported limit through a documented, preregistered rule; do not silently truncate during evaluation.
- Rank by cosine similarity, descending, with an explicit stable FQCN tie-break. Save complete scores, token usage, and ranking provenance.

**Deliverables:** `src/embeddings.py`, cached development vectors, and one full Embedding ranking per development bug.

**Acceptance:** Every development test class appears once in its Embedding ranking; scores are finite and reproducible from cached vectors; no BM25 feature enters the score.

## P5-05 — Implement the one-pair Jev decision client ✅ COMPLETE

**Depends on:** P5-01 and P5-02.

**Status:** Complete. [`src/jev_ranker.py`](../../src/jev_ranker.py); docs [`docs/jev-ranker.md`](../../docs/jev-ranker.md); checks in [`tests/test_phase5_jev_ranker.py`](../../tests/test_phase5_jev_ranker.py). OpenRouter `typesafe/jev-1.13` (observed `…-20260917`); score=`answer.noul`∈[0,1]; captured proof at [`results/jev_captured_request.json`](../../results/jev_captured_request.json); Cli-30 shortlist (23) cached under `cache/jev/`.

**Work**

- Use the exact Phase 3 patch and test representation strings in `state = {"code_change": ..., "candidate_test": ...}`. Send exactly one test class per request, with question ID `would_detect_regression`, Noul type, and the prompt/true/false criteria in section 18 of `overall.md`.
- Discover and record the stable Jev model through TypeSafe `GET /v1/models` when using the direct API. For another route, map its transport model name to a verified immutable underlying Jev version; reject `jev-latest` or an unverified moving alias for final evaluation.
- Parse `answer.noul` as the ranking score; require a finite number in `[0,1]`. Do not threshold, substitute a default, or derive a score from an unrelated confidence field.
- Keep a provider-specific transport adapter only where schemas differ; the semantic state, question text, and one-pair granularity must remain identical. Include the selected provider and exact model in the cache key.
- Make secrets runtime-only and redact authorization headers from logs/errors.

**Deliverables:** `src/jev_ranker.py`, versioned Jev question text, provider adapter if needed, and cached development responses.

**Acceptance:** A development call returns a validated Noul probability and usage record. A captured request proves only one patch/test-class pair was sent and contains no trigger labels or bug-status words added by the pipeline.

## P5-06 — Implement the GPT-5.4 nano comparison client ✅ COMPLETE

**Depends on:** P5-02.

**Status:** Complete. [`src/gpt_ranker.py`](../../src/gpt_ranker.py); docs [`docs/gpt-ranker.md`](../../docs/gpt-ranker.md); checks in [`tests/test_phase5_gpt_ranker.py`](../../tests/test_phase5_gpt_ranker.py). **Primary:** `gpt-5.4-nano-2026-03-17` / `reasoning.effort=none` (GPT-Nano). **Also scored:** `gpt-4.1-nano-2025-04-14`, `gpt-4o-mini-2024-07-18`, `gpt-5.6-luna` / GPT-Luna (same prompt/schema/state; separate cache keys). Registry [`results/gpt_comparison_models.json`](../../results/gpt_comparison_models.json); capture [`results/gpt_captured_request.json`](../../results/gpt_captured_request.json); Cli-30 shortlist cached under `cache/gpt/`.

**Work**

- Use the exact `gpt-5.4-nano-2026-03-17` snapshot, `reasoning.effort=none`, and a structured response with one `probability` number in `[0,1]`. Use one request per BM25-shortlisted test class and the same saved patch/test strings and semantic rubric Jev sees.
- Store the final prompt and schema with a prompt version. Do not request or save chain-of-thought; reject malformed or out-of-range probabilities rather than coercing them.
- Capture the provider's actual input, cached-input, and output token usage, response/request ID, latency, and price basis for later cost comparison. Record API errors separately.
- **Extension (this ticket):** also run additional pinned comparison models (`gpt-4.1-nano-2025-04-14`, `gpt-4o-mini-2024-07-18`, `gpt-5.6-luna`) under the identical contract for Phase 6 review; primary headline method remains GPT-Nano.

**Deliverables:** `src/gpt_ranker.py`, versioned prompt/schema, and cached development responses.

**Acceptance:** A development call returns exactly one validated probability with usage. Its model-visible patch/test inputs match Jev's byte-for-byte, and it uses the fixed snapshot and reasoning setting.

## P5-07 — Add bounded concurrency, retries, and spend controls ✅ COMPLETE

**Depends on:** P5-02, P5-05, and P5-06.

**Status:** Complete. [`src/semantic_scheduler.py`](../../src/semantic_scheduler.py); docs [`docs/semantic-scheduler.md`](../../docs/semantic-scheduler.md); checks in [`tests/test_phase5_scheduler.py`](../../tests/test_phase5_scheduler.py). Cap **16** concurrent; retries **429/500/502/503/529** + timeouts with **1/2/4s** (+ `Retry-After`); optional `spend_ceiling_usd` / `max_rpm`; in-flight cache-key dedupe. Wired into Jev/GPT `score_shortlist`.

**Work**

- Limit Jev and GPT to at most 16 concurrent requests each, while also respecting each provider's request/token-rate limits. A free-tier route with a lower limit should queue or pause, not exceed the allowance and silently switch providers.
- Retry only 429, 500, 502, 503, 529, and network timeouts, with at most three retries after the first attempt and 1/2/4-second backoff. Respect a longer `Retry-After` when supplied. Persist the final failure and leave its candidate unscored.
- Before a development run, estimate remaining uncached calls and token spend; offer a configurable hard spending ceiling that stops before an unexpectedly large charge. Record actual usage after each completed request. Keep this control separate from the scientific score.
- Deduplicate in-flight requests with the same cache key. On restart, schedule only missing valid scores. Never assume provider-side or Gateway caching replaces the experiment's own exact request cache.

**Deliverables:** Shared asynchronous scheduler/retry helper, spend estimate/report, and failure/recovery checks.

**Acceptance:** Simulated 429/timeouts follow the specified retries, concurrency never exceeds 16 per model, a failed request does not create a score, and resuming a partial batch does not repeat successful paid calls.

## P5-08 — Assemble complete semantic rankings from one shortlist ✅ COMPLETE

**Depends on:** P5-04 through P5-07 and Phase 4 candidate files.

**Status:** Complete. [`src/assemble_rankings.py`](../../src/assemble_rankings.py) (lazy re-exports on [`src/ranking.py`](../../src/ranking.py)); docs [`docs/assemble-rankings.md`](../../docs/assemble-rankings.md); checks in [`tests/test_phase5_assemble.py`](../../tests/test_phase5_assemble.py). Shared Phase-4 shortlist only; prefix sort score↓ / BM25-rank↑; BM25 tail unchanged; fail-closed on missing scores. Development proof: Cli-30 under `results/semantic/` (full 25 deferred to P5-09).

**Work**

- Load the **same saved** BM25 top-`K` IDs and ordered-list hash for Jev and GPT. Do not let either client regenerate, filter, or independently reorder its candidate set before scoring.
- For each model, require one valid score for every shortlisted ID. Sort that prefix by descending model probability and then ascending original BM25 rank; append all remaining tests in original BM25 order.
- Preserve the complete BM25 and Embedding rankings, Random permutations, per-candidate raw scores, shortlist hash, and model/provider/prompt versions. Keep development artifacts clearly separated from evaluation artifacts.
- Stop assembly if any score is missing, nonfinite, associated with another input hash, or produced by a different underlying model version.

**Deliverables:** Shared `src/ranking.py` assembly logic and full Jev/GPT development rankings.

**Acceptance:** Each of the five systems covers exactly the full test-class set for every development bug; Jev/GPT score the identical top-`K` set; both tails are byte-for-byte BM25 order.

## P5-09 — Run and audit all 25 development bugs ✅ COMPLETE (1 unresolved)

**Depends on:** P5-01 through P5-08.

**Status:** Complete with one documented availability gap. Runners [`scripts/run_jev.py`](../../scripts/run_jev.py), [`scripts/run_gpt.py`](../../scripts/run_gpt.py), [`scripts/run_baselines.py`](../../scripts/run_baselines.py); audit [`src/audit_phase5.py`](../../src/audit_phase5.py) / [`scripts/audit_phase5.py`](../../scripts/audit_phase5.py); docs [`docs/phase5-run.md`](../../docs/phase5-run.md); reports [`results/audit-phase5.json`](../../results/audit-phase5.json), [`results/phase5_usage_report.json`](../../results/phase5_usage_report.json). **24/25** bugs have all five systems; **Jsoup-70 Jev** blocked by OpenRouter Cloudflare WAF on `file://etc/passwd` in `ConnectTest` (GPT-Nano complete). Cache-only assembly proof passed. No evaluation bugs scored. Handoff: [`docs/phase5-handoff.md`](../../docs/phase5-handoff.md).

**Work**

- Add/document development commands such as `scripts/run_jev.py`, `scripts/run_gpt.py`, and a baseline runner. Restrict the pre-freeze run to the 25 development IDs from the manifest.
- Complete every required score, vector, and ranking. Summarize calls, cache hits, failures, input/output tokens, provider fees, actual cash spend, and client-observed latency. Save a dated pricing snapshot rather than relying on later website prices.
- Audit label leakage, cache-key stability, model and provider IDs, Jev/GPT shortlist equality, complete-score gates, full-ranking permutations, and reproducible cached reruns. Inspect development behavior for implementation and prompt-understanding problems; Phase 6 governs the single allowed Jev prompt revision.
- Test a cache-only rerun with credentials unavailable or network disabled. It must recreate development rankings without paid calls.
- Hand Phase 6 the provider comparison, exact prompts and model IDs, price basis, cached raw scores, all five rankings, audit results, and any unresolved availability issue.

**Deliverables:** Complete development outputs and a short audit/usage report.

**Acceptance:** All 25 development bugs have five complete ranking systems and valid cached semantic scores. A cache-only rerun succeeds, and no evaluation bug has been scored.

## Phase completion gate

Phase 5 is implemented when the cheapest **verified, reproducible** Jev route has been selected, all five systems run end to end on the development set, every paid result is cached with usage, and ranking integrity passes. Cloudflare is used only if its Jev-specific price and stable underlying model can be verified; a free Gateway account alone does not satisfy that test. Phase 6 can then review the development findings and freeze the provider, prompts, costs, and methods before evaluation.
