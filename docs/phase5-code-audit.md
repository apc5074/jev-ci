# Phase 5 code audit

Scope: P5-01 through P5-08 implementation and existing development caches.
P5-09's full development run remains outstanding. No paid inference or evaluation
scoring was performed, and ranking accuracy improvement has not been measured.

## Fixed

- GPT normalized inference costs now include output tokens and apply platform fees
  to the full inference cost. The existing 23 GPT-Nano responses cost $0.00925885
  at their stored list rates, versus the previous input-only $0.00871260 (a 6.27%
  upward correction). Provider-reported charges remain separate. Historical ledger
  rows were preserved; recompute historical normalized costs from cache usage and
  stored prices when preparing the final report. See `results/phase5-code-audit.json`.
- Scheduler reservations are atomic before dispatch. Concurrent calls cannot all
  spend the same available estimate. Unknown failed-call charges retain reservations.
- Shortlist retries now belong to the scheduler, passing through its rate and spend
  gates on every attempt. Retry-After metadata survives the ranker boundary. Only
  configured HTTP statuses and timeouts retry; permanent transport failures stop.
- Duplicate keys share even already-completed futures throughout a batch, closing
  a race that could repeat fast paid calls.
- Ledger deduplication and append use an interprocess lock, preventing concurrent
  duplicate success records.
- Embedding batches deduplicate identical uncached texts and conserve the measured
  batch token total when distributing usage by character count. Per-item tokens
  remain estimates, labeled as such in cache metadata.
- Embedding response indices must form an exact input permutation. Cache validation
  checks vector dimensions and rejects zero vectors. Score caches reject booleans
  and invalid token counts; GPT rejects missing or invalid completion-token usage.
- Assembly rejects missing observed model identities and returns nonzero whenever
  any requested ranking fails, even if another method succeeds.
- Removed an unnecessary container-only manifest load from a host-compatible test.

## Before the Phase 6 freeze

1. Prove immutable model identity. Existing GPT-Nano records use canonical cache ID
   `gpt-5.4-nano-2026-03-17` but both the OpenRouter request and response use an
   undated alias. Existing cache metadata alone does not establish that snapshot.
   GPT-4.1-Nano responses also report an alias, despite dated requests. Jev's
   response has a dated version, but the requested route is still an alias.
   Verify provider pinning or select a route with a provable immutable request;
   record the decision and regenerate affected scores if identity changes.
2. The spending gate uses estimates per batch. It cannot guarantee an absolute
   invoice ceiling when actual tokens exceed estimates. Add a run-wide controller
   and account-level limits for the full run; include output-token allowances.
3. Complete attempt-level failure accounting and cache-to-ledger reconciliation.
   A crash between cache persistence and ledger append can leave a successful
   cache entry without a ledger row. Use cache usage as a reconciliation source;
   do not repeat inference just to repair accounting. Failed or timed-out requests
   may be billed even when no usable score is received.
4. Keep undiscounted list-price comparisons distinct from provider cache discounts
   and actual cash spend. Existing historical ledger entries were not rewritten.
5. Finish the planned all-25-development coverage and leakage audit before making
   performance claims. Preserve the fixed shortlist, shared semantic rubric,
   representations, and untouched evaluation split during development decisions.

## Validation

`python3 -m unittest discover -s tests -p 'test_phase5*.py' -q`

81 tests ran successfully, with one existing environment-dependent skip. Added
regressions exercise concurrent budget reservations, fast-key deduplication,
concurrent ledger writes, retry gates, output-token costs, embedding token
conservation, and partial-assembly failure. Existing 115 Jev/GPT success caches
passed strengthened score validation. `git diff --check` passed.
