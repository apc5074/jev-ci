# Phase 6 tickets — Development review and experiment freeze

**Phase goal:** Finish debugging on the 25 development bugs, make every remaining methodological choice explicit, and commit an immutable preregistration before any of the 125 evaluation bugs are processed. The phase ends with a tested, tagged configuration that Phase 7 can execute without tuning or interpretation.

**Source of truth:** [../overall.md](../overall.md), especially sections 3–5, 17–23, 24–38, and 44; [../phases.md](../phases.md), Phase 6. Phases 1–5 supply the container, locked manifest, development examples, all five development rankings, cached semantic results, provider decision, and integrity checks. Evaluation IDs may be listed in the manifest and preregistration, but their examples, rankings, scores, and outcomes remain untouched here.

Tickets are ordered by dependency. Each leaves a reviewable artifact or gate. Distinguish an implementation correction from a change to the study design; record either one before the freeze.

## P6-01 — Establish a complete development baseline ✅ COMPLETE

**Depends on:** Phases 1–5.

**Status:** Complete. [`src/development_baseline.py`](../../src/development_baseline.py) / [`scripts/run_development_baseline.py`](../../scripts/run_development_baseline.py); review table [`docs/phase6-baseline.md`](../../docs/phase6-baseline.md); machine record [`results/phase6/development_baseline.json`](../../results/phase6/development_baseline.json). Initial Jev prompt `jev-would_detect_regression-v1` preserved (revision count 0). **Accepted gap:** Jsoup-70 Jev blocked by OpenRouter WAF (`file://etc/passwd`); all other systems complete for 25/25.

**Work**

- Run the end-to-end pipeline on all 25 development bugs from the locked manifest using the current extraction, BM25, Random, Embedding, Jev, and GPT implementations. Preserve the initial Jev prompt version and its complete cached outputs before considering a revision.
- Produce a development-only review table for pipeline diagnosis: example completeness, patch direction, source and trigger counts, representation truncation, BM25 candidate recall, first-trigger positions, API errors, model IDs, token usage, and ranking integrity. Do not place these numbers in the later headline evaluation table.
- Confirm that the initial run is actually complete: five full rankings per bug, one valid semantic score per shortlisted pair, no fabricated score, and no unfinished extraction. If it is incomplete, finish or fix it before using it to judge the prompt.
- Save the commands, code revision, input hashes, provider/model versions, and date for this baseline so later development changes can be traced.

**Deliverables:** A complete initial development run and a dated development audit record.

**Acceptance:** All 25 bugs have complete, traceable development artifacts. The original prompt and scores remain available for comparison after any permitted revision.

## P6-02 — Triage and correct implementation defects ✅ COMPLETE

**Depends on:** P6-01.

**Status:** Complete. Correction log [`docs/phase6-defect-log.md`](../../docs/phase6-defect-log.md) + [`results/phase6/defect_triage.json`](../../results/phase6/defect_triage.json). **Fixed D-001:** usage ledger summary now reads flat cost fields ([`src/audit_phase5.py`](../../src/audit_phase5.py)); baseline regenerated. **A-001** Jsoup-70 WAF kept as accepted availability (not a code defect). No bugs dropped; no K/prompt/system changes.

**Work**

- Review failures in checkout/source mapping, fixed → buggy diffs, trigger parsing, truncation, model-visible state, tokenizer/BM25 scoring, candidate lists, API response parsing, caching, and ranking assembly.
- For each finding, record the evidence, affected bug IDs, whether it is an implementation defect or methodological change, and the correction. Fix defects at their source and rerun affected development artifacts and downstream caches where input hashes changed.
- Keep all 25 development bugs in the study. Document any real Defects4J metadata exception with supporting evidence; do not discard a hard bug to make checks pass.
- Do not use development scores to add new systems, change the 200-candidate cap, tune a probability threshold, or search many prompt variants. A possible Jev prompt revision is governed only by P6-03.

**Deliverables:** A concise issue/correction log, corrected code, and refreshed development artifacts where necessary.

**Acceptance:** Known implementation defects are resolved, the affected checks pass, and the reason for every changed development artifact is traceable to a code/input correction or the single allowed prompt revision.

## P6-03 — Decide the one allowed Jev prompt revision ✅ COMPLETE

**Depends on:** A complete P6-01 run and P6-02 defect triage.

**Status:** Complete under the previously accepted A-001 availability exception. **Retain original; semantic revision count 0; final name v1.** Review [docs/phase6-prompt-decision.md](../../docs/phase6-prompt-decision.md); exact [Jev](../../prompts/jev/v1.json) and [GPT](../../prompts/gpt/v1.json) prompt snapshots; [decision + hashes](../../results/phase6/prompt_decision.json); [cache inventory](../../results/phase6/final_prompt_cache_inventory.json). Offline verification (`python3 scripts/verify_phase6_prompts.py`) passed: Jev **2691/2692** pairs, GPT-Nano **2692/2692**, across all 25 development bugs. Jsoup-70 / ConnectTest remains the sole accepted missing Jev score; literal full-score acceptance is still excepted and must be settled before evaluation freeze. No prompt rewrite, new inference, or evaluation inspection.

