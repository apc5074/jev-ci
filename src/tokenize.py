"""Single code tokenizer for lexical retrieval (Phase 3 windows + Phase 4 BM25).

Algorithm (``overall.md`` section 12):

1. Split at non-alphanumeric characters
2–4. Split camelCase / PascalCase / acronym / snake_case boundaries
5. Lowercase
6. Discard empty tokens
7. Discard tokens of length 1

No stemming. Keep English stopwords and Java keywords.

Boundary rules (locked; indexing and querying must not diverge):

- **Digits:** stay attached to adjacent ASCII letters in the same alphanumeric
  run (``test123Name`` → ``test123``, ``name``; ``v2API`` → ``v2``, ``api``).
  There is no letter/digit split beyond camelCase rules.
- **Repeated underscores / punctuation:** treated as non-alphanumeric separators
  (``foo__bar`` → ``foo``, ``bar``). Consecutive separators collapse.
- **Acronyms:** an uppercase run followed by Upper+lower splits before the last
  capital (``HTTPResponse`` → ``HTTP``, ``Response``; ``XMLHttpRequest`` →
  ``XML``, ``Http``, ``Request``; ``IOException`` → ``IO``, ``Exception``).
- **Unicode / non-ASCII:** any character outside ``[A-Za-z0-9]`` is a separator
  (``café`` → ``caf``). Non-ASCII letters are not kept as tokens.
- **Empty / whitespace-only input:** yields ``[]``.
- **Length-1 tokens:** discarded after lowercasing (``a``, ``I`` drop; ``if``
  and Java keywords of length ≥ 2 are kept).
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Iterable

# Bump when tokenizer behavior changes; Phase 4 rankings must invalidate.
TOKENIZER_VERSION = "jev-code-tokenizer-v1"

# Configuration fingerprint material. Change rules → bump version and this map.
TOKENIZER_CONFIG: dict[str, object] = {
    "version": TOKENIZER_VERSION,
    "split_non_alnum": True,
    "split_camel_pascal_acronym": True,
    "split_snake_via_non_alnum": True,
    "lowercase": True,
    "discard_empty": True,
    "discard_length_le": 1,
    "stem": False,
    "remove_english_stopwords": False,
    "remove_java_keywords": False,
    "letter_digit_split": False,
    "unicode_as_separator": True,
    "alnum_charset": "ASCII A-Za-z0-9 only",
}

_NON_ALNUM_SPLIT = re.compile(r"[^A-Za-z0-9]+")
# lower/digit → Upper; acronym run → Upper+lower (HTTPResponse → HTTP, Response)
_CAMEL_BOUNDARIES = re.compile(
    r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])"
)


def tokenizer_config_sha256() -> str:
    """Stable hash of tokenizer configuration for ranking provenance."""
    payload = json.dumps(TOKENIZER_CONFIG, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def tokenizer_provenance() -> dict[str, str]:
    """Fields to embed in BM25 / candidate provenance records."""
    return {
        "tokenizer_version": TOKENIZER_VERSION,
        "tokenizer_config_sha256": tokenizer_config_sha256(),
    }


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
