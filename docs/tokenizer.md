# Code tokenizer (Phases 3–4)

Single lexical tokenizer for Phase 3 long-test window selection and Phase 4
suite BM25. Module: [`src/tokenize.py`](../src/tokenize.py).

| Constant | Value |
| --- | --- |
| `TOKENIZER_VERSION` | `jev-code-tokenizer-v1` |
| Config hash | `tokenizer_config_sha256()` over `TOKENIZER_CONFIG` |

A version or config change before Phase 6 invalidates saved BM25 rankings and
candidate lists. After freeze, treat it as a disclosed methodological change.

## Algorithm

1. Split at non-alphanumeric characters (ASCII `A-Za-z0-9` only)
2–4. Split camelCase / PascalCase / acronym / snake_case boundaries
5. Lowercase
6. Discard empty tokens
7. Discard tokens of length ≤ 1

No stemming. Do **not** remove English stopwords or Java keywords.

## Boundary behavior

| Case | Behavior | Example |
| --- | --- | --- |
| Outline example | Ordered split | `parseHTTPResponse_v2` → `parse`, `http`, `response`, `v2` |
| Digits | Stay with adjacent letters in the same run; no letter/digit split | `test123Name` → `test123`, `name`; `v2API` → `v2`, `api` |
| Repeated `_` / punct | Separators collapse | `foo__bar` → `foo`, `bar` |
| Acronyms | Split before last capital of Upper+lower | `HTTPResponse` → `http`, `response`; `XMLHttpRequest` → `xml`, `http`, `request`; `IOException` → `io`, `exception` |
| Unicode / non-ASCII | Separator (not a token) | `café` → `caf` |
| Empty / whitespace | `[]` | `""`, `"   "` |
| Length-1 | Dropped; keywords ≥ 2 kept | `a if for` → `if`, `for` |

## Shared use

| Caller | Entry point |
| --- | --- |
| Phase 3 windows | `src.representations` → `tokenize(query_text)` / window bodies |
| Phase 4 BM25 | `src.ranking.tokenize_query` / `tokenize_document` → same `tokenize` |

Provenance: `tokenizer_provenance()` is merged into Phase 4 `input_hashes`
(`tokenizer_version`, `tokenizer_config_sha256`).

## Checks

```bash
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 \
  python -m unittest tests.test_phase4_tokenizer tests.test_phase3_representations.TokenizerTests -v
```
