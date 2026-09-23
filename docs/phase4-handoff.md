# Phase 4 handoff (from Phase 3)

Phase 3 extraction is complete for the **25 development** bugs. Phase 4 may
rank test classes from saved artifacts without re-parsing Defects4J exports or
changing Phase 3 representations.

## Do not

- Resample or rewrite `data/manifest.json`
- Process evaluation bugs until the design freeze
- Re-tokenize with a second tokenizer or re-score windows with a different BM25
- Feed `labels.json`, `raw/tests.trigger`, or checkout trees into model state

## Load per development example

For qualified id `Cli-30` (slug `Cli_30`):

| Need | Path |
| --- | --- |
| Example status / hashes | `data/bugs/Cli_30/example.json` (`status=complete`) |
| Patch query (recommended) | `data/patches/Cli_30/representation.txt` |
| Untruncated diff (audit) | `data/patches/Cli_30/regression_patch.diff` |
| Patch meta | `data/patches/Cli_30/patch_meta.json` |
| Test class IDs | `data/tests/Cli_30/inventory.json` → `test_classes` |
| Full-source paths | `inventory.json` → `source_map[].source_file` (repo-relative, fixed checkout) |
| Compact test reps | `data/tests/Cli_30/representations/*.txt` (+ `.json` metadata) |
| Representation index | `data/tests/Cli_30/representations_index.json` |
| Private positives | `data/tests/Cli_30/labels.json` (diagnostics only) |

Validate before ranking:

```bash
python -c 'from src.example_contract import load_example; load_example("Cli-30")'
```

## Shared lexical primitives (reuse, do not fork)

| Module | Role |
| --- | --- |
| `src/tokenize.py` | `tokenize()` / `TOKENIZER_VERSION=jev-code-tokenizer-v1` / `tokenizer_config_sha256()` ([tokenizer.md](tokenizer.md)) |
| `src/bm25.py` | `bm25_scores()` / `k1=1.5` / `b=0.75` / `BM25_VERSION=jev-bm25-v1` ([bm25-scoring.md](bm25-scoring.md)) |
| `src/ranking.py` | Lexical query/documents + `tokenize_query` / `tokenize_document` + `rank_suite` |

Phase 3 used these for long-test window selection. Phase 4 suite BM25 should
call the same functions; extend document/query builders only.

## BM25 lexical inputs (P4-01 locked)

See [`bm25-lexical-contract.md`](bm25-lexical-contract.md) and `src/ranking.py`.

- **Document (per class):** FQCN + **entire** fixed-revision source from
  `source_map` (not the compact 12k representation). If `source_missing`, FQCN
  alone. Missing claimed source → hard fail (no compact fallback).
- **Query (locked):** model-visible patch `representation.txt`
  (`query_diff_source=model_visible_representation`). Carry into Phase 6
  preregistration.
- **Hashes:** `build_lexical_inputs(...).input_hashes` for stale-ranking checks.
- **Shortlists:** `data/candidates/<slug>.json` (`K=min(200,N)`); full rankings in
  `results/rankings/<slug>.json` ([candidates.md](candidates.md)).
- **Batch command:** `python scripts/run_candidates.py --split development`

## Integrity gate already passed

See [`verification-phase4.md`](verification-phase4.md) and
`results/audit-phase4.json`. Re-run anytime:

```bash
python scripts/audit_phase4.py
```

Phase 5 shortlist contract: [`phase5-handoff.md`](phase5-handoff.md).

## Development ID list

Read only `data/manifest.json` → `development_bug_ids` (25). Do not walk
`evaluation_bug_ids` for ranking until freeze.
