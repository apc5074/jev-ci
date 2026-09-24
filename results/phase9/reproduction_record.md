# Phase 9 offline reproduction record (P9-06)

**Overall: `PASS`**

Generated: 2026-09-24T03:19:08+00:00

## Environment

- Offline: `True`
- Credentials cleared: `{'OPENROUTER_API_KEY': True, 'OPENAI_API_KEY': True, 'TYPESAFE_API_KEY': True, 'ANTHROPIC_API_KEY': True}`
- Paid requests during reproduction: **0**

## evaluate.py

- Freeze tag: `experiment-v1`
- Experiment commit: `edc70bacd23f2fc5f511ef4d97a33376e7b20bf8`
- Checks: 16/16
- Byte-identical stable artifacts: **True** (diffs=0)

## Report reconciliation

- Claims vs cohort/stats: `{'jev_fdr_at_10pct': 0.9558, 'bm25_fdr_at_10pct': 0.7345, 'delta_pp': 22.1, 'bootstrap_ci95': [0.133, 0.31], 'mcnemar_p': 4.649162292480469e-06, 'practical_success': True, 'winning_alternative': 'alt1', 'n_evaluation_bugs': 113, 'cost_ratio_jev_gpt': 0.2535714158562438}`
- README/report text checks OK: `True`

## Inventory

- Required files present: `True`
- Missing: `[]`

## Commands

```bash
docker run --rm --platform linux/amd64 --network=none -v "$(pwd):/workspace" -w /workspace jev-ci:phase1 python -u scripts/evaluate.py
```

```bash
docker run --rm --platform linux/amd64 --network=none -v "$(pwd):/workspace" -w /workspace jev-ci:phase1 python -u scripts/reproduce_phase9.py
```

## Caveats

- Reproduction attaches the existing sealed data/cache tree; it does not re-download Defects4J checkouts or re-call providers.
- Phase 9 failure_analysis categories are curated constants validated against the mechanical case list; they regenerate as the same table.
