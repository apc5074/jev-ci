# Phase 3 tickets — Build and validate development examples

**Phase goal:** For each of the 25 development bugs in the locked manifest, create a reproducible example containing the fixed-base → buggy-proposed production change, every available test class from the fixed base, model-ready test representations, and the known triggering classes kept separately as evaluation labels. The extraction must be reliable enough to reuse unchanged on evaluation bugs after the preregistration freeze.

**Source of truth:** [../overall.md](../overall.md), sections 8–12 and 37; [../phases.md](../phases.md), Phase 3. Phase 1 supplies the container and Defects4J installation; Phase 2 supplies `data/manifest.json` and its verifier. This phase may inspect **development bugs only**. It does not generate evaluation examples, rank full suites, call model APIs, or tune prompts.

Tickets are ordered by dependency. Each should leave a reviewable artifact and a clear pass/fail check. Keep raw Defects4J metadata and ground truth out of the strings sent to models.

## P3-01 — Define the example data contract and safe paths ✅ COMPLETE

**Depends on:** Phases 1–2.

**Status:** Complete. Contract in [`docs/example-contract.md`](../../docs/example-contract.md); helpers in [`src/example_contract.py`](../../src/example_contract.py).

**Work**

- Define a stable identifier and directory layout for one example, such as `<project>_<bug_id>` under `data/bugs`, `data/patches`, and `data/tests`. Read IDs and split membership from the committed manifest; never resample or infer a new bug list.
- Define separate structures for: checkout provenance; raw Defects4J exports; the regression patch and its representation; all test-class IDs; known triggering methods/classes; per-class source lookup and compact representation. Make the boundary between model-visible fields and private labels explicit.
- Record which revision each artifact comes from: fixed `Bf` is the base for test inventory and source; buggy `Bb` supplies the proposed production change. Store the manifest identity and Defects4J commit with each example.
- Decide deterministic JSON/text serialization, path conventions relative to a checkout, and atomic write/resume behavior. Later phases must be able to load examples without repeating checkouts or parsing ad hoc text.
- State how an extraction error is recorded and retried. A partial example must never be mistaken for a complete one.

**Deliverables:** An example schema documented near `src/` or `data/`, plus shared read/write helpers if needed.

**Acceptance:** Another agent can tell exactly which files are model inputs, which are private ground truth, and how to locate each artifact for a manifest ID. A loader rejects incomplete or mismatched examples.

## P3-02 — Implement isolated fixed and buggy checkouts ✅ COMPLETE

**Depends on:** P3-01.

**Status:** Complete. [`src/checkout.py`](../../src/checkout.py) writes verified `Bf`/`Bb` trees and `checkout_provenance.json` under `data/bugs/<slug>/`.

**Work**

- Implement checkout commands equivalent to `defects4j checkout -p P -v Bf -w <fixed_dir>` and `-v Bb -w <buggy_dir>` for a manifest-listed development bug.
- Use separate, deterministic work directories so one revision cannot overwrite the other. Verify each checkout exists and that Defects4J reports the requested project/bug revision before extraction.
- Handle stale, partial, or previously completed checkouts safely. Reuse only checkouts whose provenance matches the requested example and pinned Defects4J installation; otherwise fail or rebuild in a controlled way.
- Capture command, exit status, and useful stderr for failures. Keep host-specific absolute paths out of model representations.

**Deliverables:** `src/checkout.py` and checkout provenance records under the example data directory.

**Acceptance:** A development bug yields separate verified `Bf` and `Bb` trees, and rerunning checkout does not silently exchange or mix them. A failed checkout leaves an explicit incomplete state.

## P3-03 — Extract the production change in the correct direction ✅ COMPLETE

**Depends on:** P3-02.

**Status:** Complete. [`src/extract_patch.py`](../../src/extract_patch.py); truncation rule in [`docs/patch-truncation.md`](../../docs/patch-truncation.md); artifacts under `data/patches/<slug>/`.

**Work**

