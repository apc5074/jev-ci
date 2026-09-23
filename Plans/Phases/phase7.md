# Phase 7 tickets — Execute the frozen evaluation

**Phase goal:** Run the preregistered pipeline once on all 125 evaluation bugs, retain every score and complete ranking, and seal the raw outputs before calculating aggregate results. Phase 7 executes the Phase 6 design; it does not adjust prompts, retrieval, models, candidate size, metrics, or success criteria in response to evaluation data.

**Source of truth:** [../overall.md](../overall.md), sections 4–5, 8–23, 35–38, and 44; [../phases.md](../phases.md), Phase 7; and the tagged `EXPERIMENT.md` / `experiment.yaml` from Phase 6. Phase 1–5 code and the Phase 2 manifest are inputs. Resolve operational failures by resuming or fixing an implementation defect with a recorded deviation; do not silently change a frozen method.

Tickets are ordered by dependency. Each has a concrete artifact and an exit check. Do not compute or inspect aggregate FDR, candidate recall, or method-comparison results until P7-09 seals the raw results.

## P7-01 — Verify the freeze and prepare an evaluation run ✅ COMPLETE

**Depends on:** Phase 6 completion gate.

**Status:** Complete. Preflight [`scripts/run_evaluation_preflight.py`](../../scripts/run_evaluation_preflight.py) / [`src/evaluation_preflight.py`](../../src/evaluation_preflight.py); record [`docs/phase7-preflight.md`](../../docs/phase7-preflight.md) + [`results/phase7/preflight.json`](../../results/phase7/preflight.json); run [`results/phase7/run.json`](../../results/phase7/run.json); append-only log [`results/phase7/execution.log.jsonl`](../../results/phase7/execution.log.jsonl). **PASS** — tag `experiment-v1` → `edc70bacd23f2fc5f511ef4d97a33376e7b20bf8`; 125 evaluation IDs queued; frozen prompt/config/manifest hashes match tag; evaluation namespace empty; OpenRouter Jev probe pinned; spend ceiling recorded. Evaluation runners call `assert_evaluation_run_ready()` via `require_manifest_membership(..., allow_evaluation=True)`.

**Work**

- Verify that `experiment-v1` exists, resolves to the reviewed commit, and matches the configuration/prompt hashes in the Phase 6 handoff. Record the freeze commit SHA as the immutable `experiment_commit` for every output.
- Verify the Phase 2 manifest and its 125 ordered evaluation IDs, five projects, Defects4J 3.0.1 commit, container toolchain, and empty/appropriate evaluation output namespace. Reject a changed split or an unrecorded code/configuration change.
- Confirm access to the frozen embedding, Jev, and GPT models/providers, account limits, credentials, cache volumes, and pricing snapshot. Check that the selected Jev route still reports the pinned underlying model, rather than a moving alias.
- Estimate uncached call counts and likely token spend using development usage, then set the recorded spending ceiling and execution schedule. This is an operational guard, not a change to the sample, model, or candidate count.
- Create one run identifier and an append-only execution log. Define where completed artifacts, failed attempts, and the final audit will live; protect development outputs from being overwritten.

**Deliverables:** Evaluation preflight record, run ID, and verified freeze/configuration references.

**Acceptance:** All frozen inputs resolve; exactly 125 evaluation IDs are queued; the runner refuses to start if the tag, model version, manifest, or config does not match. No evaluation output is produced during a failed preflight.

## P7-02 — Extract and validate all evaluation examples ✅ COMPLETE

**Depends on:** P7-01.

