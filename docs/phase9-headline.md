# Phase 9 handoff verification + headline table (P9-01)

**Overall: `PASS`**

Phase 7 and Phase 8 seals verified offline. Report-ready headline table written
from sealed cohort summaries and cross-checked against `metrics.csv` (**565**
rows = 113 bugs × 5 methods) and the frozen cost ledger.

## A-001 cohort

Twelve Jsoup bugs with incomplete Jev rankings are **excluded from every
method** (paired denom=113). See [README](../README.md#a-001-exclusion-12-jsoup-bugs).

## Artifacts

| Output | Path |
| --- | --- |
| Verification | [`results/phase9/handoff_verification.json`](../results/phase9/handoff_verification.json) |
| Headline (Markdown) | [`results/phase9/headline_table.md`](../results/phase9/headline_table.md) |
| Headline (JSON) | [`results/phase9/headline_table.json`](../results/phase9/headline_table.json) |

## Headline (preview)

| Method | FDR@10% | Cost/Bug |
| --- | ---: | ---: |
| BM25 | 0.7345 | — |
| Jev | **0.9558** | 0.013878 |
| GPT-5.4 nano | 0.9204 | 0.054729 |

Primary: Jev − BM25 = **+22.1 pp**.

## Command

```bash
docker run --rm --platform linux/amd64 --network=none \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 python -u scripts/verify_phase9_handoff.py
```
