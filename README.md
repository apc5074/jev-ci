# jev-ci

Can a cheap decision model beat BM25 at picking which tests will catch a regression?

Short answer: **yes.** On Defects4J, Jev finds the fault-revealing test in the top 10% of the suite **22 points more often** than BM25 alone — and costs ~4× less than GPT-5.4 nano while matching or beating it on most ranking metrics.

Preregistration (frozen, don't rewrite history): [`EXPERIMENT.md`](EXPERIMENT.md)

---

## What this is

You have a code change. You have a pile of existing tests. You want to run the ones most likely to fail first.

This repo ranks **test classes** for Defects4J bugs:

1. Start from the **fixed** code
2. Treat the **buggy** code as the proposed change
3. Rank the fixed-base test suite
4. Score a method by whether a known triggering test lands in the top **10%** of classes (`FDR@10%`)

We compared five methods on the same bugs: Random, BM25, embeddings, **Jev** (BM25 top-200 → Jev rerank), and GPT-5.4 nano.

---

## Results (n=113)

| Method | FDR@10% | MRR | Cost / bug |
| --- | ---: | ---: | ---: |
| Random | 0.12 | 0.08 | — |
| BM25 | 0.73 | 0.51 | — |
| Embedding | 0.89 | 0.68 | $0.0013 |
| **Jev** | **0.96** | **0.82** | $0.014 |
| GPT-5.4 nano | 0.92 | 0.80 | $0.055 |

- Jev **0.9558** vs BM25 **0.7345** → **+22.1 pp** (McNemar p ≈ 4.6×10⁻⁶, bootstrap 95% CI [0.133, 0.310])
- Preregistered success bar (≥5 pp over BM25): **PASS**
- Near-GPT-and-cheap bar: quality band missed (Jev was slightly *better* than GPT, outside ±2 pp); cost was fine (~25% of GPT)

Charts: [`results/figures/`](results/figures/)

### Honest caveats

- This ranks **known** triggering tests. It does **not** prove unlabeled tests are safe to skip.
- “Top 10% of test classes” ≠ “90% less CI time.”
- Scores were for ranking, not calibrated probabilities.
- 12 Jsoup bugs never got a full Jev ranking (OpenRouter WAF tripped on `file://etc/passwd` in test source). Those 12 are dropped from **every** method so the comparison stays fair → headline **n=113**, not 125.

---

## Layout

```
EXPERIMENT.md          # what we promised before looking
data/                  # bugs, patches, tests, manifest
results/metrics.csv    # per-bug numbers
results/statistics.json
results/figures/       # the four charts
results/failure_*.json # 20 mechanical extreme cases + notes
src/                   # the pipeline
scripts/evaluate.py    # regenerate everything offline
```

---

## Reproduce (no API keys)

```bash
docker build --platform linux/amd64 -t jev-ci:phase1 .
docker run --rm --platform linux/amd64 --network=none \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 python -u scripts/evaluate.py
```

That rebuilds metrics, stats, and figures from sealed predictions. Full Phase 9 check: `scripts/reproduce_phase9.py`.

---

## Quick vibe check

```bash
docker build --platform linux/amd64 -t jev-ci:phase1 .
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 python scripts/check_environment.py
```

---

Built as a sealed experiment: freeze first, score second, explain last. If something looks hand-wavy, open `EXPERIMENT.md` or `results/` — the numbers live there.
