# Jev CI test-selection experiment

Static regression-test prioritization on Defects4J 3.0.1 with the Jev decision model.  
**Preregistration (unchanged):** [`EXPERIMENT.md`](EXPERIMENT.md) · freeze tag `experiment-v1`.  
**Full writeup:** [`docs/phase9-report.md`](docs/phase9-report.md).

## What was tested

150 Defects4J bugs (Cli, Lang, Math, Jsoup, JacksonDatabind): **25 development / 125 evaluation**. Fixed code is the base; buggy code is the proposed regression; fixed-base test classes are candidates; known triggering classes are positives. Headline analysis uses **n=113** after excluding 12 Jsoup bugs that never received a complete Jev ranking (see below)—dropped for **all** methods.

Five systems, paired on the same bugs: **Random**, **BM25** (also top-200 shortlist), **Embedding**, **Jev** (BM25→Jev rerank), **GPT-5.4 nano**. Primary budget: **10% of test classes**. Primary metric: **FDR@10%**.

## Headline results (n=113)

| Method | FDR@5% | FDR@10% | FDR@20% | MRR | APFD | Median NFTR | Cost/Bug |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Random | 0.0696 | 0.1229 | 0.2277 | 0.0826 | 0.5201 | 0.4780 | — |
| BM25 | 0.6372 | 0.7345 | 0.8496 | 0.5096 | 0.9005 | 0.0435 | — |
| Embedding | 0.8319 | 0.8850 | 0.9115 | 0.6783 | 0.9396 | 0.0168 | 0.001348 |
| Jev | 0.9027 | **0.9558** | **0.9823** | **0.8222** | **0.9722** | **0.0119** | 0.013878 |
| GPT-5.4 nano | **0.9204** | 0.9204 | 0.9646 | 0.8024 | 0.9638 | **0.0119** | 0.054729 |

**Jev vs BM25:** +22.1 pp FDR@10% (108 vs 83 detections; McNemar \(p \approx 4.6\times10^{-6}\); bootstrap 95% CI [0.133, 0.310]).

**Practical success (preregistered):** **PASS** via alt1 (≥5 pp over BM25). Alt2 (within 2 pp of GPT-Nano ∧ cost ≤ 30% of GPT) did not pass the quality band (Jev was +3.5 pp vs GPT; cost ratio ≈ 0.25 did meet the cheapness clause).

Secondary: Jev also leads MRR/APFD; median NFTR ties GPT at 0.0119. BM25 trigger recall@200 = 113/113. Project FDR@10% (descriptive): largest Jev−BM25 gaps on Cli and JacksonDatabind; Jsoup n=13 after exclusions.

Figures: [`results/figures/`](results/figures/). Table provenance: [`results/phase9/headline_table.md`](results/phase9/headline_table.md).

### A-001 exclusion (12 Jsoup bugs)

OpenRouter’s WAF blocked complete Jev shortlist scoring when model-visible text contained `file://etc/passwd` in `ConnectTest` / `UrlConnectTest` (deviation **A-001-eval**). Representations were not rewritten. Headline metrics/statistics/figures **exclude those twelve IDs from every method** (paired denom=113; `metrics.csv` = 565 rows). Full evaluation seal remains 125 bugs.

`Jsoup-33`, `Jsoup-40`, `Jsoup-47`, `Jsoup-54`, `Jsoup-69`, `Jsoup-72`, `Jsoup-75`, `Jsoup-78`, `Jsoup-81`, `Jsoup-84`, `Jsoup-85`, `Jsoup-86`

Policy: [`src/analysis_cohort.py`](src/analysis_cohort.py).

### Qualitative extremes (20 cases)

Mechanical selection by \(Δ = r_{\mathrm{BM25}} - r_{\mathrm{Jev}}\): [`results/failure_cases.json`](results/failure_cases.json).  
Review: [`results/failure_analysis.json`](results/failure_analysis.json) — gains often behavioral/cross-class; losses often superficial neighbors or truncated patches; **0/20** shortlist misses in this set. Explanatory only; not used to retune.

### Limits

Unlabeled tests are not confirmed negatives; test-class fraction ≠ CI runtime; static ranking ≠ coverage; scores were for ranking, not calibration. Do not claim a 90% CI runtime cut or perfect understanding of non-triggers.

## Offline regenerate

```bash
docker build --platform linux/amd64 -t jev-ci:phase1 .
docker run --rm --platform linux/amd64 --network=none \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 python -u scripts/evaluate.py
```

