# Active Defects4J bug IDs (Phase 2)

How Phase 2 obtains the active bug universe before sampling. Implemented in `src/select_bugs.py`.

## Metadata source

Active IDs come from the pinned Defects4J installation inside the Phase 1 container:

```bash
defects4j bids -p <project>
```

| Flag | Meaning |
| --- | --- |
| *(none)* | **Active** bugs only (used here) |
| `-D` | Deprecated bugs only (excluded) |
| `-A` | Active and deprecated (not used) |

Do **not** derive the active set from `overall.md` totals or from consecutive ID ranges. Always read the installed metadata.

Projects, in fixed order:

```text
Cli
Lang
Math
Jsoup
JacksonDatabind
```

## Validation rules

For each project:

1. Strip transport whitespace; reject empty or malformed IDs (must match `^[1-9][0-9]*$` as emitted by `bids`).
2. Fail on duplicate IDs within a project.
3. Require at least 30 active IDs.
4. Keep project identity with every ID (`Lang-1` vs `Math-1`) in snapshots via `qualified_ids`.

After all five projects load, compare active counts to the assumptions in `overall.md`:

| Project | Assumed active count |
| --- | --- |
| Cli | 39 |
| Lang | 61 |
| Math | 106 |
| Jsoup | 93 |
| JacksonDatabind | 110 |

A mismatch fails clearly before sampling. Do not switch releases or projects silently.

## Command

```bash
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" \
  -w /workspace \
  jev-ci:phase1 \
  python src/select_bugs.py list-active
```

JSON catalog (counts, ordered IDs, per-project SHA-256, Defects4J commit):

```bash
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" \
  -w /workspace \
  jev-ci:phase1 \
  python src/select_bugs.py list-active --json
```

The reader does not check out bugs, inspect triggers, or read test outcomes.
