# Phase 8 Random baseline aggregation (P8-03)

**Overall: `PASS`**

One `method=Random` row per evaluation bug: each numeric field is the **mean
over 1,000** sealed permutations (ranks / `detected_at_*` may be fractional).

## Cohort rules

| Quantity | Rule |
| --- | --- |
| FDR / MRR / mean APFD / mean NFTR | Mean of the 125 per-bug Random rows |
| **Median NFTR** | For replicate `i`, use permutation `i` for every bug → cohort median; report the **mean of those 1,000 medians** |
| First-trigger CDF | Average of 1,000 replicate empirical CDFs on grid `0.00..1.00` |

Do **not** use the median of per-bug mean NFTRs for the headline median.

## Headline (Random)

| FDR@10% | MRR | median NFTR |
| ---: | ---: | ---: |
| 0.1240 | 0.0884 | 0.4786 |

## Commands

```bash
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 python -u scripts/compute_random_metrics.py

docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 python -m unittest tests.test_phase8_random_metrics -v
```

## Artifacts

- [`src/random_metrics.py`](../src/random_metrics.py)
- [`results/phase8/random_metrics.json`](../results/phase8/random_metrics.json) — 125 rows + CDF
- [`tests/test_phase8_random_metrics.py`](../tests/test_phase8_random_metrics.py)