Needs sealed predictions/caches only—no API keys. Full check: `scripts/reproduce_phase9.py`. Also: `scripts/verify_phase9_handoff.py`, `scripts/publish_figures.py`, `scripts/select_failure_cases.py`, `scripts/publish_failure_analysis.py`.

**Provenance:** freeze `experiment-v1` @ `edc70bacd23f2fc5f511ef4d97a33376e7b20bf8`; pricing snapshot `2026-09-23`; run `eval-v1-20260923T035853+0000`.

## Quick start

```bash
docker build --platform linux/amd64 -t jev-ci:phase1 .
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 \
  python scripts/check_environment.py
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 \
  python src/select_bugs.py verify
```

## Docs

| Doc | Contents |
| --- | --- |
| [docs/phase9-report.md](docs/phase9-report.md) | Methodology, findings, limits, reproduce |
| [docs/phase9-headline.md](docs/phase9-headline.md) | Verified report headline table |
| [docs/phase9-figures.md](docs/phase9-figures.md) | Final figures under results/figures/ |
| [docs/phase9-failure-cases.md](docs/phase9-failure-cases.md) | Mechanical 20-case selection |
| [docs/phase9-failure-analysis.md](docs/phase9-failure-analysis.md) | Qualitative review of the 20 cases |
| [docs/phase9-reproduction.md](docs/phase9-reproduction.md) | Offline reproduction record |
| [docs/phase9-final.md](docs/phase9-final.md) | Phase 9 closeout / artifact index |
| [docs/setup.md](docs/setup.md) | Build, run, smoke check |
| [docs/phase3-handoff.md](docs/phase3-handoff.md) | Locked split for Phase 3 |
| [docs/verification-phase2.md](docs/verification-phase2.md) | Manifest lock record |
| [docs/manifest.md](docs/manifest.md) | Manifest schema / create / verify |
| [docs/testing.md](docs/testing.md) | Phase 2 unit tests |
| [docs/example-contract.md](docs/example-contract.md) | Phase 3 layout, visibility, prepare_dataset |
| [docs/patch-truncation.md](docs/patch-truncation.md) | 12k patch cap / marker-reserving rule |
| [docs/test-representations.md](docs/test-npz.md) | Test compaction, tokenizer/BM25 versions |
| [docs/verification-phase3.md](docs/verification-phase3.md) | Phase 3 integrity audit record |
| [docs/phase4-handoff.md](docs/phase4-handoff.md) | Artifacts and lexical primitives for Phase 4 |
| [docs/bm25-lexical-contract.md](docs/bm25-lexical-contract.md) | Phase 4 BM25 query/document input contract |
| [docs/tokenizer.md](docs/tokenizer.md) | Shared code tokenizer rules / version |
| [docs/bm25-scoring.md](docs/bm25-scoring.md) | BM25 formula, corpus, suite ranking order |
| [docs/candidates.md](docs/candidates.md) | Shortlist / full-ranking artifacts and Phase 5 reader |
| [docs/verification-phase4.md](docs/verification-phase4.md) | Phase 4 BM25 retrieval audit record |
| [docs/phase5-handoff.md](docs/phase5-handoff.md) | Fixed shortlist contract for Jev/GPT |
| [docs/phase6-handoff.md](docs/phase6-handoff.md) | Frozen design / Phase 7 unlock checklist |
| [EXPERIMENT.md](EXPERIMENT.md) | Human-readable preregistration (v1) |
| [docs/jev-provider-decision.md](docs/jev-provider-decision.md) | Jev route selection / pricing / probe gate |
| [docs/cache-ledger.md](docs/cache-ledger.md) | Semantic cache keys, failures, usage ledger |
| [docs/random-baseline.md](docs/random-baseline.md) | Seeded Random permutations / index convention |
| [docs/embeddings.md](docs/embeddings.md) | Full-suite Embedding baseline / over-limit rule |
| [docs/jev-ranker.md](docs/jev-ranker.md) | One-pair Jev Noul client / captured request |
| [docs/gpt-ranker.md](docs/gpt-ranker.md) | Multi-model GPT comparison clients |
| [docs/semantic-scheduler.md](docs/semantic-scheduler.md) | Concurrency, retries, spend ceiling |
| [docs/phase8-handoff.md](docs/phase8-handoff.md) | Sealed Phase 8 analysis → Phase 9 |
