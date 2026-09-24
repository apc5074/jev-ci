# Headline results (evaluation, n=113)

Fixed method order: Random, BM25, Embedding, Jev, GPT-5.4 nano. **FDR@10%** is the primary outcome. Twelve A-001 Jsoup bugs are excluded from every method (see README).

| Method | FDR@5% | FDR@10% | FDR@20% | MRR | APFD | Median NFTR | Cost/Bug |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Random | 0.0696 | 0.1229 | 0.2277 | 0.0826 | 0.5201 | 0.4780 | — |
| BM25 | 0.6372 | 0.7345 | 0.8496 | 0.5096 | 0.9005 | 0.0435 | — |
| Embedding | 0.8319 | 0.8850 | 0.9115 | 0.6783 | 0.9396 | 0.0168 | 0.001348 |
| Jev | 0.9027 | **0.9558** | **0.9823** | **0.8222** | **0.9722** | **0.0119** | 0.013878 |
| GPT-5.4 nano | **0.9204** | 0.9204 | 0.9646 | 0.8024 | 0.9638 | **0.0119** | 0.054729 |

## Presentation notes

- Bold marks the best quality value in each column (highest FDR/MRR/APFD; **lowest** median NFTR). Ties are all bolded.
- Cost/Bug is **not** treated as a quality metric and is never bolded.
- Random and BM25 show an em dash (—): they incur no paid API cost under the Phase 6 pricing snapshot.
- Paid Cost/Bug is mean **effective prepaid credits** per headline-cohort evaluation bug (Embedding / Jev / GPT-5.4 nano), from the frozen usage ledger ÷ 113.
- Primary contrast: Jev FDR@10% = 0.9558 vs BM25 = 0.7345 (Δ = +22.1 pp).

## Provenance

- Freeze tag: `experiment-v1`
- Experiment commit: `edc70bacd23f2fc5f511ef4d97a33376e7b20bf8`
- Run ID: `eval-v1-20260923T035853+0000`
- Phase 8 analysis seal: `6d3bf370b2b901dbb44608243e3684792a7a13e6845746314035c6a8974b10f1`
- `metrics.csv`: `4bd4be3cc3f59e8d90b6fb4c847d45995bf6f97697a0a0d6b6dadb2ab9ecb32e`
- `statistics.json`: `9df933050134bf6eaa3aaca46534e07e41b5c5662ae4a0e75128d06f6bb3bdd7`
- `figure_data.json`: `739c36b66f34afd366f5a43a2c4052c505abbce60378c4ef88e2caaf504bc7e3`

Values are generated from sealed Phase 8 cohort summaries and cross-checked against `metrics.csv` and the cost ledger — not hand-copied.
