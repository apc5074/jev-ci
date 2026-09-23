# Patch representation truncation (Phase 3)

Applies to the full model-visible patch text in
`data/patches/<id>/representation.txt` (headers + unified diff). The untruncated
diff remains in `regression_patch.diff` for audit.

## Cap and counting

| Rule | Value |
| --- | --- |
| Hard cap | **12,000** characters |
| Counting | Python `len(str)` on Unicode text (code points) |
| Marker | `[...PATCH TRUNCATED...]` |

For Defects4J Java sources (ASCII), code-point length equals UTF-8 byte length.
Use the same convention for test representations later.

## Why not 6,000 + marker + 6,000?

The outline sketches “first 6,000 + marker + last 6,000”. That sum **exceeds**
12,000 once the marker is included (`len(marker) == 23`).

## Preregistered rule

When `len(text) > 12_000`:

1. Let `M = len("[...PATCH TRUNCATED...]")`.
2. Let `remaining = 12_000 - M`.
3. `prefix = remaining // 2`, `suffix = remaining - prefix`.
4. Emit `text[:prefix] + marker + text[-suffix:]`.

Result length is exactly 12,000. Prefix and suffix budgets differ by at most one
code point. Implemented in `src/extract_patch.py` as `truncate_to_cap`.

Carry this rule unchanged into Phase 6 preregistration; do not silently switch
to UTF-8 byte counts or a different marker.

## Metadata

`patch_meta.json` records:

- `patch_truncated`
- `original_patch_chars`
- `representation_chars`
- `representation_char_cap`
- `truncation_marker`
- `character_count_convention` (`python_len_unicode_code_points`)
