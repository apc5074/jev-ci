# Phase 9 final closeout (P9-07)

**Overall: `PASS` — Phase 9 complete**

## Main finding

See [`results/phase9/main_finding.md`](../results/phase9/main_finding.md).

Jev FDR@10% **0.9558** vs BM25 **0.7345** (+22.1 pp) on n=113 at a 10% **test-class** budget. Practical-success **PASS** (alt1). No CI-runtime or calibration claims.

## Final index

| Artifact | Path |
| --- | --- |
| Index JSON | [`results/phase9/final_index.json`](../results/phase9/final_index.json) |
| Index Markdown | [`results/phase9/final_index.md`](../results/phase9/final_index.md) |
| Main finding | [`results/phase9/main_finding.md`](../results/phase9/main_finding.md) |
| Research report | [`docs/phase9-report.md`](phase9-report.md) |
| README | [`README.md`](../README.md) |

## Command

```bash
docker run --rm --platform linux/amd64 --network=none \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 python -u scripts/finalize_phase9.py
```
