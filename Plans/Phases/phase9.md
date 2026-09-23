# Phase 9 tickets — Present, interpret, and reproduce the experiment

**Phase goal:** Turn the sealed Phase 8 results into a clear research report, the four required figures, and a deterministic 20-case analysis. Finish with a clean, offline reproduction that another agent can follow. Phase 9 explains the observed result; it must not change the frozen methods, raw data, metrics, or headline lineup.

**Source of truth:** [../overall.md](../overall.md), sections 39–47; [../phases.md](../phases.md), Phase 9; the tagged `EXPERIMENT.md`; Phase 7's sealed raw-result index; and Phase 8's sealed `metrics.csv`, `statistics.json`, headline table, and figure data. Any post-hoc analysis must be labeled exploratory and kept separate from the preregistered headline findings.

Tickets are ordered by dependency. Each has an artifact and an acceptance check. The final audience should be able to see what was tested, how the result compares with the baselines, how uncertain it is, what it cost, and what the study cannot establish.

## P9-01 — Verify the analysis handoff and finalize the headline table

**Depends on:** Phase 8 completion gate.

**Work**

- Verify the Phase 7 and Phase 8 hash manifests, freeze commit, 125 evaluation bug IDs, 625 `bug × method` rows, and matching statistics/figure-data provenance before writing interpretations.
- Render the required five-method table in this fixed order: Random, BM25, Embedding, Jev, GPT-5.4 nano. Include FDR@5%, FDR@10%, FDR@20%, MRR, APFD, median NFTR, and cost/bug.
- Make display rounding consistent while retaining unrounded values in result files. The outline says to bold the numerically highest quality result, but median NFTR is better when **lower**; document this presentation exception and bold the lowest median NFTR. For other quality columns, bold the highest value, including ties. Do not bold cost as though it were a quality metric.
- Show every method's result even when it loses. Use an em dash for nonpaid Random/BM25 API cost and explain what the cost/bug column includes for paid methods.
- Cross-check table values directly against the sealed Phase 8 calculation, not manually copied numbers.

**Deliverables:** A canonical headline table in a report-ready Markdown or generated artifact, with a provenance reference.

**Acceptance:** All required rows/columns are present, values agree with `metrics.csv` and the frozen cost basis, and the table makes the primary FDR@10% comparison easy to identify without hiding other outcomes.

## P9-02 — Finish and inspect the four required figures

**Depends on:** P9-01 and Phase 8 figure generators.

**Work**

- Generate Figure 1, detection versus test-class budget, with all five methods and exact points at 1%, 2%, 5%, 10%, 20%, 50%, and 100%. Label the x-axis as **percent of test classes executed** and the y-axis as fraction of regressions detected.
- Generate Figure 2, a CDF of normalized first-trigger rank for the five methods. Use the frozen Random-permutation averaging rule; label axes and direction so earlier detection reads correctly.
- Generate Figure 3, grouped FDR@10% by `Cli`, `Lang`, `Math`, `Jsoup`, and `JacksonDatabind`. Keep project subsets descriptive and show denominators of 25 evaluation bugs per project.
- Generate Figure 4, FDR@10% versus mean cost/bug for Embedding, Jev, and GPT-Nano. State the frozen inference-cost basis, including how platform fees/credits are treated; do not present a promotion as a permanent zero-cost model.
- Render all four at readable report resolution, inspect labels, legends, clipping, colors, and values, and fix only presentation defects. Draw plots from the sealed `metrics.csv`/statistics/cost outputs, never from live API responses or manually edited points.

**Deliverables:** Four final files under `results/figures/`, generator commands, and concise captions naming the data and denominator.

**Acceptance:** Each figure matches the sealed metrics, remains legible at ordinary document width, and regenerates with `python scripts/evaluate.py` without network access.

## P9-03 — Select the 20 cases mechanically

**Depends on:** Phase 8 analyzed results being sealed.

**Work**

- For every evaluation bug, calculate `delta = BM25 first-trigger rank - Jev first-trigger rank` from the frozen per-bug results. Rank all bugs by `delta` descending to obtain the 10 largest Jev gains, and ascending to obtain the 10 largest Jev losses.
- Define a deterministic tie-break using the manifest's project/bug order. Select 20 **distinct** cases, save their IDs, both ranks, delta, shortlist-trigger status, and the selection rule before manual inspection.
- If fewer than 10 deltas are strictly positive or negative, still take the 10 extremes mechanically and describe zero/opposite-sign cases accurately rather than calling them improvements or regressions they are not.
- Keep this case list fixed. Do not replace awkward or ambiguous cases with more illustrative ones.

**Deliverables:** A machine-generated 20-case selection file, for example `results/failure_cases.json`, with hashes of the metric inputs.

**Acceptance:** Another agent can regenerate exactly the same 20 IDs and order from sealed metrics and the stated tie-break, with no discretionary selection.

## P9-04 — Perform a bounded qualitative failure analysis

**Depends on:** P9-03.

**Work**