**Status:** Complete. `prepare_dataset --split evaluation --allow-evaluation` produced **125/125** complete examples; integrity audit [`scripts/audit_phase3.py --split evaluation`](../../scripts/audit_phase3.py) **PASS** ([`results/phase7/extraction_audit.json`](../../results/phase7/extraction_audit.json), [`docs/phase7-extraction.md`](../../docs/phase7-extraction.md)). Summary [`results/prepare_dataset-evaluation.json`](../../results/prepare_dataset-evaluation.json) stamped with `experiment_commit=edc70bac…`. Source missing 0; patch truncations 2; representation truncations 133 (recorded, no exclusions). `JacksonDatabind-62` recovered after Defects4J export timeout retry.

**Work**

- Run the validated Phase 3 checkout/extraction pipeline for the 125 evaluation IDs, using `Bf` as base and `Bb` as proposed change. Reuse its exact diff direction, trigger parsing, source lookup, source-window selection, and character caps.
- Save raw exports, fixed-base test inventory and source map, known triggering classes in private label artifacts, patch/test representations, and missing-source/truncation metadata. Never add labels or revision-status fields to model-visible state.
- Validate each example against the manifest and pinned Defects4J checkout: patch exists and points fixed → buggy; test IDs are unique; trigger classes belong to `tests.all` unless a documented metadata exception applies; every test class has one representation, including the FQCN fallback.
- Resume by validating existing example hashes and provenance before reuse. Mark partial examples as incomplete and retry them; never omit a hard bug or substitute data from another revision.
- Record counts and extraction failures without ranking-related outcome summaries. A metadata anomaly requires documented source evidence and a decision consistent with the frozen rules.

**Deliverables:** 125 complete evaluation examples under `data/bugs`, `data/patches`, and `data/tests`, plus an extraction audit.

**Acceptance:** All 125 examples pass Phase 3 integrity checks and can be loaded from saved artifacts. Missing test source and truncation are recorded, with no excluded bug and no model-visible label leakage.

## P7-03 — Generate BM25 rankings and freeze candidate lists ✅ COMPLETE

**Depends on:** P7-02.

**Status:** Complete. `run_candidates --split evaluation --allow-evaluation` wrote **125/125** full BM25 rankings + sealed shortlists (`K=min(200,N)`), each stamped with `experiment_commit` / `run_id`. Integrity audit [`scripts/audit_phase4.py --split evaluation`](../../scripts/audit_phase4.py) **PASS** ([`results/phase7/candidates_audit.json`](../../results/phase7/candidates_audit.json), [`docs/phase7-candidates.md`](../../docs/phase7-candidates.md)). Summary [`results/run_candidates-evaluation.json`](../../results/run_candidates-evaluation.json). Trigger recall deferred to Phase 8.

**Work**

- Run the frozen Phase 4 tokenizer, query/document construction, BM25 parameters, and tie-breaks on every evaluation example. Rank the **entire** fixed-base test suite; validate `N` unique IDs and finite scores.
- Set `K=min(200,N)` and save `data/candidates/<project>_<bug>.json` as the exact ordered top-`K` prefix. Save the full BM25 scores/ranking separately with input hashes, config hash, run ID, and freeze commit.
- Hash and seal each candidate file before any Jev/GPT call. Both semantic clients must read the same file and verify its ordered-list hash; neither may regenerate a different shortlist.
- Resume only from matching, complete artifacts. A changed input or scoring configuration is an audit failure, not an invitation to quietly replace a shortlist.
- Do not inspect trigger presence in the shortlist or increase `K` based on it. Candidate recall is calculated in Phase 8 from the sealed files.

**Deliverables:** 125 complete BM25 rankings and 125 sealed top-`K` candidate files.

**Acceptance:** Every shortlist equals the prefix of its complete BM25 ranking, each file records the frozen configuration and commit, and the same IDs are ready for both semantic rankers.

## P7-04 — Generate full-suite embedding rankings ✅ COMPLETE

**Depends on:** P7-02 and P7-03 (for the required execution order, not for embedding scores).

