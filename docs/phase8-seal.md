# Phase 8 analysis seal (P8-09)

**Overall: `PASS`**

Phase 8 analyzed results are sealed. Phase 9 interprets and presents them from
these immutable outputs — no recalculation of methods, metrics, or the headline
lineup.

## Freeze identity

- `freeze_tag`: `experiment-v1`
- `experiment_commit`: `edc70bacd23f2fc5f511ef4d97a33376e7b20bf8`
- `run_id`: `eval-v1-20260923T035853+0000`
- `sealed_at`: `2026-09-23T15:24:01+00:00`
- `seal_sha256`: `92c3bd41c3d792a6fd5670d3f77debaed912954bff952967fab5afe49249ecd3`

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

Audit: CSV ranks match sealed rankings; cohort FDR@10% matches CSV means;
statistics ΔFDR matches cohort; CSV cost sums match ledger; figure denominators
agree; evaluate checks 16/16.

## Practical success

**PASS** (alt1): Jev FDR@10% = 0.864 vs BM25 0.736 (+12.8 pp). Candidate
recall@200 = 1.0; 17 Jev misses @10% are all reranker misses.

## Deviations (transparent)

- **A-001-eval:** 12 Jsoup bugs lack Jev rankings; imputed r=N for denom-125.
- **D-wallclock:** Shortlist walls reconstructed at concurrency 16.
- **D-tag-name:** Freeze tag is `experiment-v1` (not `experiment-v1-frozen`).
