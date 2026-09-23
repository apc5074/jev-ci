# Phase 7 evaluation extraction (P7-02)

Generated from `results/phase7/extraction_audit.json` and
`results/prepare_dataset-evaluation.json`.

**Overall: `PASS`**

- `experiment_commit`: `edc70bacd23f2fc5f511ef4d97a33376e7b20bf8`
- Examples complete: **125/125**
- Integrity audit: **125/125** passed; patch-direction sample ok
- Source missing: **0**
- Patch truncated: **2**
- Test representations truncated: **133** (recorded; no bugs excluded)
- Metadata exceptions: **none**

## Commands

```bash
python -u scripts/prepare_dataset.py --split evaluation --allow-evaluation
python -u scripts/audit_phase3.py --split evaluation
```

## Notes

- `JacksonDatabind-62` initially failed with a Defects4J export timeout; retried
  with `--force --only JacksonDatabind-62` and completed.
- No ranking / FDR outcomes inspected. Model-visible states audited for
  pipeline label leakage only.

Machine records:

- `results/prepare_dataset-evaluation.json`
- `results/phase7/extraction_audit.json`
- `results/phase7/prepare_dataset-evaluation.log`
