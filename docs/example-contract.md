# Example data contract (Phase 3)

Stable layout and visibility rules for one Defects4J bug example. Implemented in `src/example_contract.py`.

Phase 3 may build examples for **development** IDs from `data/manifest.json` only. Do not resample the manifest. Evaluation IDs stay reserved until freeze.

## Identifier

| Form | Example | Use |
| --- | --- | --- |
| Manifest / qualified | `Cli-30` | Lists in `data/manifest.json` |
| Directory slug | `Cli_30` | Paths under `data/bugs`, `data/patches`, `data/tests` |

Parse either form with `ExampleId.parse(...)`.

## Directory layout

For example `Cli_30`:

```text
data/bugs/Cli_30/
  example.json                 # status + provenance index (required)
  checkout_provenance.json     # Defects4J checkout commands / revisions
  error.json                   # present only on failure
  checkouts/fixed/             # Bf working tree (base)
  checkouts/buggy/             # Bb working tree (proposed change)
  raw/                         # other Defects4J exports as needed

data/patches/Cli_30/
  regression_patch.diff        # full untruncated unified diff (audit)
  representation.txt           # MODEL-VISIBLE patch text (≤ 12,000 chars)
  patch_meta.json              # truncation stats; no trigger labels

data/tests/Cli_30/
  raw/tests.all                # raw Defects4J export
  raw/tests.trigger            # PRIVATE raw trigger methods
  raw/dir.src.tests
  inventory.json               # MODEL-VISIBLE test class inventory
  labels.json                  # PRIVATE positives / trigger methods
  representations/             # per-class MODEL-VISIBLE compact sources
  representations_index.json
```

Relative paths inside diffs and representations must be **repository paths**, never checkout directory names (`fixed/`, `buggy/`) or host absolute paths.

## Revisions

| Role | Defects4J version | Used for |
| --- | --- | --- |
| Base | `Bf` (fixed) | Test inventory, test source, “before” side of the regression diff |
| Proposed change | `Bb` (buggy) | Production sources after the hypothetical PR |

Direction is always **fixed → buggy**. Do not name model fields `bug_patch` or `reverse_fix`.

Each `example.json` stores the locked manifest seed, Defects4J version/commit, and split membership so a loader can reject mismatches.

## Visibility boundary

**Model-visible (safe to feed rankers):**

- `representation.txt` / patch representation fields (`MODIFIED FILES`, `MODIFIED CLASSES`, `PROPOSED CODE CHANGE`)
- Test inventory class IDs and compact test-source representations
- Truncation / `source_missing` metadata that does not reveal labels

**Private (never in model state):**

- `labels.json` (`trigger_methods`, `positive_classes`)
- `raw/tests.trigger`
- Bug IDs, issue titles, “buggy”/“fixed” wording inserted by the pipeline, Defects4J label dumps
- Checkout trees as opaque workspaces (not serialized into model prompts)

## Status and resume

`example.json` field `status`:

| Value | Meaning |
| --- | --- |
| `incomplete` | Extraction in progress or not started; **not** consumable |
| `complete` | All required artifacts present and consistent |
| `error` | Failed stage recorded in `error.json`; **not** consumable |

Required artifacts for `complete` are listed in `complete_requirements` inside `example.json` (checkouts, patch files, test inventory/labels, representation index).

**Atomic writes:** JSON/text helpers write `*.tmp` then replace so an interrupted run cannot leave a truncated final file.

**Errors / retry:** call `mark_example_error(...)` with `stage`, `message`, and `retryable`. Clear or rebuild the incomplete tree before retrying; never flip `status` to `complete` while required files are missing.

## Loader rules

`load_example(id, require_complete=True)`:

1. Resolves the ID against the locked manifest (development only by default).
2. Requires `example.json` with matching `qualified_id`, split, seed, and Defects4J commit.
3. Rejects `status != complete` when `require_complete` is true.
4. Rejects missing required artifacts.
5. Rejects private label fields leaking into `inventory.json`.

Incomplete or mismatched examples raise `ExampleIncompleteError` / `ExampleMismatchError`.

## Checkouts (P3-02)

```bash
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 \
  python src/checkout.py Cli-30
```

Creates isolated `checkouts/fixed` (`Bf`) and `checkouts/buggy` (`Bb`) plus `checkout_provenance.json`. Matching provenance is reused; stale/partial trees are rebuilt. Evaluation IDs are rejected until freeze. Failures call `mark_example_error` and leave the example incomplete.

## Patch extraction (P3-03)

```bash
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 \
  python src/extract_patch.py Cli-30
```

Requires verified checkouts. Writes `data/patches/<slug>/` (`regression_patch.diff`, `representation.txt`, `patch_meta.json`) and raw exports under `data/bugs/<slug>/raw/`. Diff direction is **fixed → buggy** (correct lines removed, regression lines added). Model-visible paths are repository-relative only. Truncation rule: [patch-truncation.md](patch-truncation.md).

## Test inventory (P3-04 / P3-05)

```bash
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 \
  python src/extract_tests.py Cli-30
```

From the **fixed** checkout: exports `tests.all`, `tests.trigger`, and `dir.src.tests`. Writes model-visible `data/tests/<slug>/inventory.json` (class IDs + `source_map`) and private `labels.json` (`trigger_methods`, `positive_classes`). Trigger classes must already appear in `tests.all` or extraction errors; non-triggers stay unlabeled.

**Source map (P3-05):** for each FQCN, try the direct package path under `dir.src.tests`, then a recursive `<SimpleName>.java` search with package-path evidence. Nested classes map to the outer `.java` file. Ambiguous matches are recorded (`resolution=ambiguous`, `source_missing=true`) without picking a file. Missing source keeps the class in the inventory. Encoding probe: UTF-8 strict (`readable` / `line_count` on each entry).

## Test representations (P3-06)

```bash
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 \
  python src/representations.py Cli-30
```

Requires inventory + patch representation. Writes one JSON/txt pair per test class under `data/tests/<slug>/representations/` plus `representations_index.json`. Compaction and truncation: [test-representations.md](test-representations.md). Shared tokenizer/BM25: `src/tokenize.py`, `src/bm25.py`.

## Dataset preparation (P3-07)

```bash
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 \
  python scripts/prepare_dataset.py --split development
```

Runs checkout → patch → tests → representations for all **25 development** IDs. Evaluation requires `--split evaluation --allow-evaluation` (post-freeze). Completed examples with matching content hashes are skipped on resume. Summary: `results/prepare_dataset-development.json` (counts only; no trigger IDs).

## Integrity audit (P3-08)

```bash
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 \
  python scripts/audit_phase3.py
```

Validates all 25 complete examples (direction, triggers, coverage, model-state leakage policy). Report: [verification-phase3.md](verification-phase3.md). Phase 4 inputs: [phase4-handoff.md](phase4-handoff.md).

## Helpers

```bash
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 \
  python -c 'from src.example_contract import development_example_ids; print(len(development_example_ids()))'
```
