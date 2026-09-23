# Phase 8 tickets — Metrics and paired statistical analysis

**Phase goal:** Turn the sealed Phase 7 rankings and known trigger classes into the preregistered measurements, statistical comparisons, costs, tables, and figure data. Everything must regenerate offline from frozen inputs. Phase 8 calculates results; Phase 9 interprets and presents them.

**Source of truth:** [../overall.md](../overall.md), sections 23–34 and 38–40; [../phases.md](../phases.md), Phase 8; the tagged `EXPERIMENT.md` / `experiment.yaml` from Phase 6; and the Phase 7 raw-result hash manifest. If a reporting convention is missing from preregistration, identify it before opening aggregate results where possible. After results are visible, record a deviation instead of silently choosing the favorable interpretation.

Tickets are ordered by dependency. Each produces a checkable artifact or calculation. Only the 125 evaluation bugs enter headline metrics; the 25 development bugs remain diagnostic.

## P8-01 — Load and verify sealed inputs without network access ✅ COMPLETE

**Depends on:** Phase 7 completion gate.

**Status:** Complete. Offline loader [`src/evaluation_inputs.py`](../../src/evaluation_inputs.py) / [`scripts/validate_evaluation_inputs.py`](../../scripts/validate_evaluation_inputs.py); report [`docs/phase8-inputs.md`](../../docs/phase8-inputs.md) + [`results/phase8/input_validation.json`](../../results/phase8/input_validation.json); tests [`tests/test_phase8_inputs.py`](../../tests/test_phase8_inputs.py). **PASS** — 125 bugs loaded; hashes/freeze commit verified; API keys cleared; tampered ranking/hash/commit rejected.

**Work**

- Implement a read-only loader for the Phase 2 manifest, private trigger-class labels, candidate lists, complete rankings/Random permutations, `results/predictions.jsonl`, usage ledger, pricing snapshot, and Phase 7 hash manifest.
- Verify hashes, `experiment-v1-frozen` commit/configuration IDs, model/prompt versions, 125 evaluation IDs, and the 125 × five-method coverage before calculating an outcome. Reject a changed or missing raw file.
- Validate each ranking against its fixed-base `tests.all` inventory, and check that its trigger-class set is nonempty and consistent. Keep labels out of model-input artifacts; they enter only this offline analysis.
- Fail closed if any required semantic score, usage record, Random seed/permutation, or source artifact is absent. Do not make provider calls, rebuild candidate lists, or repair rankings inside the evaluator.

**Deliverables:** Offline input loader and a machine-readable input validation report.

**Acceptance:** The evaluator runs with no API credentials or network access, accepts the sealed Phase 7 snapshot, and rejects a deliberately altered ranking, label, hash, or freeze commit.

## P8-02 — Calculate exact per-bug ranking metrics ✅ COMPLETE

**Depends on:** P8-01.

**Status:** Complete. [`src/metrics.py`](../../src/metrics.py) / [`scripts/compute_per_bug_metrics.py`](../../scripts/compute_per_bug_metrics.py); records [`results/phase8/per_bug_metrics.json`](../../results/phase8/per_bug_metrics.json) (500 bug×method rows); docs [`docs/phase8-metrics.md`](../../docs/phase8-metrics.md); tests [`tests/test_phase8_metrics.py`](../../tests/test_phase8_metrics.py). Hand-worked budget/rank/APFD cases pass. Jev rows for 12 A-001 gaps are `available=false` (no invented ranks).

**Work**

- For each bug and each nonrandom full ranking, let `N` be the number of test classes and `r` the **1-based** rank of the earliest known triggering class. If several classes trigger, use the minimum rank.
- At budgets 1%, 2%, 5%, 10%, 20%, 50%, and 100%, use `k=max(1,ceil(fraction*N))`; detection is true iff any known trigger is in `ranking[:k]`. Treat FDR@10% as the single primary outcome.
- Compute `reciprocal_rank=1/r`, `normalized_first_trigger_rank=r/N`, and `apfd=1-r/N+1/(2*N)` per bug. Aggregate MRR/APFD by arithmetic mean and normalized first-trigger rank by both mean and median.
- Preserve all known triggering classes as positives but leave every other class unlabeled. Do not calculate classification accuracy, precision, false-positive rate, Brier score, or AUROC.
- Use numeric precision sufficient for reproducible aggregate and bootstrap calculations; round only display values, not stored per-bug data.

**Deliverables:** Pure metric functions in `src/metrics.py` and checked per-bug records for BM25, Embedding, Jev, and GPT.

**Acceptance:** Small hand-worked examples verify multiple triggers, rank 1, rank `N`, tiny suites where `k=1`, exact ceiling at budget boundaries, and APFD limits. Every nonrandom evaluation bug has one record per method.

## P8-03 — Aggregate the 1,000-permutation Random baseline ✅ COMPLETE

**Depends on:** P8-01 and P8-02.

