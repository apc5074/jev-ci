# Embedding baseline (Phase 5 / P5-04)

Full-suite cosine ranking with `text-embedding-3-small`.
Implementation: [`src/embeddings.py`](../src/embeddings.py).

## What is embedded

| Input | Source |
| --- | --- |
| Query | Phase 3 patch `data/patches/<id>/representation.txt` |
| Documents | **Every** Phase 3 test `data/tests/<id>/representations/*.txt` |

Do **not** restrict to BM25's top-`K` shortlist. Do **not** mix BM25 scores
into the similarity.

## Ranking

```text
score = cosine(patch_vector, test_vector)
order = score descending, FQCN ascending on ties
```

## Provider

| Preference | When | Request model | Cache `model_id` |
| --- | --- | --- | --- |
| OpenAI direct | `OPENAI_API_KEY` set | `text-embedding-3-small` | `text-embedding-3-small` |
| OpenRouter | fallback / `--provider openrouter` | `openai/text-embedding-3-small` | `text-embedding-3-small` |

Vectors are cached under `cache/embeddings/` by canonical model + exact input
text, so identical representations share one vector across bugs.

## Over-limit rule (preregistered)

**`fail_closed_no_truncate_v1`**

- Provider limit: **8192 tokens** per input (`text-embedding-3-small`).
- If the provider rejects an input for context length / max tokens: write a
  failure cache entry, **abort** that bug's Embedding ranking, and **do not**
  truncate, chunk, or window-average the text.
- Phase 3 representations are capped at 12k characters and are expected to fit;
  an over-limit event is a hard stop for that example, not a silent recovery.

Recorded on every ranking as `over_limit_rule` / `max_input_tokens`.

## Artifacts

| Path | Contents |
| --- | --- |
| `cache/embeddings/<sha256>.json` | Vector + usage (gitignored) |
| `results/embeddings/<project>_<bug>.json` | Full ranking + provenance |
| `results/embeddings_summary.json` | Batch summary |

Rankings store scores and cache keys, not the raw vectors (vectors stay in
cache for reproducibility).

## Commands

```bash
# One development bug
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace --env-file .env \
  jev-ci:phase1 \
  python src/embeddings.py Cli-30 --split development

# All 25 development bugs
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace --env-file .env \
  jev-ci:phase1 \
  python scripts/run_embeddings.py --split development
```
