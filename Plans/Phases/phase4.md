# Phase 4 tickets — BM25 retrieval and candidate shortlists

**Phase goal:** Rank every available test class for each development bug with one transparent lexical baseline, then save the exact top-200 (or smaller) prefix that both semantic rerankers will receive. Phase 4 establishes candidate generation; it does not score Jev/GPT or inspect evaluation-bug outcomes.

**Source of truth:** [../overall.md](../overall.md), sections 11–14 and the ranking-integrity rules in section 37; [../phases.md](../phases.md), Phase 4. Phase 3 supplies the committed manifest, 25 validated development examples, fixed-base test inventory/source mapping, regression-patch representation, and a shared tokenizer/BM25 primitive used for long-test-source windows. Reuse those lexical primitives rather than introducing a second implementation.

Tickets are ordered by dependency. A completed ticket should leave an artifact or behavior another agent can check independently. Candidate IDs and their order are part of the data contract for Phase 5.

## P4-01 — Lock the lexical input contract ✅ COMPLETE

**Depends on:** Phase 3.

**Status:** Complete. [`src/ranking.py`](../../src/ranking.py); contract in [`docs/bm25-lexical-contract.md`](../../docs/bm25-lexical-contract.md). Query diff source locked to model-visible `representation.txt`.

**Work**

- Define one BM25 document per class in `tests.all`: the class FQCN plus its **entire available fixed-revision Java source**. Do not use the compact 12,000-character semantic representation or just its selected windows for this corpus. If Phase 3 marked source missing, retain the class with its FQCN as its complete document.
- Define the query as modified production file paths, modified class names, and the saved regression patch text. State precisely whether the diff portion comes from the capped model-visible patch representation or the untruncated saved diff; use one choice for every bug and carry it into Phase 6 preregistration. The recommended choice is the model-visible diff so lexical and semantic rankers receive the same change context.
- Read the full source through Phase 3's persisted source mapping or stored raw source, verify it matches the fixed checkout/provenance, and fail clearly if a supposedly available source file is missing. Do not silently fall back to compact source in that case.
- Keep trigger labels and bug outcome metadata out of documents, queries, and ranking features. Use labels only later for development diagnostics.
- Define a deterministic representation of input IDs, source hashes, and query hash so stale rankings can be detected when Phase 3 artifacts change.

**Deliverable:** A documented query/document builder, likely in `src/bm25.py` or `src/ranking.py`, with a small example of its inputs.

**Acceptance:** For every development bug, the builder emits exactly one document for each `tests.all` class; long tests contribute full source, missing-source tests contribute their FQCN, and no positive-class marker enters the query or corpus.

## P4-02 — Reuse and verify the single code tokenizer ✅ COMPLETE

**Depends on:** P4-01 and Phase 3's lexical helper.

**Status:** Complete. Shared [`src/tokenize.py`](../../src/tokenize.py) with config hash; Phase 4 wrappers in [`src/ranking.py`](../../src/ranking.py); behavior docs in [`docs/tokenizer.md`](../../docs/tokenizer.md); checks in [`tests/test_phase4_tokenizer.py`](../../tests/test_phase4_tokenizer.py).

**Work**

- Centralize the tokenizer so both Phase 3 source-window selection and Phase 4 BM25 use the same function. It must split non-alphanumeric separators, camelCase, PascalCase/acronym, and snake_case boundaries; lowercase; and discard empty and one-character tokens.
- Preserve Java keywords and English stopwords; do not stem. Define boundary behavior for digits, repeated underscores, acronyms, Unicode/non-ASCII characters, and empty input so indexing and querying cannot diverge.
- Verify the outline's `parseHTTPResponse_v2` example yields `parse`, `http`, `response`, `v2` in order. Test a few Java package/class and method names representative of the data.
- Version or hash tokenizer configuration in ranking provenance. A tokenizer change before Phase 6 should invalidate saved BM25 rankings and candidate lists; after the freeze it is a methodological change requiring disclosure.

**Deliverables:** Shared tokenizer module, focused behavior checks, and recorded tokenizer version/configuration.

**Acceptance:** Phase 3 window selection and Phase 4 document/query processing call the same tokenizer. Its behavior is deterministic and the representative identifier checks pass.

## P4-03 — Implement full-corpus BM25 scoring ✅ COMPLETE

**Depends on:** P4-01 and P4-02.

**Status:** Complete. Scorer in [`src/bm25.py`](../../src/bm25.py); `rank_suite` in [`src/ranking.py`](../../src/ranking.py); formula in [`docs/bm25-scoring.md`](../../docs/bm25-scoring.md); checks in [`tests/test_phase4_bm25.py`](../../tests/test_phase4_bm25.py).

**Work**

- Reuse/extend the Phase 3 BM25 primitive to score each test-class document against the query with `k1=1.5` and `b=0.75`. Use the standard nonnegative IDF form and document the exact term-frequency, document-frequency, length-normalization, and repeated-query-term behavior.
- Build a separate corpus per bug from **all** available test classes. Calculate corpus size and average document length from the same tokenized documents being ranked, including FQCN-only fallback documents.
- Give every class a finite numeric score, including zero when there is no lexical overlap. Define a deterministic final order: descending BM25 score, then ascending FQCN for exact ties. Do not use trigger labels to break ties.
- Keep implementation inspectable and efficient enough for the development set; avoid adding semantic signals or extra retrieval heuristics to this baseline.

**Deliverables:** `src/bm25.py` scorer and a full-suite ranking function, with a documented scoring formula.

**Acceptance:** A hand-computed toy corpus matches the scorer within numeric tolerance; every development ranking contains exactly the `tests.all` set once, has finite scores, and is sorted by the documented rule. A query with no matching terms still yields a complete deterministic ranking.

