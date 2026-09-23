# Dataset manifest schema (Phase 2)

Canonical path: `data/manifest.json`.

Built by `build_manifest()` / `write_manifest_atomic()` in `src/select_bugs.py`. Preview without locking:

```bash
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" \
  -w /workspace \
  jev-ci:phase1 \
  python src/select_bugs.py build-manifest
```

Write atomically to a path (P2-04 will own one-time create at `data/manifest.json`):

```bash
python src/select_bugs.py build-manifest --output /tmp/manifest.json
```

Requires a valid Phase 1 `results/environment.json` (run `python scripts/check_environment.py` first).

Related: [testing.md](testing.md) for the Phase 2 unittest command.

## Create and verify (one-time lock)

```bash
# Create only if missing; if present, verify and leave bytes unchanged
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" \
  -w /workspace \
  jev-ci:phase1 \
  python src/select_bugs.py create

# Read-only verification (does not rewrite created_at or any bytes)
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" \
  -w /workspace \
  jev-ci:phase1 \
  python src/select_bugs.py verify
```

There is **no** force-resample flag. Fix corruption or Defects4J drift deliberately; never silently replace a locked split.

### Exit codes

| Code | Meaning |
| --- | ---: |
| `0` | Success (`create` wrote or verified; `verify` passed) |
| `1` | Corruption / schema / selection integrity failure |
| `2` | Upstream drift: installed Defects4J active set or commit differs; file preserved |

`create` when the file already exists runs the same checks as `verify` and prints that the manifest was not rewritten.

## ID conventions

| Field group | Format | Example |
| --- | --- | --- |
| `projects.*.active_bug_ids` | bare Defects4J id string | `"7"` |
| `projects.*.selected_ids` / `development_ids` / `evaluation_ids` | bare, **sample order** | `"30"` |
| `projects.*.*_qualified_ids` | `Project-<id>` | `"Cli-30"` |
| `development_bug_ids` / `evaluation_bug_ids` | `Project-<id>`, project order then sample order | `"Cli-30"` |

## Top-level fields

| Field | Type | Meaning |
| --- | --- | --- |
| `defects4j_version` | string | e.g. `3.0.1` |
| `defects4j_commit` | string | Full SHA of `/opt/defects4j` (separate from repo commit) |
| `selection_seed` | int | `20260922` |
| `project_order` | string[] | `Cli`, `Lang`, `Math`, `Jsoup`, `JacksonDatabind` |
| `projects` | object | Per-project active provenance + ordered sample/split |
| `development_bug_ids` | string[] | 25 qualified IDs |
| `evaluation_bug_ids` | string[] | 125 qualified IDs |
| `created_at` | string | UTC ISO-8601 with offset, no microseconds |
| `git_commit` | string or `null` | Experiment repo HEAD **when the manifest was generated** (precedes the commit that adds the file); `null` if unavailable |
| `environment` | object | Container Python/Java/OS/arch/timezone from `results/environment.json` |
| `id_format` | object | Human-readable reminder of bare vs qualified fields |
| `metadata_source` | string | How active IDs were obtained |

### Per-project (`projects.<name>`)

| Field | Meaning |
| --- | --- |
| `active_bug_ids` | Full active set as read from Defects4J (bids order) |
| `active_count` | Length of that list |
| `active_content_sha256` | SHA-256 of active ids joined by newlines |
| `active_source_command` | Exact `defects4j bids -p …` invocation |
| `selected_ids` | 30 bare ids in `random.sample` order |
| `development_ids` | First 5 of `selected_ids` |
| `evaluation_ids` | Remaining 25 of `selected_ids` |
| `*_qualified_ids` | Same lists with `Project-` prefix |

A reader can reconstruct every split from this file alone without calling Defects4J.

## Serialization

- UTF-8 JSON, 2-space indent, trailing newline
- Object key order is insertion order (stable); do not rely on `sort_keys`
- Atomic write: write `manifest.json.tmp` then replace `manifest.json`

## Exclusions

The manifest must not contain secrets, full process environments, checkout paths, trigger lists, or model outcomes.
