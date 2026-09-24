# Phase 9 mechanical 20-case selection (P9-03)

**Overall: `PASS`**

Twenty qualitative-review cases are selected **mechanically** from sealed Phase 8
per-bug first-trigger ranks. No discretionary swaps.

## Rule

```
delta = BM25_first_trigger_rank - Jev_first_trigger_rank
```

- **Top 10 gains:** largest `delta` (Jev earlier); tie-break project name, then numeric bug id.
- **Top 10 losses:** smallest `delta` (BM25 earlier); same tie-break.
- Arms must yield **20 distinct** IDs (duplicate overlap resolved by skipping IDs already in the gain arm).
- `delta_sign_label` is `jev_gain` / `jev_loss` / `tie` from the signed delta — do not call a zero or opposite-sign arm member an improvement/regression it is not.

## Artifacts

| Artifact | Path |
| --- | --- |
| Selection JSON | [`results/failure_cases.json`](../results/failure_cases.json) |
| Table (Markdown) | [`results/phase9/failure_cases.md`](../results/phase9/failure_cases.md) |
| Phase 8 precursor | [`results/phase8/case20_deltas.json`](../results/phase8/case20_deltas.json) |

Each case records: ID, BM25/Jev ranks, delta, shortlist-trigger status
(`candidate_trigger_in_top200`), selection arm, and input hashes for
`per_bug_metrics.json` / `metrics.csv`.

## Selected IDs

See [`results/phase9/failure_cases.md`](../results/phase9/failure_cases.md). Order is
10 gain-arm IDs then 10 loss-arm IDs.

## Commands

```bash
docker run --rm --platform linux/amd64 --network=none \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 python -u scripts/select_failure_cases.py
```

Regeneration must match `results/phase8/case20_deltas.json` `selected_ids`.
