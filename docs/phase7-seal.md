# Phase 7 raw-evaluation seal (P7-09)

**Overall: `PASS`**

Phase 7 evaluation raw results are sealed. Phase 8 must load these immutable
inputs only — no provider calls, no ranking repair, no aggregate analysis before
verifying this seal.

## Freeze identity

- `freeze_tag`: `experiment-v1`
- `experiment_commit`: `edc70bacd23f2fc5f511ef4d97a33376e7b20bf8`
- `run_id`: `eval-v1-20260923T035853+0000`
- `sealed_at`: `2026-09-23T15:24:01+00:00`

## Primary artifacts

| Artifact | Path | SHA-256 |
| --- | --- | --- |
| Predictions | `results/predictions.jsonl` | `551094261bbc1c151964b2c3602ad84482816de73304c9257e2f7d7f1fcbe747` |
| Raw-result index | `results/phase7/raw_result_index.json` | `27046f75b95a07630a14565691c6524f65ff3b482eae69e11536b2c08d0762ab` |
| Seal record | `results/phase7/raw_evaluation_seal.json` | `42ba0e4af46cde629d211f6834de18feec11fef86aae1c3746e61c06d2934386` |

## Coverage

- Evaluation bugs: **125** (Cli/Lang/Math/Jsoup/JacksonDatabind × 25)
- BM25 / Embedding / GPT-Nano / Random: **125/125**
- Jev: **113/125** (12 accepted A-001 gaps)
- `predictions.jsonl` lines: **72401**

## Offline Phase 8 read

```bash
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 python -c "
from pathlib import Path
import json
from src.example_contract import sha256_file
seal=json.loads(Path('results/phase7/raw_evaluation_seal.json').read_text())
assert sha256_file(Path(seal['predictions']['path']))==seal['predictions']['sha256']
assert sha256_file(Path(seal['raw_result_index']['path']))==seal['raw_result_index']['sha256']
print('seal-ok', seal['experiment_commit'], seal['run_id'])
"
```

Do **not** compute FDR, candidate recall, method deltas, or failure cases until
this seal verifies.
