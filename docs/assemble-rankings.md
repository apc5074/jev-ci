# Semantic ranking assembly (Phase 5 / P5-08)

Build full-suite Jev and GPT rankings from one shared BM25 shortlist.
Implementation: [`src/assemble_rankings.py`](../src/assemble_rankings.py)
(re-exported from [`src/ranking.py`](../src/ranking.py)).

## Rules

| Rule | Behavior |
| --- | --- |
| Shortlist source | Saved Phase-4 `data/candidates/<slug>.json` only — never regenerated |
| Score gate | Every shortlisted class needs one valid cached score in `[0,1]` |
| Prefix order | Score ↓, then original BM25 rank ↑ |
| Tail | BM25 ranks `K+1..N` unchanged (byte-for-byte) |
| Fail closed | Missing / non-finite / out-of-range / model-mismatch scores abort |

Jev and every GPT comparison model must share the same `candidate_ids` and
`shortlist_sha256`. Development artifacts land under
`results/semantic/<method_slug>/`.

## Outputs

```text
results/semantic/jev/Cli_30.json
results/semantic/gpt_nano/Cli_30.json
results/semantic/gpt_4_1_nano/Cli_30.json   # when that model’s shortlist is cached
results/semantic/gpt_4o_mini/Cli_30.json
results/semantic/gpt_luna/Cli_30.json
results/semantic_assembly_summary.json
```

Each ranking document stores `candidate_ids`, `prefix_order`, `tail_ids`,
per-class `score` / `bm25_rank`, and model/provider/prompt provenance.

## Usage

```bash
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 \
  python -m src.assemble_rankings Cli-30

# Primary GPT only (skip secondary comparison models if unscored)
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 \
  python -m src.assemble_rankings Cli-30 --only-primary-gpt
```

```python
from src.ranking import assemble_jev_ranking, assemble_gpt_ranking

jev = assemble_jev_ranking("Cli-30")
gpt = assemble_gpt_ranking("Cli-30")  # GPT-Nano primary
```

Full 25-bug scoring remains P5-09; P5-08 only assembles where caches are
complete (development proof: Cli-30).