**Work**

- Review the initial Jev prompt on development bugs for a genuine misunderstanding of the intended test-impact question, not just a lower score than another method. Decide either to keep it or make **at most one** semantic revision.
- If revising, write the exact before/after text and a short reason grounded in interpretation. Change neither the Noul task, one-pair state, test/patch representations, nor candidate set as part of a disguised prompt search.
- Run the revised prompt on the full development set once, using a new cache key. Preserve the original responses and record the revision count. Do not iterate again based on the revised scores.
- Name the final Jev prompt `v1` for preregistration whether it is the retained original or the single revision. Record which case occurred. Freeze the GPT rubric/prompt alongside it.

**Deliverables:** Versioned prompt files, an explicit zero-or-one revision record, and complete final development Jev scores.

**Acceptance:** There is one final Jev prompt with a known history and complete cached development output. No evaluation example or outcome informed its wording.

## P6-04 — Close every open methodological choice ✅ COMPLETE

**Depends on:** P6-02 and P6-03.

**Status:** Complete. Locked config [`experiment.yaml`](../../experiment.yaml) + [`results/phase6/experiment.json`](../../results/phase6/experiment.json); decisions [`docs/phase6-decisions.md`](../../docs/phase6-decisions.md); loader [`src/experiment_config.py`](../../src/experiment_config.py); pricing snapshot refreshed **2026-09-23**. Prompt decision recorded as **retain original** (`revision_count=0`) with frozen bodies under `results/phase6/prompts/`. Cost criterion basis: `effective_prepaid_credits_usd`. Open availability A-001 (Jsoup-70 WAF) remains a pre-eval gate item.

**Work**

- Compare code and configuration against `overall.md` and Phase 1–5 decisions. Settle and document any necessary interpretation before evaluation, including patch truncation arithmetic, character counting, BM25 query diff source and scoring formula, tie-breaks, nested/ambiguous source handling, long-source windows, embedding over-limit behavior, Random evaluation-index convention, and output precision.
- Lock the five named systems, project order and split, `K=min(200,N)`, models and provider endpoints, exact Jev underlying model ID, GPT snapshot, all prompts and representations, API concurrency/retries, and cache-key serialization. Resolve model/version or provider-access blockers here; do not use a moving Jev alias in final evaluation.
- Lock the outcome definitions: FDR@10% primary; secondary FDR budgets, MRR, normalized first-trigger rank, APFD, candidate recall@200, cost and latency; paired McNemar and 10,000 paired bootstrap samples; project descriptions; and the predetermined practical-success thresholds.
- State how provider list price, platform fees, promotional credits, and actual cash spend are recorded. Choose the price basis for the Jev/GPT `<=30%` cost criterion in advance and save the dated provider price snapshot. Avoid declaring Jev free merely because a Gateway feature or credit is free.
- Write a short deviations/decisions log for any specification ambiguity or unavoidable change. An altered research question or comparator requires a clearly versioned new experiment rather than a quiet edit to `overall.md`.

**Deliverables:** Final `experiment.yaml` values, pricing snapshot, and a decisions/deviations log.

**Acceptance:** A Phase 7 agent can read the configuration and execute without choosing a tokenization rule, model, provider, price basis, metric, or tie-break during evaluation.

## P6-05 — Write the human-readable preregistration ✅ COMPLETE

**Depends on:** P6-04.

**Status:** Complete. [`EXPERIMENT.md`](../../EXPERIMENT.md) synced with [`experiment.yaml`](../../experiment.yaml) / [`results/phase6/experiment.json`](../../results/phase6/experiment.json); canonical prompts [`prompts/jev/v1.json`](../../prompts/jev/v1.json) and [`prompts/gpt/v1.json`](../../prompts/gpt/v1.json) with file SHA-256s recorded. Includes H1–H3, FDR@10% primary, practical-success thresholds, cost basis, full ID lists, figures, failure-case rule, and claim limits.

**Work**

- Write `EXPERIMENT.md` as the human-readable frozen design. Include all selected IDs and their development/evaluation membership, Defects4J version/commit, fixed-base → buggy-proposed direction, test/patch representations, tokenizer/BM25 settings, candidate K, all five ranking methods, exact model IDs/provider, exact prompts, cache/retry rules, and handling of extraction exceptions.
- State H1–H3, the single primary outcome, secondary outcomes, practical-success criteria, cost basis, paired statistics, project analysis, candidate-generation ceiling, required figures, and deterministic failure-case selection.
- Link or quote the final prompt/config files and identify their content hashes. Make `experiment.yaml` the machine-readable implementation companion; check that it matches `EXPERIMENT.md` and the code defaults. Do not leave a placeholder such as “choose later.”
- State the claim limits: this measures rankings of known fault-revealing test classes under a test-class count budget, not CI runtime reduction or classification of unlabeled tests.