**Status:** Complete. `run_embeddings --split evaluation --allow-evaluation` produced **125/125** full-suite Embedding rankings stamped with `experiment_commit` / `run_id`. Audit [`scripts/audit_embeddings.py --split evaluation`](../../scripts/audit_embeddings.py) **PASS** ([`results/phase7/embeddings_audit.json`](../../results/phase7/embeddings_audit.json), [`docs/phase7-embeddings.md`](../../docs/phase7-embeddings.md)). Summary [`results/embeddings_summary-evaluation.json`](../../results/embeddings_summary-evaluation.json). Model `text-embedding-3-small`; independent of BM25 shortlists.

**Work**

- Embed each saved compact regression patch and **all** compact test representations using the frozen `text-embedding-3-small` configuration. Reuse valid exact-input cached vectors; make only missing requests.
- Verify dimensions, finite vector values, input hashes, model identity, and token usage. Handle provider-limit failures using only the preregistered rule; do not silently truncate or remove a test.
- Compute cosine similarity for every class, apply the frozen tie-break, and save scores and a complete embedding ranking. Keep it independent of BM25 candidates/scores.
- Record per-request usage, latency, provider IDs, and cache hits for cost accounting.

**Deliverables:** Cached evaluation embeddings and 125 complete Embedding rankings.

**Acceptance:** Every evaluation test class appears exactly once in its embedding ranking, all similarity scores are finite, and ranking can be regenerated from cached vectors without a paid call.

## P7-05 — Score the frozen shortlist with Jev ✅ COMPLETE (accepted A-001 gaps)

**Depends on:** P7-03 and the Phase 6 provider/prompt freeze.

**Status:** Complete with documented availability gaps. `run_jev --split evaluation` scored **13402/13414** shortlist pairs (**113/125** bugs fully complete). **12** Jsoup pairs blocked by OpenRouter WAF on `file://etc/passwd` (ConnectTest / UrlConnectTest) — A-001 evaluation extension; no representation rewrite. `Math-89` HTTP 520s retried successfully. Audit [`scripts/audit_jev.py`](../../scripts/audit_jev.py); report [`docs/phase7-jev.md`](../../docs/phase7-jev.md); diagnosis [`results/phase7/jev_missing_diagnosis.json`](../../results/phase7/jev_missing_diagnosis.json). Summary [`results/jev_scoring_summary-evaluation.json`](../../results/jev_scoring_summary-evaluation.json).

**Work**

- For each candidate, send exactly one saved patch/test pair with the final `would_detect_regression` Noul question. Use the frozen provider, exact underlying Jev model, prompt `v1`, and Phase 5 cache key.
- Read candidate IDs only from the sealed Phase 4 shortlist. Enforce at most 16 concurrent requests and the specified retry statuses, three retries, and 1/2/4-second backoff, further respecting provider rate limits.
- Cache every successful typed `noul` score, usage, latency, request ID, timestamp, model version, and input hash. Persist failures separately. Retry/resume missing scores without issuing a paid call again for any exact valid cache hit.
- Pause on unexpected model/version drift, malformed output, spend ceiling, or a nonretryable provider error. Record the incident and resume under the same design once resolved; do not substitute `0.5`, drop a candidate, or switch providers mid-evaluation.
- Check per-bug score completeness before marking it Jev-ready, without examining trigger ranks or aggregate performance.

**Deliverables:** Complete cached Jev score set for all evaluation shortlist pairs and a usage/failure ledger.

**Acceptance:** Each shortlisted test has exactly one valid score in `[0,1]` from the frozen Jev model and prompt; every successful paid response has a matching cache entry and accounting record. *(Excepted: 12 WAF-blocked pairs above.)*

## P7-06 — Score the identical shortlist with GPT-5.4 nano ✅ COMPLETE

**Depends on:** P7-03 and the Phase 6 GPT prompt/model freeze. Can execute after P7-05 or independently once the shortlist is sealed.

