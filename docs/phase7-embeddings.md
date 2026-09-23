# Phase 7 Embedding rankings (P7-04)

**Overall: `PASS`**

- `experiment_commit`: `edc70bacd23f2fc5f511ef4d97a33376e7b20bf8`
- Model: `text-embedding-3-small` (full suite; independent of BM25)
- Rankings: **125/125** (`results/embeddings/<slug>.json`)
- Integrity audit: **125/125** (`results/phase7/embeddings_audit.json`)
- Failures: **0**

## Commands

```bash
python -u scripts/run_embeddings.py --split evaluation --allow-evaluation
python -u scripts/audit_embeddings.py --split evaluation
```

## Acceptance checks

- Every inventory test class appears exactly once
- Cosine scores finite; sort cosine↓ / FQCN↑
- `uses_bm25=false`; vectors live in `cache/embeddings/`
- Cache-only regeneration possible without paid calls for exact input hits

Machine records:

- `results/embeddings_summary-evaluation.json`
- `results/phase7/embeddings_audit.json`
- `results/phase7/run_embeddings-evaluation.log`
