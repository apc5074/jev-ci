# Jev CI experiment: phase briefs

This is the sequence for turning [overall.md](overall.md) into executable phase plans. Each phase brief tells an agent what to plan, what it can rely on, and what must be true before the next phase starts. The exact experimental rules, prompts, formulas, and output schemas remain in `overall.md`; a phase plan should reference those rules rather than quietly changing them.

The central boundary is the preregistration freeze. Before that boundary, agents may build and debug with the 25 development bugs. After it, they execute the fixed design on the 125 evaluation bugs and may not tune it in response to results. Preparing shared infrastructure is fine before the freeze; evaluation rankings, scores, and aggregate outcomes must wait.

## Phase 1 — Establish a reproducible environment

**Goal:** Make the experiment runnable in a clean Linux container and prove that Defects4J works there.

**An agent's full plan should cover:**

- A Dockerfile based on Ubuntu 22.04 with Python 3.12, Java 11, Git, Subversion, Perl, cpanm, and `TZ=America/Los_Angeles`.
- Installing Defects4J 3.0.1, its dependencies, and its initialized project repositories. Pin the installation to a recorded Git commit and make `defects4j` available on `PATH`.
- Python dependencies and a minimal command or script that validates the toolchain with `defects4j info -p Lang`.
- Where large Defects4J checkouts, caches, API credentials, and generated artifacts live in the container. Keep credentials out of committed files.
- A short setup guide with exact commands for building and running the container.

**Deliverables:** `Dockerfile`, `requirements.txt`, setup instructions, and a captured environment record containing Defects4J commit, Python and Java versions, OS, architecture, and timezone.

**Exit check:** A fresh container can install and initialize Defects4J and successfully query `Lang` without relying on the host machine's Java setup.

## Phase 2 — Select and lock the dataset

**Goal:** Create one deterministic list of bugs and a durable development/evaluation split.

**An agent's full plan should cover:**

- Reading active bug IDs for exactly `Cli`, `Lang`, `Math`, `Jsoup`, and `JacksonDatabind`, in that order.
- Using one continuous `random.Random(20260922)` instance to sample 30 sorted active IDs per project. The first five selected IDs in each project are development bugs; the other 25 are evaluation bugs.
- Writing `data/manifest.json` with the 150 IDs, split membership, Defects4J version and commit, seed, creation time, repository commit, and environment metadata.
- Validating 30 IDs per project, 25 development IDs, 125 evaluation IDs, uniqueness, and active status. Define how the script behaves if a manifest already exists: validate and reuse it, never silently resample it.
- Recording any discrepancy between the installed Defects4J metadata and the assumptions in `overall.md` before proceeding.

**Deliverables:** `src/select_bugs.py`, a manifest creation entry point, `data/manifest.json`, and manifest validation checks.

**Exit check:** Re-running the selection command preserves the existing split byte-for-byte or refuses to overwrite it. The split is committed before further work.

## Phase 3 — Build and validate examples on development bugs

**Goal:** Turn a Defects4J bug into a proposed regression change, an available test suite, and known triggering test classes. Prove the extraction on the development set first.

**An agent's full plan should cover:**

- Checking out `Bf` as the working base and `Bb` as the proposed changed version. Extract modified production classes and source paths, then generate a unified diff in the **fixed → buggy** direction.
- Building the patch representation with paths, modified classes, and diff; applying the 12,000-character middle-truncation rule and recording truncation metadata.
- Exporting `tests.all`, `tests.trigger`, and test source directories from the fixed checkout. Convert trigger methods to classes, verify class membership, and preserve the distinction between known positives and unlabeled tests.
- Mapping test FQCNs, including nested classes, to fixed-revision source. Use the specified source-window selection for files over 240 lines, the 12,000-character cap, and the FQCN fallback when source is missing.
- Saving raw extraction artifacts and normalized representations with stable IDs so later phases can reproduce inputs exactly.
- Checking patch direction, trigger parsing, missing-source behavior, source-window ordering, truncation, and absence of bug labels or answer-bearing metadata from model-visible state.

**Deliverables:** Checkout, patch, test-extraction, and representation modules; development examples under `data/bugs`, `data/patches`, and `data/tests`; extraction validation checks.

**Exit check:** All 25 development bugs produce a patch, a complete test-class list, and at least one consistent known triggering class. Any exceptional Defects4J metadata is documented. Do not inspect evaluation-bug outcomes here.

