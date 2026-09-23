"""Minimal BM25 scoring primitive (Phase 3 window selection; Phase 4 extends).

Parameters (``overall.md`` section 13):

- ``k1 = 1.5``
- ``b = 0.75``

IDF uses the nonnegative form:

    IDF(q_i) = ln(1 + (N - df + 0.5) / (df + 0.5))

Query terms are the distinct tokens in the query (first-seen order). Each
distinct term contributes once (``qtf = 1``). Document term frequency is the
raw count in that document. Empty query or empty corpus yields all-zero scores.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Sequence

BM25_K1 = 1.5
BM25_B = 0.75
BM25_VERSION = "jev-bm25-v1"


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
