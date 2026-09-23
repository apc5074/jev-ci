# Phase 3 handoff (from Phase 2)

Phase 2 is complete. Phase 3 may begin from this locked split.

## Consume

| Item | Value |
| --- | --- |
| Manifest path | `data/manifest.json` |
| ID format | Combined lists use `Project-<id>` (e.g. `Cli-30`); per-project sample fields also keep bare ids |
| Project order | `Cli`, `Lang`, `Math`, `Jsoup`, `JacksonDatabind` |
| Seed | `20260922` |
| Defects4J | 3.0.1 @ commit recorded in the manifest (`defects4j_commit`) |
| Development set | `development_bug_ids` (25) — **may be inspected / used to debug** |
| Evaluation set | `evaluation_bug_ids` (125) — **reserved until the design is frozen** |

## Container

```bash
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" \
  -w /workspace \
  jev-ci:phase1 \
  python …
```

Verify the split anytime (read-only):

```bash
python src/select_bugs.py verify
```

## Rules for Phase 3

- Do **not** resample or rewrite `data/manifest.json`.
- Do **not** use evaluation-bug outcomes to tune prompts, representations, or methods.
- Development bugs may be checked out and used to validate extraction pipelines.
- Selection provenance (active-set hashes, seed, project order) is already in the manifest; see [manifest.md](manifest.md) and [verification-phase2.md](verification-phase2.md).