## Phase 4 — Implement lexical retrieval and candidate selection

**Goal:** Produce a complete, transparent BM25 ranking and the fixed candidate shortlist used by both semantic rerankers.

**An agent's full plan should cover:**

- Implementing the single tokenizer from `overall.md`, including identifier boundaries and no stemming or stopword removal.
- Implementing BM25 with `k1=1.5` and `b=0.75`. Index each available test class using its FQCN and entire available source; query with modified paths, class names, and the regression patch.
- Producing a deterministic full-suite ranking with an explicit tie-break rule and `K=min(200, N)` top candidates. Store shortlist IDs and BM25 ranks in `data/candidates`.
- Verifying that every ranking is a permutation of the full suite and that the shortlist is an exact prefix. Calculate candidate trigger recall on development bugs for pipeline diagnosis only.
- Making the ranking and shortlist reproducible from the saved example data; evaluation shortlists are generated only after the freeze.

**Deliverables:** Tokenizer and BM25 modules, candidate-generation script, development rankings and shortlist files, ranking integrity checks.

**Exit check:** Every development bug has a full BM25 ranking and top-200 shortlist, with deterministic reruns and no missing or duplicated tests.

## Phase 5 — Implement semantic scoring and the other baselines

**Goal:** Make all five ranking systems executable on development bugs, with identical inputs where required and recoverable paid calls.

**An agent's full plan should cover:**

- A random baseline with 1,000 seeded permutations per bug and an embedding baseline using `text-embedding-3-small`, cosine similarity, and a full-suite ranking.
- Discovering a stable Jev model ID through `GET /v1/models`, saving the response, and scoring one Noul decision per patch/test-class pair using the exact rubric in `overall.md`.
- A GPT baseline using the fixed `gpt-5.4-nano-2026-03-17` snapshot, reasoning effort `none`, structured probability output, and the same patch and test representations and semantic rubric.
- Giving Jev and GPT the **same** BM25 top-200 IDs. Rerank only those IDs, break score ties by BM25 rank, and append the untouched BM25 tail.
- A SHA-256 request cache keyed by provider, model ID, prompt version, serialized state, and question; record scores, token usage, latency, request IDs, and failures. Reuse exact cache hits.
- Maximum 16 concurrent requests per provider, the specified retryable errors and 1/2/4-second backoff, and a completeness gate: no missing or placeholder score may enter a final ranking.
- Checking current model availability, API response formats, and pricing before paid calls; record exact model IDs and pricing snapshots. If a specified model is unavailable, document the blocker before changing the study design.

**Deliverables:** Embedding, Jev, GPT, cache, and ranking modules; development scores and complete rankings; provider and pricing snapshots; client-level checks.

**Exit check:** All five systems return complete development rankings; every semantic call is cached; Jev/GPT shortlist equality and score completeness are verified.

## Phase 6 — Run development checks and freeze the experiment

**Goal:** Fix implementation problems, make the last allowed design decisions, and preregister the evaluation.

**An agent's full plan should cover:**

- Running the full pipeline on the 25 development bugs and inspecting extraction failures, patch direction, prompt interpretation, schemas, API errors, and ranking behavior.
- Fixing implementation bugs and allowing at most **one** semantic Jev prompt revision after the first complete development run. Record the final prompt as `v1` and keep development outcomes out of headline results.
- Verifying the exact five systems, 200-candidate cap, test representations, model snapshots, metrics, statistical tests, cost method, and success criteria against `overall.md`.
- Writing `EXPERIMENT.md` with the selected IDs and split, patch direction, representations, prompts, models, hypotheses, metrics, thresholds, and analysis method.
- Running the integrity checks: no label leakage, fixed → buggy patch direction, trigger consistency, full ranking permutations, shortlist equality, and complete model scores.
- Committing the preregistration and tagging `experiment-v1-frozen`; record the freeze commit hash in all later outputs.

**Deliverables:** Final `experiment.yaml`, `EXPERIMENT.md`, passing pre-evaluation checks, and the `experiment-v1-frozen` tag.

**Exit check:** The freeze commit contains everything needed to run evaluation without making a methodological choice. Evaluation work cannot begin until this check passes.

## Phase 7 — Execute the frozen evaluation

**Goal:** Apply the frozen pipeline once to all 125 evaluation bugs and preserve complete raw results.

