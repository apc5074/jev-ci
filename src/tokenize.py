"""Single code tokenizer for lexical retrieval (Phase 3 windows + Phase 4 BM25).

Algorithm (``overall.md`` section 12):

1. Split at non-alphanumeric characters
2–4. Split camelCase / PascalCase / acronym / snake_case boundaries
5. Lowercase
6. Discard empty tokens
7. Discard tokens of length 1

No stemming. Keep English stopwords and Java keywords.
"""

from __future__ import annotations

import re
from typing import Iterable

# Bump when tokenizer behavior changes; Phase 4 rankings must invalidate.
TOKENIZER_VERSION = "jev-code-tokenizer-v1"

_NON_ALNUM_SPLIT = re.compile(r"[^A-Za-z0-9]+")
# lower/digit → Upper; acronym run → Upper+lower (HTTPResponse → HTTP, Response)
_CAMEL_BOUNDARIES = re.compile(
    r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])"
)


def split_camel_pascal(token: str) -> list[str]:
    """Split one alphanumeric identifier on camelCase / PascalCase / acronyms."""
    if not token:
        return []
    parts = _CAMEL_BOUNDARIES.split(token)
    return [p for p in parts if p]


def tokenize(text: str) -> list[str]:
    """Tokenize source or query text into the shared lexical vocabulary."""
    if not text:
        return []
    out: list[str] = []
    for piece in _NON_ALNUM_SPLIT.split(text):
        if not piece:
            continue
        for part in split_camel_pascal(piece):
            tok = part.lower()
            if len(tok) <= 1:
                continue
            out.append(tok)
    return out


def tokenize_many(texts: Iterable[str]) -> list[list[str]]:
    return [tokenize(t) for t in texts]
