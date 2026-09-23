# Phase 7 ranking assembly (P7-07)

**Overall: `PASS`** (with 12 accepted Jev A-001 gaps)

- `experiment_commit`: `edc70bacd23f2fc5f511ef4d97a33376e7b20bf8`
- Bugs passed: **125/125**
- Systems:
  - Random: **125/125** (1,000 seeded permutations each)
  - BM25: **125/125** (from P7-03)
  - Embedding: **125/125** (from P7-04)
  - GPT-Nano: **125/125** assembled
  - Jev: **113/125** assembled; **12** omitted (WAF gaps, not invented)

## Commands

```bash
python -u scripts/run_random_baseline.py --split evaluation --allow-evaluation
python -u scripts/assemble_evaluation.py
```

## Gaps

See [`phase7-jev.md`](phase7-jev.md). Jev rankings are **not** written for those
12 bugs (`fail_closed_on_missing_scores`).

Machine records:

- `results/phase7/assembly.json`
- `results/random_baseline_summary-evaluation.json`
- `results/semantic/jev/*.json` (113)
- `results/semantic/gpt_nano/*.json` (125)