**An agent's full plan should cover:**

- Extracting evaluation examples with the validated Phase 3 pipeline; recording source gaps and truncation without excluding bugs.
- Generating full BM25 rankings and freezing top-200 IDs, then generating full-suite embedding rankings and scores for the identical Jev/GPT shortlists.
- Resuming safely after interruptions through cached requests. Resolve failed or missing candidate scores before assembling rankings; never substitute guessed values.
- Creating full Random, BM25, Embedding, Jev, and GPT rankings for every bug, each with exactly `N` unique test classes.
- Writing raw per-candidate scores and complete ranking files with model/prompt versions, manifest ID, freeze commit, usage, cost basis, and latency. Treat these files as immutable inputs to analysis.
- An evaluation audit: 125 bugs, five complete rankings each, no duplicate/missing classes, no shortlist mismatch, no uncached successful paid request, and no changed preregistered settings.

**Deliverables:** Evaluation examples and candidate files, cached semantic outputs, full rankings, `results/predictions.jsonl`, and an audit report.

**Exit check:** All 125 examples and five rankings per example are complete. Freeze the raw predictions and rankings before calculating or inspecting aggregate results.

## Phase 8 — Calculate metrics and statistical results

**Goal:** Convert frozen rankings into the preregistered measurements and comparisons.

**An agent's full plan should cover:**

- `FDR@10%` as the single primary outcome, with `k=max(1, ceil(0.10*N))`; also FDR at 1%, 2%, 5%, 20%, 50%, and 100%.
- Earliest known trigger rank, MRR, mean and median normalized first-trigger rank, and APFD using the formulas in `overall.md`. Never treat non-triggering tests as confirmed negatives.
- The required bug × method `results/metrics.csv` schema, including candidate recall, missing-source and truncation fields, and model usage, cost, and timing.
- The paired Jev-versus-BM25 FDR@10% table and exact McNemar test; 10,000 paired bootstrap samples for the stated metric differences and percentile intervals. Label Jev-versus-Embedding and Jev-versus-GPT comparisons secondary.
- Descriptive results for each project, BM25 trigger recall@200, and Jev failure categories separating candidate-generation misses from reranker misses.
- Pricing based on the stored historical snapshot and measured usage; latency from client-observed requests and 16-concurrent shortlist runs.
- A deterministic, offline `python scripts/evaluate.py` that recreates metrics, statistics, tables, and figures from cached raw predictions, with no paid API calls.

**Deliverables:** `results/metrics.csv`, `results/statistics.json`, reproducible headline table, and offline evaluation script.

**Exit check:** Row counts and formulas validate, results can be regenerated from frozen inputs, and the primary comparison includes both effect size and paired uncertainty.

## Phase 9 — Interpret and publish the research report

**Goal:** Present the outcome honestly and make the experiment understandable and reproducible to another person.

**An agent's full plan should cover:**

- The five-method headline table with FDR@5%, FDR@10%, FDR@20%, MRR, APFD, median NFTR, and cost per bug; bold only the best numeric quality value in each column.
- Four figures: detection versus test-class budget, first-trigger-rank CDF, project-level FDR@10%, and quality versus reranking cost.
- A deterministic 20-case review: the 10 largest Jev improvements over BM25 and the 10 largest regressions, chosen by first-trigger-rank difference after aggregate results are frozen. Classify each with the phenomena listed in `overall.md`.
- A README/research writeup that explains setup, data split, patch inversion, methods, primary result, uncertainty, cost, candidate-generation ceiling, project variation, and limitations.
- Conclusions limited to ranking known fault-revealing test classes under a **test-class count** budget. Avoid CI runtime, probability calibration, coverage replacement, or claims that unlabeled tests are irrelevant.
- A final clean-environment run of the offline evaluation command and a check that every required artifact exists.

**Deliverables:** Four figures, headline table, 20-case failure analysis, README/research report, and a reproducibility check record.

**Exit check:** Another agent can build the environment, inspect the frozen design and raw results, and regenerate all reported metrics and figures without an API call.

## Planning rule for each phase

When expanding one phase into an implementation plan, specify the concrete tasks, files and data contracts, commands, dependencies, checks, failure/retry behavior, and handoff to the next phase. Preserve the rules in `overall.md`. If a necessary choice is absent or two rules conflict, resolve and record it **before** the freeze; after the freeze, report a deviation rather than silently altering the evaluation.
