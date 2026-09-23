# Phase 2 tickets — Select and lock the dataset

**Phase goal:** Produce one traceable, deterministic 150-bug Defects4J manifest: 30 bugs from each of five projects, split into 25 development bugs and 125 evaluation bugs. Later phases read this manifest as an immutable input.

**Source of truth:** [../overall.md](../overall.md), sections 4–5 and the development/evaluation rules in sections 35–36; [../phases.md](../phases.md), Phase 2. Phase 1 supplies a validated Defects4J 3.0.1 container, its pinned Git commit, the container command, and an environment record. This phase selects IDs only. It does not check out bugs, inspect triggers, run models, or look at evaluation outcomes.

Tickets are ordered by dependency. Each ticket has a reviewable artifact and a pass/fail check. Keep the selection logic small and explicit so another agent can independently reproduce the split.

## P2-01 — Read and validate active Defects4J bug IDs ✅ COMPLETE

**Depends on:** Phase 1.

**Status:** Complete. Reader in [`src/select_bugs.py`](../../src/select_bugs.py); metadata source documented in [`docs/active-bugs.md`](../../docs/active-bugs.md).

**Work**

- Implement a reader for active bug IDs exposed by the pinned Defects4J installation. Use its documented command or metadata interface; record the exact command/path and how inactive or deprecated IDs are excluded.
- Read **only** `Cli`, `Lang`, `Math`, `Jsoup`, and `JacksonDatabind`, in that order. Do not infer the active set from the outline's stated total or from numbered ID ranges.
- Normalize IDs to strings exactly as Defects4J represents them, strip transport whitespace, reject empty/malformed IDs, and fail on duplicates. Require at least 30 active IDs for each project.
- Preserve an auditable snapshot of the active ID lists or their content hashes and counts, along with the Defects4J commit they came from. Keep project identity attached to every ID so `Lang-1` and `Math-1` cannot collide.
- Report a mismatch between installed metadata and assumptions in `overall.md` before sampling; do not silently switch releases or projects.

**Deliverables:** An active-ID reader in `src/select_bugs.py` or a small supporting module, with documented metadata source and validation errors.

**Acceptance:** In the Phase 1 container, the reader returns a unique, nonempty active-ID list with at least 30 entries for each of the five required projects. A malformed/duplicate/too-short input fails clearly. The reader does not access test outcomes or bug checkouts.

## P2-02 — Implement the exact deterministic sample and split ✅ COMPLETE

**Depends on:** P2-01.

**Status:** Complete. `select_bugs()` in [`src/select_bugs.py`](../../src/select_bugs.py); convention in [`docs/selection.md`](../../docs/selection.md).

**Work**

- Initialize `rng = random.Random(20260922)` **once**. Iterate projects in the required order. For each project, execute the equivalent of `rng.sample(sorted(active_bug_ids), 30)` without resetting or reseeding the RNG.
- Treat IDs as strings when applying Python's `sorted`; do not silently substitute numeric sorting or sort the 30 sampled IDs afterward. Their sampled order determines the split.
- Assign selected positions 1–5 within each project to development and positions 6–30 to evaluation. Keep that order in the manifest and expose project-qualified IDs, for example `Cli-7`, when building combined split lists.
- Keep selection as a pure function over the five active-ID lists. It must not depend on filesystem enumeration order, local timezone, hash randomization, or prior generated files.

**Deliverables:** A small selection function and a clearly documented identifier/order convention.

**Acceptance:** The function returns exactly 30 distinct selected bugs per project, five development and 25 evaluation bugs per project, and 150 unique project-qualified IDs overall. Reordering the input metadata does not change the output. An independent implementation of the stated algorithm produces the same ordered lists.

## P2-03 — Define and write the manifest with provenance ✅ COMPLETE

**Depends on:** P2-02 and the Phase 1 environment record.

**Status:** Complete. Schema in [`docs/manifest.md`](../../docs/manifest.md); `build_manifest` / `write_manifest_atomic` in [`src/select_bugs.py`](../../src/select_bugs.py) (`build-manifest` command).

**Work**

- Define a stable JSON schema for `data/manifest.json`. Include the required top-level fields: `defects4j_version`, `selection_seed`, `projects`, `development_bug_ids`, `evaluation_bug_ids`, `created_at`, and `git_commit`.
- In each `projects` entry, store the ordered 30 selected IDs and identify its ordered five development and 25 evaluation IDs. Store enough active-set provenance from P2-01 to audit what was sampled.
- Record the Defects4J Git commit separately from the experiment repository's `git_commit`. The latter is the source revision used to generate the manifest, which necessarily precedes the later commit that adds the manifest. Include Python version, Java version, OS, architecture, and timezone from the validated environment; do not confuse the build host with the container where selection ran.
- Use a documented timestamp format, stable key/list ordering, and explicit string IDs. A later reader should not need to guess whether bare IDs or project-qualified IDs appear in each field.
- Write the file atomically so an interrupted run cannot leave a partial manifest. Do not put secrets, full environment variables, checkout data, trigger lists, or other outcome information in it.