**Status:** Complete. `run_gpt --split evaluation --model primary` scored **13414/13414** pairs (**125/125** bugs). Audit [`scripts/audit_gpt.py`](../../scripts/audit_gpt.py) **PASS** ([`results/phase7/gpt_audit.json`](../../results/phase7/gpt_audit.json), [`docs/phase7-gpt.md`](../../docs/phase7-gpt.md)). Summary [`results/gpt_scoring_summary-evaluation.json`](../../results/gpt_scoring_summary-evaluation.json). Same sealed shortlists/state as Jev; no WAF gaps on GPT.

**Work**

- Use the same ordered IDs and saved patch/test strings used by Jev, one pair per request. Call `gpt-5.4-nano-2026-03-17` with `reasoning.effort=none`, the frozen semantic rubric, and a structured `probability` response.
- Apply the same 16-concurrent cap, retry policy, exact cache reuse, failure persistence, and spend guard. Validate that each probability is finite and in `[0,1]`; do not coerce malformed answers.
- Record input/cached-input/output tokens, latency, provider request ID, timestamp, prompt/schema version, and exact-input hash. Keep actual cash spend and list-price inference cost distinguishable.
- Compare the final ordered shortlist hash and representation hashes with Jev's input ledger before declaring either model complete.

**Deliverables:** Complete cached GPT score set for all evaluation shortlist pairs and a usage/failure ledger.

**Acceptance:** Each shortlisted test has one valid GPT score; the candidate ID set and order and patch/test bytes match Jev's inputs; rerunning the scorer only reads cache.

## P7-07 — Assemble all five full rankings ✅ COMPLETE

**Depends on:** P7-03 through P7-06.

**Status:** Complete. Random **125/125**; BM25/Embedding retained; GPT-Nano assembled **125/125**; Jev assembled **113/125** with **12** A-001 WAF gaps omitted (fail-closed, no invented scores). Runner [`scripts/assemble_evaluation.py`](../../scripts/assemble_evaluation.py); record [`results/phase7/assembly.json`](../../results/phase7/assembly.json); report [`docs/phase7-assembly.md`](../../docs/phase7-assembly.md).

**Work**

- Generate Random's 1,000 seeded full-suite permutations per bug using the frozen evaluation-index convention; preserve seeds/permutations or the exact reproducible state needed by Phase 8.
- Retain the complete BM25 and Embedding rankings. For Jev and GPT separately, sort the scored top-`K` candidates by descending score and original BM25 rank for ties, then append the unchanged BM25 tail.
- Reject assembly while any semantic score is absent, invalid, or associated with a different shortlist/input/model/prompt hash. Never fill a gap with a guessed probability.
- Save every complete ranking with 1-based ranks, method name, bug ID, split, `N`, input/config hashes, run ID, and freeze commit. Keep deterministic ordering and atomic writes.

**Deliverables:** Five complete systems for each of 125 bugs: Random, BM25, Embedding, Jev, and GPT rankings, with Random represented by its 1,000 permutations.

**Acceptance:** Each nonrandom ranking contains exactly the `N` unique classes from `tests.all`; each Random permutation does too. Jev/GPT tails match BM25 order exactly. No ranking was assembled from incomplete scores. *(Jev absent for 12 documented WAF bugs.)*

## P7-08 — Export normalized raw predictions and provenance ✅ COMPLETE

**Depends on:** P7-07.

**Status:** Complete. Exporter [`src/export_predictions.py`](../../src/export_predictions.py) / [`scripts/export_predictions.py`](../../scripts/export_predictions.py); report [`docs/phase7-predictions.md`](../../docs/phase7-predictions.md); artifacts `results/predictions.jsonl` (72,401 lines) + [`results/phase7/raw_result_index.json`](../../results/phase7/raw_result_index.json). Derived from sealed rankings/caches only (no API calls). Jev omitted for 12 accepted A-001 gaps; semantic tails marked `score_applicable=false`.

**Work**

