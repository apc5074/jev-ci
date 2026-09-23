# Phase 7 BM25 rankings and sealed shortlists (P7-03)

**Overall: `PASS`**

- `experiment_commit`: `edc70bacd23f2fc5f511ef4d97a33376e7b20bf8`
- Run ID: `eval-v1-20260923T035853+0000`
- Rankings + shortlists: **125/125**
- Integrity audit: **125/125** (`results/phase7/candidates_audit.json`)
- `N` total / `K` total: **18194** / **13414** (`K=min(200,N)`)
- Source missing: **0**
- Candidate trigger recall: **not computed** (Phase 8)

## Commands

```bash
python -u scripts/run_candidates.py --split evaluation --allow-evaluation
python -u scripts/audit_phase4.py --split evaluation
```

## Seal contract

Each `data/candidates/<slug>.json` and `results/rankings/<slug>.json` records:

- `split=evaluation`
- `experiment_commit` / `run_id`
- `shortlist_sha256` of the ordered BM25 top-`K` prefix
- frozen BM25 / tokenizer settings and input hashes

Jev and GPT must `load_candidates` and verify `shortlist_sha256`; neither may
regenerate a different shortlist.

Machine records:

- `results/run_candidates-evaluation.json`
- `results/phase7/candidates_audit.json`
- `results/phase7/run_candidates-evaluation.log`