## P4-04 — Save the full ranking and exact semantic prefix ✅ COMPLETE

**Depends on:** P4-03.

**Status:** Complete. [`src/candidates.py`](../../src/candidates.py); layout in [`docs/candidates.md`](../../docs/candidates.md); 25 development shortlists under `data/candidates/` and full rankings under `results/rankings/`; checks in [`tests/test_phase4_candidates.py`](../../tests/test_phase4_candidates.py).

**Work**

- For each bug compute `K=min(200, N)` where `N` is the number of test classes. Save the first `K` class IDs, in BM25 order, to `data/candidates/<project>_<bug>.json`.
- Save the complete BM25 ranking with scores and 1-based ranks in a separate development ranking artifact. Use stable filenames, deterministic serialization, and atomic writes. Record manifest ID, split, Defects4J commit, input hashes, tokenizer/BM25 settings, `N`, and `K`.
- Make the shortlist an exact prefix of the saved full ranking, not a separately scored or sorted list. Include a content hash of the ordered shortlist for Phase 5 to check before Jev and GPT calls.
- Support safe reruns. Reuse identical artifacts when inputs/configuration match; report and intentionally regenerate stale development artifacts when they do not. Do not overwrite a shortlist while a semantic scoring run is using it.
- Keep the `K=200` rule fixed even if development candidate recall is disappointing. Any proposed change belongs in a separately documented future experiment, not an unnoticed adjustment.

**Deliverables:** Candidate-list files under `data/candidates`, complete development BM25 ranking files, and a stable reader for Phase 5.

**Acceptance:** Each candidate file contains exactly `min(200, N)` unique IDs equal to the first `K` full-ranking IDs. A second run with identical inputs leaves the files byte-for-byte unchanged; a changed input/configuration is detected before reuse.

## P4-05 — Add the development candidate-generation command ✅ COMPLETE

**Depends on:** P4-01 through P4-04.

**Status:** Complete. [`scripts/run_candidates.py`](../../scripts/run_candidates.py); summary [`results/run_candidates-development.json`](../../results/run_candidates-development.json); gating tests in [`tests/test_phase4_run_candidates.py`](../../tests/test_phase4_run_candidates.py).

**Work**

- Provide an entry point, for example `python scripts/run_candidates.py --split development`, that verifies the Phase 2 manifest and Phase 3 example integrity, then builds BM25 rankings and shortlists for all 25 development IDs in manifest order.
- Restrict the default/pre-freeze command to development bugs. Do not generate rankings or candidate-recall diagnostics for the 125 evaluation bugs until Phase 6 has frozen the design.
- Report completed/failed bugs, `N`, `K`, and missing-source counts without exposing trigger IDs in candidate files. On failure, preserve already complete artifacts and return a nonzero status; do not emit a seemingly complete partial ranking.
- Make the command resumable from validated artifacts and explicit about any changed input hashes.

**Deliverables:** `scripts/run_candidates.py` and the development rankings/shortlists it produces.

**Acceptance:** One documented command produces a full ranking and shortlist for every development bug; rerunning it is safe. No evaluation ranking or shortlist is produced by the pre-freeze invocation.

## P4-06 — Audit retrieval quality and hand off a fixed shortlist ✅ COMPLETE

**Depends on:** P4-05.

**Status:** Complete. [`src/audit_phase4.py`](../../src/audit_phase4.py) / [`scripts/audit_phase4.py`](../../scripts/audit_phase4.py); report [`docs/verification-phase4.md`](../../docs/verification-phase4.md) + [`results/audit-phase4.json`](../../results/audit-phase4.json); Phase 5 contract [`docs/phase5-handoff.md`](../../docs/phase5-handoff.md). Development candidate recall@K = 25/25 (diagnostic only).

**Work**

- Validate every development ranking as a permutation of the fixed-base test inventory and every shortlist as its exact prefix. Check score/rank consistency, finite scores, ID uniqueness, `N`/`K` counts, and matching provenance hashes.
- Calculate **development-only** candidate trigger recall: the fraction of the 25 development bugs with at least one known triggering class in their BM25 top `K`. Keep this diagnostic separate from the later 125-bug evaluation metric and headline table.
- Inspect a few high/low development cases for extraction or ranking bugs. Correct implementation errors before Phase 6, and record any methodological choice that needs to be frozen. Do not tune `K`, add query expansions, or change the corpus based on the diagnostic.
- Hand Phase 5 a single candidate-file reader and a content-hash equality check. Jev and GPT must consume the same ordered IDs; each will rerank those IDs and append the untouched BM25 tail.

**Deliverables:** Ranking/candidate integrity checks, a development-only retrieval audit, and the Phase 5 shortlist contract.

**Acceptance:** All 25 development bugs have valid complete BM25 rankings and stable top-`K` lists. Phase 5 can load one list per bug for both semantic rerankers without re-running BM25 or making a separate candidate-selection decision.

## Phase completion gate ✅

Phase 4 is implemented when the shared tokenizer and standard BM25 scorer produce deterministic full-suite rankings for all 25 development bugs, each top-`min(200,N)` list is saved as an exact ranking prefix, and the provenance/integrity checks pass. The algorithm, query/document inputs, tie-breaks, and shortlist format are ready to be frozen in Phase 6. Evaluation rankings and candidate lists remain ungenerated until after that freeze.

**Status:** Gate met. `run_candidates` + `audit_phase4` pass for all 25 development IDs; evaluation set untouched. Hand-off for Phase 5: [`docs/phase5-handoff.md`](../../docs/phase5-handoff.md).
