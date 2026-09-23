# Phase 8 cohort summaries (P8-05)

**Overall: `PASS`**

Headline denominators are **125** for every method. Unavailable Jev A-001 bugs
are imputed as non-detections with worst-case `r = N`.

## FDR@10% (primary)

| Random | BM25 | Embedding | Jev | GPT-Nano |
| ---: | ---: | ---: | ---: | ---: |
| 0.124 | 0.736 | 0.880 | 0.864 | 0.912 |

## Candidate ceiling

BM25 trigger recall@`min(200,N)` = **125/125 = 1.000** (sealed shortlists).

## Jev misses @10%

- **17** misses / 125 (108 detections)
- Candidate-generation misses: **0**
- Reranker misses: **17** (includes 12 A-001 gaps + 5 scored non-detections)

## Practical success

**PASS** via alternative 1: Jev − BM25 = **+12.8 pp** (≥ +5 pp).

Alternative 2 fails (Jev is −4.8 pp vs GPT-Nano; cost ratio 0.247 ≤ 0.30 alone is not enough).

## Commands

```bash
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 python -u scripts/compute_cohort_summaries.py

docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 python -m unittest tests.test_phase8_cohort -v
```

## Artifacts

- [`src/cohort_summaries.py`](../src/cohort_summaries.py)
- [`results/phase8/cohort_summaries.json`](../results/phase8/cohort_summaries.json)
- [`tests/test_phase8_cohort.py`](../tests/test_phase8_cohort.py)
