# BM25 scoring (Phase 4)

Suite-level BM25 baseline and candidate generator. Implementation:
[`src/bm25.py`](../src/bm25.py) (scorer) and [`src/ranking.py`](../src/ranking.py)
(`rank_suite`).

| Constant | Value |
| --- | --- |
| `BM25_VERSION` | `jev-bm25-v1` |
| `k1` | `1.5` |
| `b` | `0.75` |

## Formula

Nonnegative IDF:

```text
IDF(t) = ln(1 + (N - df(t) + 0.5) / (df(t) + 0.5))
```

Document score (sum over **distinct** query terms `t`, first-seen order):

```text
score(d) = Σ_t  IDF(t) · (tf(t,d) · (k1 + 1))
                    / (tf(t,d) + k1 · (1 - b + b · |d| / avgdl))
```

| Symbol | Meaning |
| --- | --- |
| `tf(t,d)` | Raw count of term `t` in document `d` |
| `df(t)` | Number of corpus documents with `tf(t,·) > 0` |
| `|d|` | Token count of `d` |
| `N` | Corpus size = number of test classes ranked |
| `avgdl` | Mean `|d|` over those same `N` tokenized documents (includes FQCN-only docs) |
| Repeated query tokens | Collapsed; each distinct term contributes once (`qtf = 1`) |

Empty query → all scores `0.0`. No negative contributions. Scores are always
finite.

## Ranking order

1. Descending BM25 score
2. Ascending FQCN for exact ties

Trigger labels are never used for scoring or tie-breaks.

## Corpus

Built per bug from **all** inventory / `tests.all` classes via the lexical
contract ([bm25-lexical-contract.md](bm25-lexical-contract.md)). Tokenizer:
[tokenizer.md](tokenizer.md).

## Check

```bash
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 \
  python -m unittest tests.test_phase4_bm25 -v
```
