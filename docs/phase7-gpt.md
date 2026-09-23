# Phase 7 GPT-Nano shortlist scoring (P7-06)

**Overall: `PASS`**

- `experiment_commit`: `edc70bacd23f2fc5f511ef4d97a33376e7b20bf8`
- Model: `gpt-5.4-nano-2026-03-17` (`reasoning.effort=none`)
- Prompt: `gpt-would_detect_regression-v1`
- Bugs complete: **125/125**
- Pairs scored: **13414 / 13414**
- Failures: **0**
- Spend ceiling: `$16.23` (operational)

Same sealed BM25 shortlists and patch/test state bytes as Jev (`build_jev_state`).
Unlike Jev, GPT accepts the Jsoup `file://etc/passwd` representations (no WAF gap).

## Commands

```bash
python -u scripts/run_gpt.py --split evaluation --allow-evaluation \
  --model primary --max-concurrency 16 --spend-ceiling-usd 16.23
python -u scripts/audit_gpt.py --split evaluation
```

Machine records:

- `results/gpt_scoring_summary-evaluation.json`
- `results/phase7/gpt_audit.json`
- `results/phase7/run_gpt-evaluation.log`
