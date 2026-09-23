# Phase 5 handoff (from Phase 4)

Phase 4 produced deterministic BM25 full-suite rankings and fixed top-`K`
shortlists for all **25 development** bugs. Phase 5 semantic rerankers (Jev and
GPT) must consume **one shared ordered shortlist per bug** — never re-run BM25
or choose candidates independently.

## Do not

- Resample `data/manifest.json` or retokenize / rescore the BM25 corpus
- Generate evaluation rankings/shortlists until the Phase 6 freeze
- Put `labels.json` / trigger IDs into model requests
- Change `K_cap=200`, query/document contract, or tie-breaks from development
  recall diagnostics

## Load the shortlist (both Jev and GPT)

```python
from src.candidates import load_candidates, shortlist_content_hash

doc = load_candidates("Cli-30")
ids = doc["candidate_ids"]          # ordered BM25 top-K
assert doc["shortlist_sha256"] == shortlist_content_hash(ids)

# Optional: pin the hash before a scoring run
doc = load_candidates("Cli-30", require_hash=doc["shortlist_sha256"])
```

| Field | Meaning |
| --- | --- |
| `candidate_ids` | Exact BM25 prefix length `K=min(200,N)` |
| `shortlist_sha256` | Content hash of that ordered list |
| `N`, `K`, `k_cap` | Corpus size and shortlist size (`k_cap=200`) |
| `input_hashes` / `settings` | Provenance for staleness checks |

Full ranking (scores + BM25 tail) lives at
`results/rankings/<slug>.json`. After semantic scores on the prefix, append the
**untouched** BM25 order for ranks `K+1..N`.

## Integrity already passed

See [`verification-phase4.md`](verification-phase4.md) and
`results/audit-phase4.json`. Re-run:

```bash
python scripts/audit_phase4.py
```

Development candidate trigger recall@K was **25/25** (diagnostic only).

## Locked inputs (carry into Phase 6)

| Choice | Value |
| --- | --- |
| Query | model-visible `representation.txt` |
| Document | FQCN + full fixed source |
| Tokenizer | `jev-code-tokenizer-v1` |
| BM25 | `jev-bm25-v1`, `k1=1.5`, `b=0.75` |
| Order | score ↓, FQCN ↑ |
| Shortlist | `K=min(200,N)` exact ranking prefix |
| Jev provider | OpenRouter `typesafe/jev-1.13` (observed `…-20260917`); TypeSafe direct unavailable ([jev-provider-decision.md](jev-provider-decision.md)) |
| Random index | **zero-based** in locked manifest lists; eval seed `1337+i`; dev seed `1001337+i` ([random-baseline.md](random-baseline.md)) |
| Embedding | `text-embedding-3-small`, full suite, cosine↓ FQCN↑; over-limit `fail_closed_no_truncate_v1` ([embeddings.md](embeddings.md)) |
| Jev client | OpenRouter `typesafe/jev-1.13`; one-pair Noul; prompt `jev-would_detect_regression-v1` ([jev-ranker.md](jev-ranker.md)) |
| GPT clients | Primary `gpt-5.4-nano-2026-03-17` (`reasoning.effort=none`) + `gpt-4.1-nano` + `gpt-4o-mini` + `gpt-luna`/`gpt-5.6-luna` ([gpt-ranker.md](gpt-ranker.md)) |
| Scheduler | ≤16 concurrent; retry 429/5xx; optional spend ceiling / max_rpm ([semantic-scheduler.md](semantic-scheduler.md)) |
| Assembly | Shared shortlist; score↓ / BM25-rank↑ prefix; BM25 tail unchanged ([assemble-rankings.md](assemble-rankings.md)) |

## Development run status (P5-09)

Commands: [phase5-run.md](phase5-run.md). Audit: `results/audit-phase5.json`. Usage: `results/phase5_usage_report.json`.

| System | Development coverage |
| --- | --- |
| Random / BM25 / Embedding | 25/25 |
| GPT-Nano (primary) | 25/25 assembled under `results/semantic/gpt_nano/` |
| Jev | **24/25** — see unresolved issue below |
| Cache-only rerun | Passed (Cli-30 proof; no API keys) |
| Evaluation bugs scored | **No** |

### Unresolved availability (accepted for Phase 6 continuation)

OpenRouter’s Cloudflare edge returns **HTTP 403** on Jev System One requests whose model-visible state contains the literal substring `file://etc/passwd` (case-insensitive). In development this hits only:

- **Jsoup-70** / `org.jsoup.integration.ConnectTest`

GPT chat completions accept the same Phase-3 bytes. Do **not** truncate or rewrite the representation to bypass the WAF.

**Decision (2026-09-22):** Continue into Phase 6 with this single Jev score missing. Jsoup-70 still has Random, BM25, Embedding, and GPT-Nano. Revisit before evaluation freeze if TypeSafe direct or an OpenRouter WAF fix becomes available.
