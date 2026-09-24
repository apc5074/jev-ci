# Phase 8 analysis seal (P8-09)

**Overall: `PASS`**

Phase 8 analyzed results are sealed on the **113-bug** headline cohort (A-001
gaps excluded for all methods). Phase 9 interprets from these outputs.

## Freeze identity

- `freeze_tag`: `experiment-v1`
- `experiment_commit`: `edc70bacd23f2fc5f511ef4d97a33376e7b20bf8`
- `run_id`: `eval-v1-20260923T035853+0000`
- `sealed_at`: `2026-09-23T15:24:01+00:00`

## Seal command

```bash
docker run --rm --platform linux/amd64 --network=none \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 python -u scripts/seal_analysis.py
```

## Artifacts

| Artifact | Path |
| --- | --- |
| Analysis seal | [`results/phase8/analysis_seal.json`](../results/phase8/analysis_seal.json) |
| Cross-file audit | [`results/phase8/analysis_audit.json`](../results/phase8/analysis_audit.json) |
| 20-case deltas | [`results/phase8/case20_deltas.json`](../results/phase8/case20_deltas.json) |
| Phase 9 handoff | [`docs/phase8-handoff.md`](phase8-handoff.md) |

## Practical success

**PASS** (alt1): Jev FDR@10% = 0.9558 vs BM25 0.7345 (+22.1 pp). Candidate
recall@200 = 1.0 on the headline cohort; 5 Jev misses @10% (all reranker).

## Deviations (transparent)

- **A-001-eval:** 12 Jsoup bugs lack complete Jev rankings; excluded from
  headline metrics for **all** methods (n=113). See README.
- **D-wallclock:** Shortlist walls reconstructed at concurrency 16.
- **D-tag-name:** Freeze tag is `experiment-v1` (not `experiment-v1-frozen`).
