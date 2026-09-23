# Jev CI test-selection experiment

Static regression-test prioritization experiment using Defects4J 3.0.1 and the Jev decision model. Design and rules live in `Plans/overall.md`.

## Quick start

```bash
docker build --platform linux/amd64 -t jev-ci:phase1 .
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 \
  python scripts/check_environment.py
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 \
  python src/select_bugs.py verify
```

## Docs

| Doc | Contents |
| --- | --- |
| [docs/setup.md](docs/setup.md) | Build, run, smoke check |
| [docs/phase3-handoff.md](docs/phase3-handoff.md) | Locked split for Phase 3 |
| [docs/verification-phase2.md](docs/verification-phase2.md) | Manifest lock record |
| [docs/manifest.md](docs/manifest.md) | Manifest schema / create / verify |
| [docs/testing.md](docs/testing.md) | Phase 2 unit tests |
| [docs/example-contract.md](docs/example-contract.md) | Phase 3 layout, visibility, prepare_dataset |
| [docs/patch-truncation.md](docs/patch-truncation.md) | 12k patch cap / marker-reserving rule |
| [docs/test-representations.md](docs/test-representations.md) | Test compaction, tokenizer/BM25 versions |
| [docs/verification-phase3.md](docs/verification-phase3.md) | Phase 3 integrity audit record |
| [docs/phase4-handoff.md](docs/phase4-handoff.md) | Artifacts and lexical primitives for Phase 4 |
| [docs/bm25-lexical-contract.md](docs/bm25-lexical-contract.md) | Phase 4 BM25 query/document input contract |
| [docs/tokenizer.md](docs/tokenizer.md) | Shared code tokenizer rules / version |
| [docs/bm25-scoring.md](docs/bm25-scoring.md) | BM25 formula, corpus, suite ranking order |
| [docs/candidates.md](docs/candidates.md) | Shortlist / full-ranking artifacts and Phase 5 reader |
| [docs/verification-phase4.md](docs/verification-phase4.md) | Phase 4 BM25 retrieval audit record |
| [docs/phase5-handoff.md](docs/phase5-handoff.md) | Fixed shortlist contract for Jev/GPT |
| [docs/jev-provider-decision.md](docs/jev-provider-decision.md) | Jev route selection / pricing / probe gate |
| [docs/cache-ledger.md](docs/cache-ledger.md) | Semantic cache keys, failures, usage ledger |
| [docs/random-baseline.md](docs/random-baseline.md) | Seeded Random permutations / index convention |
| [docs/embeddings.md](docs/embeddings.md) | Full-suite Embedding baseline / over-limit rule |
| [docs/jev-ranker.md](docs/jev-ranker.md) | One-pair Jev Noul client / captured request |
| [docs/gpt-ranker.md](docs/gpt-ranker.md) | Multi-model GPT comparison clients |
| [docs/semantic-scheduler.md](docs/semantic-scheduler.md) | Concurrency, retries, spend ceiling |