**Deliverables:** Complete `EXPERIMENT.md` and synchronized `experiment.yaml`.

**Acceptance:** An independent reader can reconstruct the study design and determine in advance whether Jev met the success criteria. All dataset, model, prompt, metric, and statistical details required by section 36 of `overall.md` are present.

## P6-06 — Run the pre-evaluation integrity gate ✅ COMPLETE

**Depends on:** P6-05.

**Status:** Complete. Gate CLI [`scripts/run_pre_eval_gate.py`](../../scripts/run_pre_eval_gate.py) / [`src/pre_eval_gate.py`](../../src/pre_eval_gate.py); freeze guard [`src/freeze_guard.py`](../../src/freeze_guard.py) (wired via `require_manifest_membership(..., allow_evaluation=True)`); report [`docs/phase6-pre-eval-gate.md`](../../docs/phase6-pre-eval-gate.md) + [`results/phase6/pre_eval_gate.json`](../../results/phase6/pre_eval_gate.json). **PASS** 25/25 development bugs; preregistration agreement ok; zero evaluation artifacts; freeze lock absent and evaluation blocked; cache-only rebuild (Cli-30) ok. Accepted gap A-001 (Jsoup-70 WAF) unchanged.

**Work**

- Run automated checks over all 25 development examples and all five ranking outputs: base is `Bf`, proposal is `Bb`, trigger classes are consistent with `tests.all` or have explicit source-backed exceptions, and every ranking contains exactly `N` unique test classes.
- Inspect the **serialized** Jev and GPT requests for all development candidates. The model-visible fields must not include bug ID, issue title, trigger method/list, expected result, or pipeline-added “buggy”/“fixed” labels. Genuine Java source text containing such words is not by itself leakage.
- Verify Jev/GPT received identical ordered BM25 shortlists and identical patch/test strings; all required scores are valid, cached, and associated with the frozen model/provider/prompt/input hashes.
- Rebuild development rankings in a clean Phase 1 container using cached responses and no provider credentials. Check that configuration and preregistration agree and that the command has no evaluation side effects.
- Add a guard that refuses evaluation-mode extraction, ranking, or scoring until the freeze tag/configuration is present and validated.

**Deliverables:** Passing integrity checks and a dated pre-evaluation gate report.

**Acceptance:** Every required check passes. No evaluation example, candidate list, semantic call, or metric file has been generated before the freeze.

## P6-07 — Commit, tag, and hand off the frozen design 🧾 READY (user commit/tag)

**Depends on:** P6-01 through P6-06.

**Status:** Freeze tag is **`experiment-v1`** → commit `edc70bacd23f2fc5f511ef4d97a33376e7b20bf8`. Handoff [`docs/phase6-handoff.md`](../../docs/phase6-handoff.md); unlock with [`scripts/write_freeze_lock.py`](../../scripts/write_freeze_lock.py) (writes `freeze_lock.json` after the tag; keep it out of the tagged tree).

**Work**

- Commit `EXPERIMENT.md`, `experiment.yaml`, final prompt files, source code, tests, manifest reference, pricing/model snapshots, and gate report. Review the commit for accidental secrets, local absolute paths, or evaluation artifacts.
- Create the annotated `experiment-v1-frozen` tag on that exact commit. Record the tag's target commit SHA in the handoff. Do not place a self-referential freeze SHA inside the commit being tagged; Phase 7 will attach it to each new result file.
- Verify that a clean checkout at the tag can run the pre-evaluation checks and load the manifest and development caches as documented. Confirm the working tree has no uncommitted methodological changes when evaluation starts.
- Hand Phase 7 the container command, manifest, freeze SHA, exact configuration/prompt hashes, provider and credential requirements, price snapshot, cache paths, and evaluation execution order.

**Deliverables:** Frozen commit and `experiment-v1-frozen` tag, plus a concise Phase 7 handoff record.

**Acceptance:** The tag resolves to the reviewed preregistration commit, all pre-evaluation checks pass from that revision, and Phase 7 can start the 125 evaluation bugs without a new design decision.

## Phase completion gate

Phase 6 is implemented only when the complete development run has been reviewed, implementation defects are resolved, Jev has had no more than one documented prompt revision, the full study is specified in `EXPERIMENT.md` and `experiment.yaml`, and the integrity gate passes. The commit is tagged `experiment-v1-frozen` before any evaluation processing. From that point onward, changed methods must be recorded as deviations or a new version, never retroactively folded into the frozen study.
