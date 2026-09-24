# Research report — Jev CI test selection (Phase 9)

Preregistered design: [`EXPERIMENT.md`](../EXPERIMENT.md) (frozen tag `experiment-v1`).  
This report interprets sealed Phase 8 metrics; it does **not** change methods, raw data, or the preregistration.

## Question and setup

Can a BM25 shortlist plus the **Jev** decision-model reranker place known fault-revealing Defects4J test classes earlier under a **test-class count budget** than BM25 alone?

- **Corpus:** Defects4J 3.0.1; 150 sampled bugs across Cli, Lang, Math, Jsoup, JacksonDatabind (30 each).
- **Splits:** 25 development / 125 evaluation (locked before scoring).
- **Scenario:** fixed revision as base; buggy revision as the proposed regression; existing **fixed-base** test classes as candidates; Defects4J triggering classes as positives.
- **Headline cohort:** 113 evaluation bugs. Twelve Jsoup bugs with incomplete Jev rankings (OpenRouter WAF, deviation **A-001-eval**) are excluded from **every** method so denominators stay paired. Full evaluation seal remains 125 bugs.

Budget \(k = \lceil 0.10 \cdot N\rceil\) test classes. Primary metric: **FDR@10%** (fraction of bugs with a known trigger in the top \(k\)).

## Systems

| Method | Role |
| --- | --- |
| Random | Seeded permutation baseline (1,000 replicates for aggregate NFTR/CDF) |
| BM25 | Full-suite lexical ranking; also supplies the top-200 shortlist for Jev/GPT |
| Embedding | Full-suite `text-embedding-3-small` cosine ranking |
| Jev | BM25 top-200 → Jev one-pair scores → shortlist reorder + BM25 tail |
| GPT-5.4 nano | Same shortlist ceiling; generative reranker cost/quality reference |

Paired comparisons share the same bugs and labels. Candidate ceiling: BM25 trigger recall@min(200,N) = **113/113**.

## Primary result

On n=113, **Jev FDR@10% = 0.9558** (108/113) vs **BM25 = 0.7345** (83/113): **+22.1 pp**.

- McNemar exact two-sided \(p \approx 4.65\times10^{-6}\) (discordant: Jev-only 28, BM25-only 3).
- Bootstrap 95% CI for Δ FDR@10% (Jev−BM25): **[0.133, 0.310]** (point 0.221).

Interpretation: **strong positive** primary contrast versus BM25 under the preregistered metric.

## Secondary evidence

| Method | FDR@5% | FDR@10% | FDR@20% | MRR | APFD | Median NFTR | Cost/bug (USD) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Random | 0.0696 | 0.1229 | 0.2277 | 0.0826 | 0.5201 | 0.4780 | — |
| BM25 | 0.6372 | 0.7345 | 0.8496 | 0.5096 | 0.9005 | 0.0435 | — |
| Embedding | 0.8319 | 0.8850 | 0.9115 | 0.6783 | 0.9396 | 0.0168 | 0.001348 |
| Jev | 0.9027 | **0.9558** | **0.9823** | **0.8222** | **0.9722** | **0.0119** | 0.013878 |
| GPT-5.4 nano | **0.9204** | 0.9204 | 0.9646 | 0.8024 | 0.9638 | **0.0119** | 0.054729 |

Cost is mean **effective prepaid credits** / headline bug from the frozen Phase 6 price snapshot (`2026-09-23`) and sealed usage ledger—not live prices; promotions are not treated as permanent zero cost.

**Project FDR@10% (descriptive):** Cli 0.88 vs 0.48; Lang 0.96 vs 0.92; Math 0.96 vs 0.88; Jsoup 1.00 vs 0.69 (n=13); JacksonDatabind 1.00 vs 0.68 (Jev vs BM25).

Figures: [`results/figures/`](../results/figures/) · captions [`results/figures/captions.md`](../results/figures/captions.md).

## Practical-success criterion

Frozen rule: success if (1) Jev ≥ BM25 + 5 pp FDR@10%, **or** (2) within 2 pp of GPT-Nano **and** Jev cost ≤ 30% of GPT-Nano.

| Alternative | Outcome |
| --- | --- |
| Alt1 (≥5 pp over BM25) | **PASS** (+22.1 pp) |
| Alt2 (near GPT ∧ cheap) | FAIL quality band (Jev − GPT = +3.5 pp, outside ±2 pp) though cost ratio ≈ 0.25 ≤ 0.30 |
| Overall | **PASS** via alt1 |

## Twenty-case qualitative review

Mechanically selected extremes of \(Δ = r_{\mathrm{BM25}} - r_{\mathrm{Jev}}\) ([`results/failure_cases.json`](../results/failure_cases.json)). Review: [`results/failure_analysis.json`](../results/failure_analysis.json).

- All 20 triggers were in the BM25 top-200 (**0** candidate-generation misses in this set).
- Large Jev gains often look like **behavioral / cross-class** matches BM25 under-ranked.
- Jev losses often look like **overvalued superficial neighbors** or a **large/truncated patch**; one **indirect dependency** miss; one **ambiguous** same-package name match.

These labels are explanatory only—they were not used to retune prompts or metrics.

## Limits

- Unlabeled tests are **not** confirmed negatives; do not read FDR as precision over the suite.
- A **test-class fraction** is not measured CI wall-clock.
- Static source ranking does not replace coverage or dynamic analysis.
- Model scores were used to **rank**, not assessed for probability calibration.
- Headline n=113 after A-001 exclusions; Jsoup project slices are descriptive with n=13.

## Environment and provenance

| Item | Value |
| --- | --- |
| Freeze tag | `experiment-v1` |
| Experiment commit | `edc70bacd23f2fc5f511ef4d97a33376e7b20bf8` |
| Run ID | `eval-v1-20260923T035853+0000` |
| Pricing snapshot | `2026-09-23` (`results/pricing_snapshot.json`) |
| Defects4J | 3.0.1 (see `data/manifest.json`) |

### Recorded deviations

- **A-001-eval:** 12 Jsoup WAF gaps → paired exclusion (README).
- **D-wallclock:** shortlist walls reconstructed from per-request latencies at concurrency 16.
- **D-tag-name:** freeze tag is `experiment-v1` (plans historically mentioned `experiment-v1-frozen`).

## Reproduce offline

```bash
docker build --platform linux/amd64 -t jev-ci:phase1 .
docker run --rm --platform linux/amd64 --network=none \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 python -u scripts/evaluate.py
```

Regenerates `results/metrics.csv`, `results/statistics.json`, headline/figure intermediates from sealed predictions—no API credentials required. Phase 9 publish helpers: `scripts/verify_phase9_handoff.py`, `scripts/publish_figures.py`, `scripts/select_failure_cases.py`, `scripts/publish_failure_analysis.py`.
