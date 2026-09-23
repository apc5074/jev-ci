# BM25 lexical input contract (Phase 4)

Locked query and document assembly for suite-level BM25. Implemented in
[`src/ranking.py`](../src/ranking.py). Tokenizer and BM25 scoring remain in
[`src/tokenize.py`](../src/tokenize.py) / [`src/bm25.py`](../src/bm25.py)
(Phase 3 primitives; do not fork).

Contract version: `jev-bm25-lexical-v1` (`LEXICAL_INPUT_CONTRACT_VERSION`).

## Document (one per `tests.all` class)

Inventory order from `data/tests/<slug>/inventory.json` → `test_classes` /
`source_map`.

| Inventory | BM25 document text |
| --- | --- |
| `source_missing=false` and mapped file present under fixed checkout | `{FQCN}\n` + **entire** fixed-revision Java source (LF-normalized UTF-8) |
| `source_missing=true` (or no `source_file`) | `{FQCN}` only |

Rules:

- Do **not** use the compact 12,000-character semantic representation or its
  selected windows as the corpus document.
- If inventory claims source is available but the file is absent under
  `data/bugs/<slug>/checkouts/fixed/`, **fail** with a clear error. Do not
  silently fall back to compact text.
- Long tests contribute full source (no windowing for Phase 4 BM25).

## Query (locked for Phase 6)

```text
diff_source = model_visible_representation
```

Query text = entire `data/patches/<slug>/representation.txt`, which already
contains:

1. modified production file paths (`MODIFIED FILES`)
2. modified class names (`MODIFIED CLASSES`)
3. the capped proposed unified diff (`PROPOSED CODE CHANGE`)

Lexical and semantic rankers therefore share the same change context. The
untruncated `regression_patch.diff` stays audit-only and is **not** used as the
BM25 query.

## Exclusions

Never read into documents, queries, or ranking features:

- `labels.json` / `positive_classes` / `trigger_methods`
- `raw/tests.trigger`
- bug outcome / Defects4J status labels

Use labels only later for development diagnostics (candidate recall), not for
scoring or tie-breaks.

## Provenance hashes

`build_lexical_inputs()` returns `input_hashes` used to detect stale rankings
when Phase 3 artifacts change:

| Key | Meaning |
| --- | --- |
| `lexical_input_contract_version` | This contract id |
| `query_diff_source` | `model_visible_representation` |
| `test_class_ids_sha256` | Ordered inventory FQCNs |
| `query_sha256` | Query text UTF-8 |
| `documents_sha256` | Ordered `FQCN:text_sha256` lines |
| `inventory_sha256` | `inventory.json` file |
| `patch_representation_sha256` | `representation.txt` file |
| `num_documents` / `source_missing_count` | Counts |

A tokenizer or contract version bump before Phase 6 must invalidate saved BM25
rankings and candidate lists. Tokenizer version/config hash fields are recorded
in `input_hashes` via `tokenizer_provenance()` (see [tokenizer.md](tokenizer.md)).

## Small example

Synthetic inventory for classes `a.ATest` (source present) and `b.BTest`
(missing):

```text
# Document 1 (available source)
a.ATest
package a;
public class ATest { ... entire file ... }

# Document 2 (missing source)
b.BTest

# Query (from representation.txt)
MODIFIED FILES:
src/main/java/a/Foo.java

MODIFIED CLASSES:
a.Foo

PROPOSED CODE CHANGE:
--- src/main/java/a/Foo.java
+++ src/main/java/a/Foo.java
@@ ...
```

## CLI check

```bash
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 \
  python src/ranking.py Cli-30
```