**Deliverables:** Manifest schema notes and the manifest serialization/writer code.

**Acceptance:** A generated manifest is parseable JSON, records all required provenance, and lets a reader reconstruct every per-project and combined split without consulting Defects4J again.

## P2-04 — Make creation one-time and validation read-only ✅ COMPLETE

**Depends on:** P2-03.

**Status:** Complete. `create` / `verify` in [`src/select_bugs.py`](../../src/select_bugs.py); exit behavior in [`docs/manifest.md`](../../docs/manifest.md).

**Work**

- Provide a simple command, for example `python src/select_bugs.py create`, that creates `data/manifest.json` only when it does not already exist. If it exists, validate it and return without rewriting it, or fail with a clear instruction to run verification. Do not add a routine force-resample option.
- Provide a read-only verification command, for example `python src/select_bugs.py verify`, that checks the schema, counts, uniqueness, membership, split order, seed, project order, Defects4J version/commit, and environment provenance. Recompute the expected sample from the recorded active-ID snapshot or current pinned Defects4J metadata and compare ordered lists.
- Distinguish a corrupted manifest from changed upstream metadata. If the current active set differs from the recorded one, report the drift and preserve the existing manifest; never regenerate a different split in place.
- Ensure `verify` leaves the manifest byte-for-byte unchanged, including `created_at`. Make error messages point to the project and field that failed.

**Deliverables:** Create and verify command paths, with documented exit behavior.

**Acceptance:** Repeated create/verify runs do not alter an existing manifest. A changed seed, swapped project order, missing ID, duplicate, wrong split position, or metadata drift is detected. No command silently resamples after a manifest exists.

## P2-05 — Add focused determinism and integrity checks ✅ COMPLETE

**Depends on:** P2-02 through P2-04.

**Status:** Complete. Tests in [`tests/test_phase2_selection.py`](../../tests/test_phase2_selection.py); command in [`docs/testing.md`](../../docs/testing.md).

**Work**

- Use small synthetic active-ID lists to check exact sampling against `random.Random(20260922)`, continuous RNG use across projects, lexicographic input sorting, and first-five split membership. Include shuffled input order to prove the result is stable.
- Check manifest validation on representative invalid cases: fewer than 30 active bugs, duplicate IDs, wrong project membership, mismatched combined lists, and a changed Defects4J commit or active-set snapshot.
- Check the one-time write behavior by creating a manifest in a temporary directory, re-running the command, and comparing bytes and timestamp. Confirm a failed write does not leave a truncated manifest.
- Keep tests confined to selection and manifest integrity; tests requiring actual bug checkout or trigger data belong to Phase 3.

**Deliverables:** Focused tests under `tests/` and a documented test command that runs in the Phase 1 container.

**Acceptance:** The tests pass, and deliberate changes to the sampling order, split positions, or overwrite behavior make the relevant checks fail.

## P2-06 — Generate, review, and lock the real manifest ✅ COMPLETE

**Depends on:** P2-01 through P2-05.

**Status:** Complete. Locked [`data/manifest.json`](../../data/manifest.json); record in [`docs/verification-phase2.md`](../../docs/verification-phase2.md); Phase 3 handoff in [`docs/phase3-handoff.md`](../../docs/phase3-handoff.md).

**Work**

- Run the Phase 1 environment check, create the real manifest from the pinned Defects4J installation, and run the read-only verifier. Capture the exact commands used.
- Review and report the five active-set counts, the 30 selected IDs per project, and the 25/125 split counts. Confirm that no selected ID appears in both splits and no project contributes a different number of bugs.
- Commit `data/manifest.json` with the selection code, tests, and schema notes before Phase 3 starts. Record the commit used to lock the split. The later `experiment-v1-frozen` tag in Phase 6 is a separate preregistration milestone.
- Hand Phase 3 the manifest path, ID format, project order, selection provenance, verifier command, and Phase 1 container invocation. State explicitly that development bugs may be inspected next and evaluation bugs remain reserved until the design is frozen.

**Deliverables:** The populated, committed `data/manifest.json`, passing verification output, and a brief handoff in the setup/experiment notes.

**Acceptance:** The manifest contains exactly 150 selected bugs from the five named projects, with 25 development and 125 evaluation IDs. The verifier passes without modifying it, and another agent can reproduce the ordered selection from the documented inputs and seed.

## Phase completion gate ✅

Phase 2 is implemented when a committed manifest and its provenance exist, selection and validation checks pass in the Phase 1 container, rerunning the commands cannot change the split, and Phase 3 can consume the 25 development IDs without making any new selection decision. The 125 evaluation IDs are named in the manifest but have not been used to inspect outcomes or tune the experiment.
