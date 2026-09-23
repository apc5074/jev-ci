# Phase 4 verification — BM25 retrieval audit

Record of the P4-06 integrity pass over the 25 locked development rankings and
candidate shortlists.

## Commands

```bash
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 \
  python scripts/run_candidates.py --split development

docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 \
  python scripts/audit_phase4.py

docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 \
  python -m unittest discover -s tests -v
```

JSON report: [`results/audit-phase4.json`](../results/audit-phase4.json).

## Results

| Check | Result |
| --- | --- |
| Development rankings audited | 25 / 25 passed |
| Ranking = permutation of inventory | ok |
| Shortlist = exact top-`K` prefix | ok |
| Finite scores; rank 1..N; score↓ / FQCN↑ | ok |
| `K = min(200, N)`; ID uniqueness | ok |
| Provenance / shortlist hashes | ok |
| Evaluation candidate/ranking artifacts | **0** |
| Development candidate trigger recall@K | **25 / 25 (100%)** |

## Development candidate recall (diagnostic only)

Definition: fraction of the **25 development** bugs with at least one known
triggering class in the BM25 top `K` (`K=min(200,N)`).

This is **not** the 125-bug evaluation `candidate_recall@200` and must not
appear as a headline evaluation number.

| Scope | Value |
| --- | --- |
| Bugs with trigger in top K | 25 |
| Bugs audited | 25 |
| Recall | 1.0 |

## Case inspection (no tuning)

Earliest first-trigger ranks (examples): Lang-3, Lang-15, Math-25 / Math-7 /
Math-27 / several JacksonDatabind IDs at rank 1.

Later first-trigger ranks still inside K: Cli-15 (28), JacksonDatabind-105 (21),
JacksonDatabind-28 (16), Cli-1 (14).

**No implementation defects found.** Methodological choices to freeze in Phase 6
(unchanged by this diagnostic):

- Query diff = model-visible `representation.txt`
- Document = FQCN + full fixed source (FQCN-only if missing)
- Tokenizer `jev-code-tokenizer-v1`; BM25 `jev-bm25-v1` (`k1=1.5`, `b=0.75`)
- Tie-break: score desc, FQCN asc
- `K_cap = 200` fixed

Do **not** raise `K`, expand queries, or alter the corpus from these ranks.

## Phase 5 handoff

See [`phase5-handoff.md`](phase5-handoff.md). Reader:
`src.candidates.load_candidates` + `shortlist_sha256` / `require_hash`.

## Related

- Candidate generation summary: [`results/run_candidates-development.json`](../results/run_candidates-development.json)
- Shortlist layout: [`candidates.md`](candidates.md)