**Status:** Complete. [`src/random_metrics.py`](../../src/random_metrics.py) / [`scripts/compute_random_metrics.py`](../../scripts/compute_random_metrics.py); output [`results/phase8/random_metrics.json`](../../results/phase8/random_metrics.json); docs [`docs/phase8-random.md`](../../docs/phase8-random.md); tests [`tests/test_phase8_random_metrics.py`](../../tests/test_phase8_random_metrics.py). 125 Random rows (means over 1,000 perms); median NFTR via permutation replicates; synthetic N=2 exhaustive means verified.

**Work**

- Run the **same** per-bug metric functions on all 1,000 saved/reproducible Random permutations for each evaluation bug. Verify the frozen seed/index convention and permutation counts before aggregation.
- For Random's required one `bug × method` row, store the per-bug mean of each numeric metric and detection indicator over its 1,000 permutations. Consequently, its `first_trigger_rank` and `detected_at_*` fields may be fractional; document this schema meaning. Average these per-bug values across the 125 bugs for linear headline metrics such as FDR and MRR.
- For nonlinear cohort summaries such as median NFTR, form 1,000 cohort replicates: replicate `i` uses permutation `i` for every bug. Compute the cohort median for each replicate, then report the mean of those 1,000 medians, consistent with the outline's “mean metric across permutations” rule. Average the 1,000 cohort CDFs similarly for the Random distribution figure. Record this convention in Phase 6 before evaluation; do not take the median of per-bug means or choose a lucky permutation.
- Keep the Random seed/permutation records available so another agent can reproduce every reported mean.

**Deliverables:** Random aggregation logic and documented row/figure semantics.

**Acceptance:** A synthetic suite with exhaustively known permutations yields the expected average detection and rank metrics. There is exactly one Random metrics row per evaluation bug, backed by 1,000 permutations.

## P8-04 — Calculate measured cost and latency consistently

**Depends on:** P8-01.

**Work**

- Sum actual provider input, cached-input, and output tokens for Embedding, Jev, and GPT from the frozen usage ledger. Apply the **dated** Phase 6 pricing snapshot, including the preregistered treatment of platform fees, promotional credits, retries, and shared cached embeddings. Never fetch current prices to recalculate historical costs.
- Report total inference dollars, total actual cash dollars where different, mean dollars per bug (`cohort total / 125`), and mean dollars per scored candidate. For embeddings, specify attribution when a vector is reused by several bugs; ensure per-bug rows reconcile to the cohort total.
- Compute candidate request p50, p95, and mean client-observed latency from `send → full response`, plus actual wall-clock time to score each top-`K` shortlist at up to 16 concurrent requests. Distinguish provider request latency from wall time that includes queueing/retries/cache reads.
- Use the frozen cost basis to evaluate the Jev-versus-GPT `<=30%` reranking-cost criterion. Record both numerator and denominator, not just the ratio. Do not claim a token, test-class, or free-credit saving is a measured CI runtime saving.

**Deliverables:** `src/metrics.py` or a cost/latency helper, reconciled usage/cost records, and a cost-basis note linked to the pricing snapshot.

**Acceptance:** Independent sums of the request ledger match the reported token and dollar totals; cost per bug/candidate reconciles to those totals; latency percentiles and shortlist wall times use the documented population.

## P8-05 — Build cohort, project, and candidate-ceiling summaries

**Depends on:** P8-02 through P8-04.

**Work**

- Calculate FDR at all seven budgets as the fraction of **125 evaluation bugs** detected by each method, with Random averaged as specified in P8-03. Compute MRR, APFD, mean/median NFTR, cost/bug, and latency summaries without changing the five-method lineup.
- Calculate BM25 trigger recall@200: fraction of evaluation bugs with at least one known triggering class in the saved top-`min(200,N)` candidate list. Use the sealed shortlist; do not rerun retrieval or enlarge it.
- Produce descriptive results separately for `Cli`, `Lang`, `Math`, `Jsoup`, and `JacksonDatabind`, each with 25 evaluation bugs. Do not make significance claims from the project subsets.
- Classify Jev non-detections at the 10% budget as candidate-generation misses when **no** trigger was in the BM25 shortlist, and reranker misses when a trigger was in the shortlist but Jev still missed at that budget. Keep the underlying bug IDs and counts for Phase 9 failure analysis.
- Evaluate the preregistered practical-success alternatives using the observed FDR@10% and frozen cost basis, reporting exact percentage-point differences and the Jev/GPT cost ratio. Show the full table even if Jev loses.

**Deliverables:** Cohort/project/candidate-ceiling summaries in a machine-readable analysis artifact.

**Acceptance:** Headline denominators equal 125, project denominators equal 25, candidate recall uses the frozen prefix, and every Jev miss receives exactly one candidate-vs-reranker classification.

## P8-06 — Run the preregistered paired statistical comparisons

**Depends on:** P8-02 and P8-05.

**Work**

