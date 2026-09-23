"""BM25 scoring primitive (Phase 3 window selection + Phase 4 suite ranking).

Parameters (``overall.md`` section 13; locked):

- ``k1 = 1.5``
- ``b = 0.75``

## Formula

Nonnegative IDF:

    IDF(t) = ln(1 + (N - df(t) + 0.5) / (df(t) + 0.5))

where ``N`` is the number of documents in the corpus and ``df(t)`` is the
number of documents containing term ``t`` at least once (clamped to
``[0, N]``).

Document score (sum over distinct query terms ``t``):

    score(d) = Σ_t  IDF(t) * (tf(t,d) * (k1 + 1))
                         / (tf(t,d) + k1 * (1 - b + b * |d| / avgdl))

Definitions:

- **Term frequency** ``tf(t,d)``: raw count of ``t`` in document ``d``.
- **Document frequency** ``df(t)``: count of documents with ``tf(t,·) > 0``.
- **Document length** ``|d|``: total token count in ``d`` (sum of raw tfs).
- **Average length** ``avgdl``: mean ``|d|`` over the same ``N`` tokenized
  documents being ranked (including FQCN-only fallback documents).
- **Repeated query terms:** the query is reduced to **distinct** tokens in
  first-seen order; each distinct term contributes once (``qtf = 1``). Raw
  query multiplicity does not scale the score.

Empty query or empty corpus → all scores ``0.0``. Terms with ``tf = 0`` in a
document contribute nothing to that document (no negative scores).

Phase 4 suite order: descending score, then ascending FQCN for exact ties.
Trigger labels are never used.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any, Sequence

BM25_K1 = 1.5
BM25_B = 0.75
BM25_VERSION = "jev-bm25-v1"

BM25_CONFIG: dict[str, object] = {
    "version": BM25_VERSION,
    "k1": BM25_K1,
    "b": BM25_B,
    "idf": "nonnegative_ln_1_plus_(N-df+0.5)/(df+0.5)",
    "query_term_policy": "distinct_first_seen_qtf_1",
    "tf": "raw_count",
    "length": "token_count",
    "avgdl": "mean_over_ranked_corpus",
}


def bm25_provenance() -> dict[str, Any]:
    """Fields to embed in ranking / candidate provenance records."""
    return {
        "bm25_version": BM25_VERSION,
        "bm25_k1": BM25_K1,
        "bm25_b": BM25_B,
    }


def _distinct_preserve_order(tokens: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for tok in tokens:
        if tok in seen:
            continue
        seen.add(tok)
        out.append(tok)
    return out


def bm25_idf(*, n_docs: int, df: int) -> float:
    """Nonnegative BM25 IDF for a term with document frequency ``df``."""
    if n_docs <= 0:
        return 0.0
    # Clamp df into [0, N] for safety.
    df_c = min(max(df, 0), n_docs)
    return math.log(1.0 + (n_docs - df_c + 0.5) / (df_c + 0.5))


def bm25_scores(
    query_tokens: Sequence[str],
    documents: Sequence[Sequence[str]],
    *,
    k1: float = BM25_K1,
    b: float = BM25_B,
) -> list[float]:
    """Score each tokenized document against the query with standard BM25."""
    n_docs = len(documents)
    if n_docs == 0:
        return []
    query = _distinct_preserve_order(query_tokens)
    if not query:
        return [0.0] * n_docs

    doc_tfs: list[Counter[str]] = [Counter(doc) for doc in documents]
    doc_lens = [sum(tf.values()) for tf in doc_tfs]
    avgdl = sum(doc_lens) / n_docs if n_docs else 0.0

    df: Counter[str] = Counter()
    for tf in doc_tfs:
        for term in tf:
            df[term] += 1

    scores = [0.0] * n_docs
    for term in query:
        idf = bm25_idf(n_docs=n_docs, df=df.get(term, 0))
        for i, tf in enumerate(doc_tfs):
            freq = tf.get(term, 0)
            if freq == 0:
                continue
            dl = doc_lens[i]
            denom = freq + k1 * (1.0 - b + b * (dl / avgdl if avgdl > 0 else 0.0))
            scores[i] += idf * (freq * (k1 + 1.0)) / denom
    return scores


def bm25_corpus_stats(
    documents: Sequence[Sequence[str]],
) -> dict[str, float | int]:
    """Corpus size and average document length from tokenized docs being ranked."""
    n_docs = len(documents)
    if n_docs == 0:
        return {"n_docs": 0, "avgdl": 0.0, "total_tokens": 0}
    lengths = [len(doc) for doc in documents]
    total = sum(lengths)
    return {
        "n_docs": n_docs,
        "avgdl": total / n_docs,
        "total_tokens": total,
    }
