# Phase 8 paired statistics (P8-06)

**Overall: `PASS`**

Bootstrap seed = **20260922** (Phase 6 `selection_seed`; recorded in
`results/statistics.json` as `configuration.bootstrap_seed`). 10,000 paired
resamples; 95% percentile CIs.

## Primary: Jev vs BM25 (FDR@10%)

| both | Jev only | BM25 only | neither | McNemar p (exact 2-sided) |
| ---: | ---: | ---: | ---: | ---: |
| 80 | 28 | 12 | 5 | 0.0166 |

| Δ | point | 95% CI |
| --- | ---: | --- |
| FDR@10% | +0.1280 | [0.0320, 0.2240] |
| MRR | +0.2488 | [0.1708, 0.3274] |
| APFD | −0.0183 | [−0.0737, 0.0335] |
| median NFTR | −0.0285 | [−0.0484, −0.0109] |

## Secondary

Jev vs Embedding and Jev vs GPT-Nano use the **same** bootstrap index samples;
labeled secondary (not additional primary tests).

## Commands

```bash
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 python -u scripts/compute_statistics.py

docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 python -m unittest tests.test_phase8_statistics -v
```

## Artifacts

- [`src/statistics.py`](../src/statistics.py)
- [`results/statistics.json`](../results/statistics.json)
- [`tests/test_phase8_statistics.py`](../tests/test_phase8_statistics.py)
