# Phase 1–4 audit improvements

## Changes

- Completion hashes include every representation JSON and text file, plus the full patch. Validation checks matching text/JSON, class IDs, current settings, patch-query hash, and normalized source hash.
- Phase 3 reconstructs every development patch from both existing checkouts and saved exports, comparing the full diff and capped model input exactly.
- Phase 4 reports development FDR@10% (ceil budget), MRR, mean first-trigger rank, candidate recall, and whole-suite shortlist counts, including per-project and N>200 subsets. Ranks come from the entire ranking, including shortlist misses. Empty subsets report null metrics; partial audit metrics are flagged incomplete.
- BM25 results are cached by source/query hashes and tokenizer/scorer versions. Sources are still read to establish freshness; unchanged inputs skip tokenization and scoring. Cache corruption causes recomputation. The cache is populated on the first candidate-generation run after this change.
- Representation version 2 reserves header context, discounts overlapping windows, and marks omissions. See [the representation contract](test-representations.md). This changes semantic inputs, not full-source BM25 retrieval or K.

## Refresh existing development data

No resampling, Defects4J checkout, export, or candidate regeneration is needed:

```bash
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace jev-ci:phase1 \
  python scripts/refresh_development.py
```

This command regenerates development representations, updates completion hashes,
and writes both audit reports including new retrieval metrics. It refuses to
start while a development semantic lock exists. Evaluation examples are excluded.
A failure returns nonzero; representation writes mark that example incomplete
until finalized. Historical semantic scores/embeddings must only be reused when
their exact input state matches; changed representation inputs require new calls.

This amendment supersedes the original top-three-window rule in overall.md
section 11 and the Phase 3 brief. Record version 2 in the Phase 6 freeze. The
existing verification reports describe the earlier run until refreshed.

## Verification status

No tests or data refresh were run for this change, at the user's request not to
run tests. Code changes were reviewed statically. Improved model accuracy has
not been measured.