- Write `results/predictions.jsonl` from saved cache/ranking artifacts, not fresh API responses. Include the raw BM25 and Embedding scores for all classes, Jev/GPT scores for shortlisted classes, model/provider/prompt/input identifiers, token usage, cost basis, and latency. Record which scores are inapplicable outside the semantic shortlist rather than inventing values.
- Store the complete ranking files, Random seeds/permutations, extraction metadata, pricing snapshot, and a result index containing file hashes. Every result artifact should identify the freeze commit, directly or through an integrity-checked sidecar index.
- Validate JSONL schema, unique `(bug, method, test_class)` keys where applicable, line counts implied by saved rankings, finite scores, and agreement with cache entries. Make the export deterministic and atomic.
- Keep known trigger labels in their separate source-of-truth artifacts. Do not write `results/metrics.csv`, statistics, headline tables, or figures in this phase.

**Deliverables:** `results/predictions.jsonl`, complete ranking files, and a hashed raw-result index.

**Acceptance:** A Phase 8 reader can reconstruct every nonrandom ranking, every raw model score, and all 1,000 Random permutations per bug using only frozen files, with no network or provider credentials.

## P7-09 — Audit completeness and seal the raw evaluation ✅ COMPLETE

**Depends on:** P7-01 through P7-08.

**Status:** Complete. Sealer [`src/seal_evaluation.py`](../../src/seal_evaluation.py) / [`scripts/seal_evaluation.py`](../../scripts/seal_evaluation.py); audit [`results/phase7/evaluation_seal_audit.json`](../../results/phase7/evaluation_seal_audit.json); seal [`results/phase7/raw_evaluation_seal.json`](../../results/phase7/raw_evaluation_seal.json); handoff [`docs/phase7-seal.md`](../../docs/phase7-seal.md). **PASS** — 125/125 bugs; Jev 113 + 12 accepted gaps; predictions 72,401 lines hash-locked; Random seeds regenerated; evaluation usage reconciled; no aggregate metrics computed.

**Work**

- Audit exactly 125 manifest evaluation bugs across the five required projects, each with one complete example, a full BM25 and Embedding ranking, one Jev and one GPT full ranking, and 1,000 reproducible Random permutations. Check no duplicate/missing test IDs or skipped bugs.
- Verify all candidate lists are BM25 prefixes of `min(200,N)`, Jev and GPT scored identical ordered IDs and exact patch/test strings, every required score is valid and cached, and all raw artifacts reference the same frozen commit/configuration.
- Reconcile successful request records, retry/failure logs, usage totals, and pricing snapshot. Flag any unaccounted paid call, model drift, or altered preregistered setting. Resolve data-completeness issues under the frozen method before sealing.
- Produce a read-only hash manifest or equivalent immutable snapshot of `predictions.jsonl`, rankings, candidate lists, raw labels, caches needed for reproduction, and configuration references. Save an audit report and hand Phase 8 the paths/hashes and offline read command.
- Only after the raw seal passes may an agent compute aggregate FDR, candidate recall@200, method differences, statistical tests, or failure cases.

**Deliverables:** Passing 125-bug evaluation audit, sealed raw-result manifest, and Phase 8 handoff.

**Acceptance:** Another agent can verify the hashes and regenerate all raw rankings and scores offline. No required candidate is missing, and the preregistered design has not changed since the Phase 6 tag.

## Phase completion gate ✅ COMPLETE

Phase 7 is implemented when all 125 evaluation examples and all five ranking systems are complete, every semantic score is cached and accounted for, `results/predictions.jsonl` and ranking files pass the integrity audit, and their hashes are sealed before aggregate analysis. Phase 8 receives immutable raw inputs and a freeze commit, with no further paid API calls required to calculate results.

**Sealed handoff:** [`docs/phase7-seal.md`](../../docs/phase7-seal.md) · commit `edc70bacd23f2fc5f511ef4d97a33376e7b20bf8` · tag `experiment-v1`.