- Review only the selected 20 cases, using the saved fixed → buggy patch, fixed-base test representations/full source where needed, BM25 shortlist, Jev scores, and known trigger classes. Do not issue new model calls or rerank cases.
- Assign one dominant phenomenon from the outline to each case: identifier/name match; behavioral semantic match; cross-class relationship; useful test-source clue; BM25 candidate-generation miss; Jev overvalued superficial similarity; Jev missed indirect dependency; large/truncated patch; large/truncated test; or ambiguous test responsibility.
- Support each classification with a short, concrete observation from the saved artifacts, citing file paths/class names and ranks where useful. Distinguish candidate-generation failures from reranker failures rather than attributing every miss to Jev.
- Note ambiguous cases as ambiguous and explain why the chosen dominant category is the best fit. This is explanatory review, not a second tuning set; do not modify prompts, shortlist size, labels, or statistical results afterward.

**Deliverables:** A 20-row failure-analysis table or section with ID, ranks/delta, trigger-in-shortlist status, dominant category, and brief evidence.

**Acceptance:** All mechanically selected cases are covered exactly once, each has a supported category, and no unselected case is substituted for narrative convenience.

## P9-05 — Write the methodology and findings for a new reader

**Depends on:** P9-01, P9-02, and P9-04.

**Work**

- Update `README.md` with a short research narrative and links to `EXPERIMENT.md`, result files, figures, failure analysis, and reproducibility commands. Keep `EXPERIMENT.md` as the preregistered design; do not rewrite it to fit the observed results.
- Explain the question and setup plainly: 150 sampled Defects4J bugs across five projects, 25 development/125 evaluation, fixed code as base, buggy code as the proposed regression, existing fixed-base test classes as candidates, and known triggering classes as positives.
- Describe the five systems and the BM25 top-200 ceiling, the 10% test-class budget, and the paired nature of comparisons. Report the primary Jev-versus-BM25 difference with both detection counts and uncertainty; also report MRR/APFD/NFTR, project variation, candidate recall@200, costs, and latency as secondary evidence.
- State whether either preregistered practical-success condition was met using the exact Phase 8 numbers and frozen price basis. Interpret strong, moderate, negative, or candidate-limited outcomes in proportion to the evidence; include the 20-case findings without feeding them back into methods.
- Explain limits: unlabeled tests are not confirmed negatives, test-class fraction is not measured CI runtime, static source ranking does not replace coverage analysis, and estimated probabilities were used only to rank tests rather than assessed for calibration.
- Include exact environment/model versions, Defects4J and freeze commits, pricing-snapshot date, commands to regenerate outputs, and any recorded deviations from preregistration. Separate exploratory follow-ups from headline conclusions.

**Deliverables:** Finished `README.md` and, if the README would become unwieldy, a linked short research report under `results/` or `docs/`.

**Acceptance:** A reader who has not seen the planning files can understand the experimental design, primary result, uncertainty, cost, caveats, and how to reproduce every table/figure. Claims stay within the evidence supported by the study.

## P9-06 — Reproduce the reported result from a clean environment

**Depends on:** P9-01 through P9-05.

**Work**

- Build/use the documented Phase 1 container from a clean checkout, attach only the required sealed data/cache artifacts, and run the documented offline command `python scripts/evaluate.py` with network/model credentials unavailable.
- Confirm the command regenerates `results/metrics.csv`, `results/statistics.json`, the headline table, and all four figures from cached raw predictions, rankings, labels, and usage. Compare numeric content or hashes with the published artifacts; explain any harmless file-metadata difference.
- Check that `data/manifest.json`, `EXPERIMENT.md`, 125 complete evaluation examples, five full ranking systems per bug, all semantic caches, `predictions.jsonl`, the 20-case analysis, four figures, and the final README/report exist and are linked correctly.
- Reconcile the report's quoted figures, counts, p-value, intervals, cost ratio, and success determination against regenerated outputs. Verify no paid request occurred and no result was drawn from a development bug.
- Record the commands, environment version, input hashes, output comparison, and any reproducibility caveat in a final check record.

**Deliverables:** Clean-environment reproduction record and complete final artifact inventory.

**Acceptance:** Another agent can follow the README, run `python scripts/evaluate.py` offline, and obtain the same metrics, statistics, table, and four figures without API access or an undocumented manual step.

## P9-07 — Finalize the interpretation and close the experiment

**Depends on:** P9-06.

**Work**

- Give the report a final consistency read: headline table, four figures, statistics, candidate ceiling, cost accounting, and 20-case review must tell the same story and use the same five method names.
- State the main finding in terms of ranking known fault-revealing tests at a 10% **test-class execution budget**. If Jev loses or the result is inconclusive, report that directly. Do not claim a 90% CI runtime reduction, superior code understanding, perfect probability calibration, or relevance judgments about non-triggering tests.
- Preserve the frozen raw and analyzed files with their hash manifests and freeze commit. Record any deviation or post-hoc exploration separately so the preregistered result remains identifiable.
- Provide a final artifact index with links to the manifest, preregistration, metrics, predictions, statistics, figures, failure analysis, README/report, and reproduction record.

**Deliverables:** Final research writeup and artifact index.

**Acceptance:** The study is complete against section 46 of `overall.md`: required artifacts exist, the offline evaluator reproduces reported outputs, and the conclusion matches the measured evidence and stated limits.

## Phase completion gate

Phase 9 is implemented when the five-method headline table, four checked figures, deterministic 20-case analysis, README/research writeup, and clean offline reproduction record are finished. A reader can trace each claim back to Phase 8 metrics and Phase 7 sealed raw data, while the Phase 6 preregistration remains unchanged.
