# jev-ci

You push a change, CI has a bunch of tests to run, and you want the ones that might catch a bug to go first.

That’s the idea behind this repo. Take a code change, find the tests that look relevant, then ask a small decision model to put them in a better order.

The question was pretty simple: **can Jev beat BM25 at finding the tests that catch a regression?**

On this Defects4J experiment, it did. Jev put a known failing test in the first 10% of test classes on **96% of bugs**, compared with **73% for BM25**. It also cost about a quarter as much as GPT-5.4 nano per bug.

## How it works

BM25 is the starting point: it matches text in the code change with text in the tests. Jev takes the top 200 candidates and scores each change/test pair using `typesafe/jev-1.13`. Those scores decide the new order.

To try this on real bugs, we used Defects4J. For each bug, we start with the fixed code and treat the change back to the buggy version as the proposed patch. Then we rank the existing test classes and check how early a test known to catch that bug shows up.

We ran five approaches on the same bugs: random order, BM25, embeddings, BM25 → Jev, and BM25 → GPT-5.4 nano. Both rerankers get the same BM25 shortlist; embeddings rank the full suite.

## What happened

These numbers cover the **113 evaluation bugs with complete results across all five methods**.

| Method | Bug found in first 10% of classes | MRR | Cost / bug |
| --- | ---: | ---: | ---: |
| Random | 12% | 0.08 | — |
| BM25 | 73% | 0.51 | — |
| Embeddings | 89% | 0.68 | $0.0013 |
| **Jev** | **96%** | **0.82** | **$0.014** |
| GPT-5.4 nano | 92% | 0.80 | $0.055 |

The first column is the main metric, `FDR@10%`: how often at least one known failing test class lands in the first 10% of the suite, rounded up. MRR measures how early the first one appears. Higher is better; 1 means it’s always first.

Jev improved on BM25 by **22.1 percentage points** (0.9558 vs. 0.7345). The paired McNemar test gives p ≈ 4.6 × 10⁻⁶, and the bootstrap 95% confidence interval for the improvement is 13.3–31.0 percentage points.

Before scoring the evaluation set, we set a target of at least 5 points over BM25. Jev cleared that. We also set an alternative target: within 2 points of GPT nano at no more than 30% of its cost. Jev met the cost target, but scored slightly better than that quality band allowed, so that second target technically didn’t pass.

Charts are in [`results/figures/`](results/figures/), with versions for sharing in [`results/share/`](results/share/).

## A few limits

This is a test ranking experiment. It checks where **known failing tests** end up. It doesn’t establish that the other tests are safe to skip, and running 10% of test classes doesn’t necessarily take 10% of the CI time. The model scores are used to sort tests; they aren’t calibrated failure probabilities.

We planned to evaluate 125 bugs. Twelve Jsoup bugs never got a complete Jev ranking because OpenRouter’s WAF blocked requests containing `file://etc/passwd` in the test source. We left those bugs out of every method’s headline results so everyone is compared on the same 113 bugs.

## The experiment setup

We locked the setup before looking at evaluation results under tag `experiment-v1`, commit `edc70bac…`. The full configuration is in [`experiment.yaml`](experiment.yaml), and the bug list is in [`data/manifest.json`](data/manifest.json).

- Defects4J 3.0.1, covering Cli, Lang, Math, Jsoup, and JacksonDatabind.
- 25 development bugs and 125 planned evaluation bugs, selected with seed `20260922`.
- Main metric: find a known failing class in the first `ceil(0.10 × N)` classes, where `N` is the suite size.
- Jev: BM25 top 200 → `typesafe/jev-1.13`, one change/test pair per request.
- GPT: the same shortlist → `gpt-5.4-nano`, returning a structured probability score.

Prompts, BM25 settings, statistical checks, and the other details are recorded in the configuration so you can see exactly what ran.

## Rebuild the results

You can regenerate the metrics, statistics, and charts from the saved predictions with Docker. No API keys needed.

```bash
docker build --platform linux/amd64 -t jev-ci:phase1 .
docker run --rm --platform linux/amd64 --network=none \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 python -u scripts/evaluate.py
```

This redoes the analysis from the sealed rankings. For the full reproduction check, see [`scripts/reproduce_phase9.py`](scripts/reproduce_phase9.py).

To check the environment:

```bash
docker build --platform linux/amd64 -t jev-ci:phase1 .
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 python scripts/check_environment.py
```

## Where things live

| Path | What’s there |
| --- | --- |
| [`experiment.yaml`](experiment.yaml) | The locked experiment setup |
| [`data/`](data/) | Bug IDs, patches, test sources, and the manifest |
| [`src/`](src/) | Ranking and evaluation code |
| [`scripts/`](scripts/) | Scripts to run and reproduce the experiment |
| [`results/metrics.csv`](results/metrics.csv) | Per-bug metrics |
| [`results/statistics.json`](results/statistics.json) | Statistical comparisons |
| [`results/figures/`](results/figures/) | Result charts |
| [`results/share/`](results/share/) | Charts for sharing |
| [`results/failure_cases.json`](results/failure_cases.json) and [`failure_analysis.json`](results/failure_analysis.json) | Cases worth digging into |
| [`results/`](results/) | Saved rankings, embeddings, predictions, and the cost/latency ledger |

The freeze record is in `results/phase6/freeze_lock.json`. The raw evaluation seal and index are in `results/phase7/`, and regenerated analysis goes in `results/phase8/`.

The idea is to find useful tests earlier without spending much on the ranking itself. These are the results from one experiment; the saved outputs are here if you want to poke around.
