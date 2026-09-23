# Phase 7 predictions export (P7-08)

**Overall: `PASS`**

- `experiment_commit`: `edc70bacd23f2fc5f511ef4d97a33376e7b20bf8`
- `run_id`: `eval-v1-20260923T035853+0000`
- `results/predictions.jsonl`: **72,401** lines  
  (`sha256=551094261bbc1c151964b2c3602ad84482816de73304c9257e2f7d7f1fcbe747`)
- Hashed index: [`results/phase7/raw_result_index.json`](../results/phase7/raw_result_index.json)

## What was exported

One JSONL row per `(bug, method, test_class)` for evaluation bugs:

| Method | Rows | Notes |
| --- | ---: | --- |
| BM25 | 18,194 | Full-suite lexical scores |
| Embedding | 18,194 | Full-suite cosine scores + embedding cache usage |
| GPT-Nano | 18,194 | Shortlist scores; tail `score=null`, `score_applicable=false` |
| Jev | 17,819 | Same shortlist/tail rule; **12** WAF-gap bugs omitted |

Inapplicable semantic scores are recorded explicitly (`inapplicable_reason=outside_bm25_shortlist`); no values are invented. Accepted Jev A-001 gaps have **no** Jev rows.

Random is **not** flattened into JSONL; seeds/permutation fingerprints live under `results/random/` and are hashed in the index (regenerate with `generate_permutations`).

Private trigger labels are hashed in the index only; they are never copied into `predictions.jsonl`.

## Commands

```bash
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 python -u scripts/export_predictions.py
```

Offline read for Phase 8:

```bash
python -c "import json; print(json.load(open('results/phase7/raw_result_index.json'))['predictions'])"
```

## Machine records

- `results/predictions.jsonl`
- `results/phase7/raw_result_index.json`
- `results/phase7/predictions_export.json`
- `results/phase7/export_predictions.log`
