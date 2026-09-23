# Phase 8 input validation (P8-01)

**Overall: `PASS`**

Offline loader accepts the sealed Phase 7 snapshot with no provider credentials
or network use.

- `experiment_commit`: `edc70bacd23f2fc5f511ef4d97a33376e7b20bf8`
- `freeze_tag`: `experiment-v1` (overall.md alias `experiment-v1-frozen`)
- Evaluation bugs: **125/125**
- Method coverage: BM25/Embedding/GPT-Nano/Random **125**; Jev **113** (+12 accepted gaps)
- Predictions: **72,401** lines, hash-locked to the Phase 7 seal

## Commands

```bash
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 python -u scripts/validate_evaluation_inputs.py

docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 python -m unittest tests.test_phase8_inputs -v
```

## Rejection checks

Unit tests confirm fail-closed behavior for:

- Tampered `predictions.jsonl` hash in the seal
- Modified BM25 ranking bytes (index hash mismatch)
- Seal `experiment_commit` that disagrees with `freeze_lock`

## Artifacts

- Loader: [`src/evaluation_inputs.py`](../src/evaluation_inputs.py)
- CLI: [`scripts/validate_evaluation_inputs.py`](../scripts/validate_evaluation_inputs.py)
- Report: [`results/phase8/input_validation.json`](../results/phase8/input_validation.json)
- Tests: [`tests/test_phase8_inputs.py`](../tests/test_phase8_inputs.py)
