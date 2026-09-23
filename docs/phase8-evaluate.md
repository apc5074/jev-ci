# Phase 8 offline evaluate command (P8-08)

**Overall: `PASS`**

`python scripts/evaluate.py` regenerates all Phase 8 outputs from the sealed
Phase 7 snapshot with **no API credentials** and **zero** provider calls.

## Command

```bash
docker run --rm --platform linux/amd64 --network=none \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 python -u scripts/evaluate.py
```

Pipeline: seal verify → per-bug metrics → Random → cost/latency → cohort →
statistics → metrics.csv / headline / figures → checks → regeneration record.

Timestamps in JSON artifacts are normalized to Phase 7 `sealed_at` so reruns are
byte-identical for `metrics.csv`, `statistics.json`, headline, and SVGs.

## Record

[`results/phase8/evaluate_regeneration.json`](../results/phase8/evaluate_regeneration.json)

## Tests

```bash
docker run --rm --platform linux/amd64 --network=none \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 python -m unittest tests.test_phase8_evaluate -v
```