- For the primary Jev-versus-BM25 FDR@10% comparison, build the complete 2×2 paired detection table: both detected, Jev only, BM25 only, neither. Run a two-sided **exact McNemar test** on the discordant cells, including a defined result when there are zero discordances.
- Draw exactly 10,000 paired bootstrap samples of the 125 evaluation bug IDs **with replacement**, using the seed fixed in Phase 6. For each sample compute Jev-minus-comparator differences in FDR@10%, MRR, APFD, and median NFTR. Use 2.5th/97.5th percentile bounds for 95% intervals.
- Apply the same bootstrap comparisons to Jev versus Embedding and Jev versus GPT-Nano, labeled secondary. Keep all methods' results paired by the same sampled bug IDs; do not independently resample each method.
- Report point differences, intervals, exact McNemar p-value, and the four paired-detection cell counts. Do not reduce the primary result to a p-value alone or present secondary comparisons as new primary tests.

**Deliverables:** `src/statistics.py` and `results/statistics.json` with reproducible seeds, resample count, point estimates, intervals, and paired tables.

**Acceptance:** Hand-worked discordant-pair and bootstrap fixtures match expected results; rerunning with the frozen seed produces byte-identical statistics from the same metrics inputs.

## P8-07 — Write the required results and canonical display outputs

**Depends on:** P8-02 through P8-06.

**Work**

- Write `results/metrics.csv` with **one row per evaluation bug × method** (125 × 5 = 625 rows) and every field listed in section 38 of `overall.md`: project/bug/split/method, suite/trigger counts, earliest-rank metrics, detection budgets, APFD, candidate indicator, reranker token/cost/wall metrics, and truncation/missing-source metadata. Add provenance fields or a hashed sidecar without dropping the required columns.
- Write `results/statistics.json` from the paired calculations and include configuration, freeze commit, input hash-manifest ID, statistic definitions, and denominator counts.
- Generate the canonical five-method headline table with FDR@5%, FDR@10%, FDR@20%, MRR, APFD, median NFTR, and cost/bug. Bold only the numerically best quality value in each column; preserve losing values and mark nonpaid Random/BM25 cost appropriately.
- Implement data-to-figure generation for the four required Phase 9 figures: budget curve, first-trigger CDF, project FDR@10%, and quality versus cost. Phase 9 may refine layout/captions but must derive the figures only from `metrics.csv`, `statistics.json`, and frozen cost data.
- Avoid making plots directly from API responses or unsealed cache records.

**Deliverables:** `results/metrics.csv`, `results/statistics.json`, machine-generated headline table, and deterministic figure data/generation code.

**Acceptance:** The CSV has exactly 625 valid rows, required columns, five method values, and no development data. The table and figure generators read frozen result files rather than provider responses.

## P8-08 — Make `evaluate.py` a complete offline regeneration command

**Depends on:** P8-01 through P8-07.

**Work**

- Implement `python scripts/evaluate.py` to verify the Phase 7 hashes, load the frozen rankings/labels/usage, calculate metrics and statistics, and regenerate the table and four figures in one documented run. It must require no API credentials and make **zero** paid/model requests.
- Make output ordering, numeric serialization, bootstrap RNG, and figure inputs deterministic. Use atomic output writes and record input/freeze IDs in generated artifacts. Separate validation failures from ordinary display rounding differences.
- Run in a clean Phase 1 container with network unavailable and only the documented raw-artifact/cache mount. Compare generated file hashes or numeric content against a second run, allowing only deliberately nondeterministic image metadata if the plotting library forces it.
- Add meaningful metric/statistic checks covering multiple triggers, budget ceiling, APFD, Random aggregation, paired resampling, and schema counts. Do not add tests that merely repeat implementation line by line.

**Deliverables:** `scripts/evaluate.py`, focused checks, and a clean offline regeneration record.

**Acceptance:** The command succeeds from frozen raw inputs without credentials/network and reproduces metrics, statistics, table, and figures. A missing or altered raw input causes a clear nonzero failure before any output is published.

## P8-09 — Freeze analyzed results for interpretation

**Depends on:** P8-08.

**Work**

- Review cross-file consistency: each CSV metric agrees with its saved ranking/trigger set; aggregate table values agree with 625 CSV rows; statistical inputs match per-bug FDR@10%; cost totals match usage ledgers; figures use the same denominators.
- Hash and preserve final `metrics.csv`, `statistics.json`, table, and figure data alongside their Phase 7 raw-input hashes and freeze commit. Record any preregistration deviation transparently without overwriting the sealed raw data.
- Hand Phase 9 the canonical outputs, exact practical-success determination, candidate-generation ceiling, per-project summaries, Jev miss categories, and a deterministic list of per-bug first-trigger-rank differences for the 20-case qualitative review.

**Deliverables:** Analysis audit, sealed result index, and Phase 9 handoff.

**Acceptance:** Another agent can trace every headline number to a per-bug row and each row to a sealed ranking. The results are ready for interpretation without rerunning providers or changing the analysis method.

## Phase completion gate

Phase 8 is implemented when all 625 evaluation `bug × method` rows, paired statistics, costs, project/candidate summaries, headline table, and four figure generators exist and reconcile to Phase 7's sealed raw inputs. `python scripts/evaluate.py` regenerates them offline and deterministically. Phase 9 can then explain and present the result without recalculating or selecting favorable metrics.
