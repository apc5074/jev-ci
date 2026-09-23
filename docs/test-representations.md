# Test representation compaction (Phase 3)

Model-ready per-class text lives under `data/tests/<id>/representations/`. Built by
`src/representations.py` using the shared tokenizer (`src/tokenize.py`) and BM25
primitive (`src/bm25.py`) that Phase 4 must reuse for suite retrieval.

## Compaction

| Source lines | Behavior |
| --- | --- |
| ≤ 240 | Entire fixed-base file |
| > 240 | Reserve first **40** lines, then choose up to **3** 80-line windows (stride **60**) by BM25 × fraction of new lines; retain at most **240** source lines in source order, with omission markers |

Query for window scoring: model-visible `data/patches/<id>/representation.txt`.

## Missing source

```text
TEST CLASS:
<FQCN>

SOURCE FILE:
[SOURCE MISSING]

TEST SOURCE:
```

No invented test code. Ambiguous / missing inventory entries use this form.

## Truncation

Same 12,000 code-point hard cap and marker-reservation arithmetic as patches
([patch-truncation.md](patch-truncation.md)), with marker
`[...TEST TRUNCATED...]`.

## Shared lexical versions

| Component | Constant |
| --- | --- |
| Tokenizer | `jev-code-tokenizer-v1` (rules: [tokenizer.md](tokenizer.md)) |
| BM25 | `jev-bm25-v1` (`k1=1.5`, `b=0.75`, nonnegative IDF) |

## Version 2 amendment (before evaluation freeze)

`jev-test-context-v2` reserves file context and discounts redundant windows.
Exact ties prefer the earlier window. Each selected window contributes its unseen
lines in source order until the 240-source-line budget is exhausted. Omission
markers are additional display lines; the 12,000-character cap still applies.
This is a methodological amendment to overall.md section 11, not a demonstrated
accuracy improvement. It does not guarantee retention of complete methods,
setup, assertions, or external helpers. Both semantic rankers must use version 2.

Artifacts record generation settings, normalized source SHA-256, and patch-query
SHA-256. Completion checks verify individual JSON/text contents, equality of
those two forms, source freshness, and settings. Old artifacts require the
representation-only refresh described in [phase audit improvements](phase-audit-improvements.md).
