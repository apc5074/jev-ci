# BM25 candidates and rankings (Phase 4)

Persist the full-suite BM25 ranking and its exact top-`K` shortlist.
Implementation: [`src/candidates.py`](../src/candidates.py).

## Paths

| Artifact | Path |
| --- | --- |
| Shortlist (Phase 5) | `data/candidates/<project>_<bug>.json` |
| Full ranking | `results/rankings/<project>_<bug>.json` |
| Semantic lock | `data/candidates/<slug>.json.semantic_lock` |

## Shortlist rule

```text
K = min(200, N)   # CANDIDATE_K_CAP = 200 (fixed)
```

`candidate_ids` is the first `K` FQCNs of the full ranking in BM25 order (score
desc, FQCN asc). It is never re-sorted separately.

`shortlist_sha256` hashes the ordered IDs (`FQCN\\n` lines). Phase 5 must verify
this hash before Jev/GPT scoring.

## Provenance

Both files record manifest Defects4J commit/seed, split, `N`/`K`, tokenizer/BM25
settings, and lexical `input_hashes`. Trigger labels never appear.

## Safe reruns

| Situation | Behavior |
| --- | --- |
| Existing artifacts match hashes/IDs/settings | **Reuse** (no rewrite) |
| Missing or stale | Write ranking first, then candidates (atomic tmp+replace) → **written** / **regenerated** |
| `*.json.semantic_lock` present | Refuse overwrite unless `force=True` |

## Phase 5 reader

```python
from src.candidates import load_candidates, verify_shortlist_is_ranking_prefix, load_ranking

c = load_candidates("Cli-30")           # checks K, uniqueness, shortlist_sha256
r = load_ranking("Cli-30")
verify_shortlist_is_ranking_prefix(candidates=c, ranking=r)
ids = c["candidate_ids"]                # identical ordered list for Jev and GPT
```

## One-bug CLI

```bash
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 \
  python src/candidates.py Cli-30
```

Batch generation for all development bugs:

```bash
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 \
  python scripts/run_candidates.py --split development
```

Summary (counts only; no trigger IDs): `results/run_candidates-development.json`.
Evaluation requires `--split evaluation --allow-evaluation` (post-freeze).
Reruns reuse validated artifacts when input hashes match.