- Export `classes.modified` and `dir.src.classes` from the fixed checkout; use the buggy checkout's source-directory metadata where needed. Resolve every modified production class to its source path on each side, accounting for package paths and changed/missing files without guessing silently.
- Generate unified diffs with `difflib.unified_diff(fixed_lines, buggy_lines, n=3)`. Use repository-relative file names in diff headers, not checkout directory names such as `fixed/` or `buggy/`.
- Sort modified paths/classes deterministically and concatenate the diffs into the specified model representation: `MODIFIED FILES`, `MODIFIED CLASSES`, and `PROPOSED CODE CHANGE`.
- Store the untruncated diff separately from the model-visible representation, with `patch_truncated`, `original_patch_chars`, and `representation_chars`. Do not use an LLM summary.
- Resolve the outline's truncation arithmetic before coding: 6,000 prefix characters + the truncation marker + 6,000 suffix characters exceeds the stated 12,000-character cap. Record a deterministic rule that reserves space for the marker while retaining approximately equal beginning/end context, and carry that rule into Phase 6 preregistration. Use one documented character-counting convention consistently.

**Deliverables:** `src/extract_patch.py`, regression-patch files and metadata under `data/patches`, and a short note on the truncation rule.

**Acceptance:** The diff shows fixed-source lines removed and buggy-source lines added; every modified production class is accounted for or produces a documented extraction error. The model-visible representation is at most 12,000 characters and contains no checkout/revision labels inserted by the pipeline.

## P3-04 — Extract the full test inventory and known positives ✅ COMPLETE

**Depends on:** P3-02 and P3-01.

**Status:** Complete. [`src/extract_tests.py`](../../src/extract_tests.py); inventory/labels under `data/tests/<slug>/`.

**Work**

- From the **fixed** checkout, export `tests.all`, `tests.trigger`, and `dir.src.tests`. Preserve the raw outputs for audit and parse `tests.all` as class IDs.
- Parse each trigger method by splitting on `::` and taking the class name. Deduplicate into `positive_classes` while retaining the original trigger methods in a private label artifact.
- Validate that the test-class inventory has unique, nonempty IDs and that every triggering class belongs to it, unless explicit Defects4J metadata explains an exception. Do not silently add a trigger to `tests.all` or drop an example.
- Keep non-triggering test classes **unlabeled**. Do not create negative labels or accuracy/precision data from this export.
- Record counts and any metadata anomaly per example for later audits.

**Deliverables:** `src/extract_tests.py`, raw exports and normalized test inventory/positive-class files under `data/tests`.

**Acceptance:** Every development example has a complete unique test-class list and at least one known triggering class, with trigger consistency verified or an explicit source-backed exception. Model-input files contain neither triggering methods nor positive-class flags.

## P3-05 — Resolve fixed-revision Java test source ✅ COMPLETE

**Depends on:** P3-04.

**Status:** Complete. Source resolution in [`src/extract_tests.py`](../../src/extract_tests.py); per-class `source_map` in `inventory.json`.

**Work**

- Resolve each FQCN from `tests.all` against `dir.src.tests` in the fixed checkout. Map nested classes such as `FooTest$Nested` to the outer `FooTest.java` source file.
- Try the direct package-relative path first. If it fails, recursively search for the corresponding simple-class Java filename, using a deterministic ordering and package/path evidence to resolve matches. If multiple candidates remain ambiguous, record that ambiguity instead of arbitrarily choosing a file.
- When source cannot be found, retain the test class with `source_missing=true` and a representation based on its FQCN alone. Never exclude the test or bug because of missing source.
- Store source paths relative to the fixed checkout and read source with a documented encoding/error policy. Record missing or ambiguous-source counts.

**Deliverables:** Source-resolution logic in `src/extract_tests.py` or a focused helper, with a per-class source map.

**Acceptance:** Direct, nested, fallback, missing, and ambiguous lookup cases behave deterministically. Every ID in `tests.all` remains in the candidate inventory, whether or not source exists.

## P3-06 — Build compact, model-ready test representations ✅ COMPLETE

**Depends on:** P3-03 and P3-05.

**Status:** Complete. [`src/representations.py`](../../src/representations.py), [`src/tokenize.py`](../../src/tokenize.py), [`src/bm25.py`](../../src/bm25.py); notes in [`docs/test-representations.md`](../../docs/test-representations.md).

**Work**

- For source files of at most 240 lines, use the entire file. For longer files, create 80-line windows with stride 60, tokenize the proposed patch, BM25-score windows, select the top three with a deterministic tie-break, restore source order, and remove duplicate overlap lines.
- Implement or factor out the **single tokenizer** specified in section 12 of `overall.md` and the minimal BM25 scoring primitive needed for window selection. Phase 4 must reuse these same primitives for suite retrieval; it should extend them, not implement a second tokenizer or scoring formula.
- Build the exact `TEST CLASS`, `SOURCE FILE`, and `TEST SOURCE` representation. Use only fixed-base source and relative paths. Apply the 12,000-character hard cap after composing the representation and record whether source/representation was truncated, original length, and final length.
- For missing source, include the FQCN and a clear empty/omitted source convention without inventing test code. Use the same representation contract for both Jev and GPT in later phases.
- Define window behavior at file endings, duplicate/overlapping lines, equal scores, and files shorter than one full window so reruns produce identical text.

**Deliverables:** `src/representations.py` and shared lexical helpers, plus one saved model-ready representation and compaction metadata per test class.

**Acceptance:** Every test ID has exactly one representation. Long-source output follows the specified 80/60/top-three process, has no duplicate overlap lines, preserves original source order, and stays within the character cap. Rerunning it on the same files produces identical bytes.

## P3-07 — Orchestrate extraction for all development bugs ✅ COMPLETE

**Depends on:** P3-01 through P3-06.

**Status:** Complete. [`scripts/prepare_dataset.py`](../../scripts/prepare_dataset.py); 25 development examples under `data/`; summary in [`results/prepare_dataset-development.json`](../../results/prepare_dataset-development.json).

**Work**

- Provide a Phase 3 entry point, for example `scripts/prepare_dataset.py --split development`, that reads the manifest and runs checkout, patch, metadata, source mapping, and representation stages for all 25 development IDs.
- Make the split restriction explicit: before the Phase 6 freeze, this command must reject or require a later-phase mode for evaluation IDs. It must not accidentally walk the whole 150-bug manifest.
- Write artifacts atomically and resume completed examples only after validating their manifest/Defects4J provenance and input hashes. Retry failed examples without leaving old partial data presented as complete.
- Produce a concise run summary: completed/failed bugs, number of tests per bug, triggering-class counts, missing-source counts, and patch/test truncation counts. Keep bug labels and trigger IDs out of model-visible files.

**Deliverables:** Dataset-preparation command and 25 persisted development examples under the agreed `data/` layout.

**Acceptance:** A fresh run completes all 25 development bugs; a second run is safe and leaves completed example content unchanged. Failures are visible by bug ID and do not yield false success.

## P3-08 — Prove extraction integrity and hand off to retrieval ✅ COMPLETE

**Depends on:** P3-07.

**Status:** Complete. Audit in [`src/audit_phase3.py`](../../src/audit_phase3.py) / [`scripts/audit_phase3.py`](../../scripts/audit_phase3.py); report [`docs/verification-phase3.md`](../../docs/verification-phase3.md) + [`results/audit-phase3.json`](../../results/audit-phase3.json); Phase 4 contract [`docs/phase4-handoff.md`](../../docs/phase4-handoff.md).

**Work**

- Add focused checks for patch direction, source-file mapping, nested classes, trigger-method parsing, deduplication, window order/overlap removal, caps, and missing-source fallback. Use small fixtures for edge cases and at least one real development example for the end-to-end direction check.
- Audit all 25 persisted examples: base=`Bf`, proposed=`Bb`; all trigger classes accounted for; every test class has one model-ready representation; no duplicate IDs; all saved records match the locked manifest and Defects4J commit.
- Inspect **serialized model states**, not just source code, for leaked metadata fields: bug ID, issue title, trigger list/methods, expected result, and revision-status labels. A literal word such as “fixed” inside authentic Java source is not by itself leakage; provenance labels inserted by the pipeline are.
- Document every genuine Defects4J metadata exception with supporting source evidence and its handling. Resolve extraction defects before Phase 4; do not drop hard examples to make the pipeline pass.
- Provide Phase 4 with the patch query representation, test IDs, full-source paths, compact representations, and reusable tokenizer/BM25 primitive.

**Deliverables:** Extraction/integrity tests, a 25-example audit report, and a documented Phase 4 data contract.

**Acceptance:** All checks pass and all 25 development examples are complete. Phase 4 can rank their test classes from saved artifacts without reinterpreting raw Defects4J output or changing Phase 3 representations.

## Phase completion gate ✅

Phase 3 is implemented when the 25 development bugs each have a verified fixed → buggy production patch, fixed-base test inventory, known triggering classes stored separately, and one deterministic compact representation per test class. The extraction command is resumable, its integrity checks pass, and no evaluation bug has been processed. The same frozen extraction logic will be used for evaluation after Phase 6.

**Status:** Gate met. Prepare + audit pass for all 25 development IDs; evaluation set untouched. Hand-off for Phase 4: [`docs/phase4-handoff.md`](../../docs/phase4-handoff.md).
