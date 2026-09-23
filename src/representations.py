"""Build compact, model-ready test-class representations (Phase 3).

Long sources (>240 lines) reserve 40 header lines and use up to three
80-line windows, stride 60, ranked by BM25 times their novel-line fraction.
At most 240 source lines are retained, with explicit omission markers. Shared tokenizer/BM25 live in ``tokenize.py`` /
``bm25.py`` for Phase 4 reuse.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.bm25 import BM25_B, BM25_K1, BM25_VERSION, bm25_scores
from src.checkout import verify_checkout_tree
from src.example_contract import (
    WORKSPACE,
    ExampleContractError,
    ExampleId,
    ExampleStatus,
    assert_no_private_fields,
    atomic_write_json,
    atomic_write_text,
    example_paths,
    load_manifest,
    mark_example_error,
    read_json,
    require_manifest_membership,
    write_example_record,
)
from src.extract_patch import (
    REPRESENTATION_CHAR_CAP,
    truncate_to_cap,
)
from src.extract_tests import SOURCE_ENCODING, SOURCE_ENCODING_ERRORS
from src.tokenize import TOKENIZER_VERSION, tokenize

WINDOW_LINE_LIMIT = 240
WINDOW_SIZE = 80
WINDOW_STRIDE = 60
TOP_WINDOWS = 3
REPRESENTATION_VERSION = "jev-test-context-v2"
CONTEXT_HEADER_LINES = 40

def representation_settings() -> dict[str, Any]:
    return {"version": REPRESENTATION_VERSION, "line_limit": WINDOW_LINE_LIMIT,
            "window_size": WINDOW_SIZE, "stride": WINDOW_STRIDE,
            "top_windows": TOP_WINDOWS, "header_lines": CONTEXT_HEADER_LINES,
            "char_cap": REPRESENTATION_CHAR_CAP, "tokenizer": TOKENIZER_VERSION,
            "bm25": BM25_VERSION, "k1": BM25_K1, "b": BM25_B}


TEST_TRUNCATION_MARKER = "[...TEST TRUNCATED...]"
SOURCE_MISSING_PLACEHOLDER = "[SOURCE MISSING]"


class RepresentationError(Exception):
    """Failed to build a test representation."""


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _rel_to_workspace(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(WORKSPACE.resolve()))
    except ValueError:
        return str(path)


def representation_filename(fqcn: str) -> str:
    """Stable on-disk name for one test class JSON artifact."""
    return fqcn.replace("$", "__") + ".json"


def make_windows(
    lines: Sequence[str],
    *,
    size: int = WINDOW_SIZE,
    stride: int = WINDOW_STRIDE,
) -> list[tuple[int, int, list[str]]]:
    """Return ``(start, end, lines[start:end])`` windows; end is exclusive.

    Advances by ``stride`` until the file is covered. The final window may be
    shorter than ``size``. An empty file yields no windows.
    """
    n = len(lines)
    if n == 0:
        return []
    if size <= 0 or stride <= 0:
        raise ValueError("window size and stride must be positive")
    windows: list[tuple[int, int, list[str]]] = []
    start = 0
    while start < n:
        end = min(start + size, n)
        windows.append((start, end, list(lines[start:end])))
        if end >= n:
            break
        start += stride
    return windows


def select_top_windows(
    windows: Sequence[tuple[int, int, list[str]]],
    scores: Sequence[float],
    *,
    top_k: int = TOP_WINDOWS,
) -> list[tuple[int, int, list[str], float]]:
    """Pick top-k by score desc, then start index asc; return in source order."""
    if len(windows) != len(scores):
        raise RepresentationError("windows/scores length mismatch")
    ranked = sorted(
        range(len(windows)),
        key=lambda i: (-scores[i], windows[i][0], i),
    )
    chosen_idx = ranked[: min(top_k, len(windows))]
    # Restore original source order.
    chosen_idx.sort(key=lambda i: (windows[i][0], i))
    return [
        (windows[i][0], windows[i][1], windows[i][2], scores[i])
        for i in chosen_idx
    ]


def concat_windows_dedupe(
    selected: Sequence[tuple[int, int, list[str], float]],
) -> list[str]:
    """Concatenate windows in source order, dropping already-emitted overlap."""
    result: list[str] = []
    covered_until = 0
    for start, end, wlines, _score in selected:
        if start >= covered_until:
            result.extend(wlines)
            covered_until = end
            continue
        skip = covered_until - start
        if skip < len(wlines):
            result.extend(wlines[skip:])
        covered_until = max(covered_until, end)
    return result


def compact_source_lines(
    lines: Sequence[str],
    *,
    query_tokens: Sequence[str],
) -> tuple[list[str], dict[str, Any]]:
    """Apply full-file or 80/60/top-3 BM25 window compaction."""
    n = len(lines)
    meta: dict[str, Any] = {
        "source_lines": n,
        "mode": "full",
        "windows_total": 0,
        "windows_selected": [],
        "window_scores": [],
    }
    if n <= WINDOW_LINE_LIMIT:
        meta["mode"] = "full"
        return list(lines), meta

    windows = make_windows(lines, size=WINDOW_SIZE, stride=WINDOW_STRIDE)
    docs = [tokenize("\n".join(wlines)) for _s, _e, wlines in windows]
    scores = bm25_scores(query_tokens, docs, k1=BM25_K1, b=BM25_B)
    selected = select_top_windows(windows, scores, top_k=TOP_WINDOWS)
    # Reserve file context, then spend the remaining line budget on lexical
    # windows. Prefer windows contributing new lines over redundant overlap.
    retained = set(range(min(CONTEXT_HEADER_LINES, n)))
    chosen = []
    remaining = list(range(len(windows)))
    while remaining and len(chosen) < TOP_WINDOWS and len(retained) < WINDOW_LINE_LIMIT:
        best = max(remaining, key=lambda i: (
            scores[i] * len(set(range(windows[i][0], windows[i][1])) - retained)
            / max(1, windows[i][1] - windows[i][0]), -windows[i][0]))
        remaining.remove(best)
        start, end, wlines = windows[best]
        novel = sorted(set(range(start, end)) - retained)
        if not novel:
            continue
        retained.update(novel[:WINDOW_LINE_LIMIT - len(retained)])
        chosen.append((start, end, wlines, scores[best]))
    selected = sorted(chosen, key=lambda w: w[0])
    compact = []
    previous = -1
    for line_no in sorted(retained):
        if line_no > previous + 1:
            compact.append("// [...SOURCE LINES OMITTED...]")
        compact.append(lines[line_no])
        previous = line_no
    if previous < n - 1:
        compact.append("// [...SOURCE LINES OMITTED...]")
    meta["retained_line_ranges"] = []
    for line_no in sorted(retained):
        ranges = meta["retained_line_ranges"]
        if ranges and ranges[-1][1] == line_no:
            ranges[-1][1] += 1
        else:
            ranges.append([line_no, line_no + 1])
    meta.update(
        {
            "mode": "windows",
            "windows_total": len(windows),
            "windows_selected": [[s, e] for s, e, _l, _sc in selected],
            "window_scores": [
                {"start": s, "end": e, "score": sc}
                for s, e, _l, sc in selected
            ],
            "all_window_scores": [
                {"start": windows[i][0], "end": windows[i][1], "score": scores[i]}
                for i in range(len(windows))
            ],
        }
    )
    return compact, meta


def build_representation_text(
    *,
    test_class: str,
    source_file: str | None,
    test_source: str,
    source_missing: bool,
) -> str:
    source_field = (
        SOURCE_MISSING_PLACEHOLDER if source_missing or not source_file else source_file
    )
    return (
        f"TEST CLASS:\n{test_class}\n"
        f"\n"
        f"SOURCE FILE:\n{source_field}\n"
        f"\n"
        f"TEST SOURCE:\n{test_source}"
    )


def read_fixed_source(path: Path) -> str:
    """Read fixed-checkout source as LF-normalized UTF-8 text."""
    try:
        text = path.read_text(
            encoding=SOURCE_ENCODING,
            errors=SOURCE_ENCODING_ERRORS,
        )
    except UnicodeDecodeError as exc:
        raise RepresentationError(f"UTF-8 decode failed for {path}: {exc}") from exc
    return text.replace("\r\n", "\n").replace("\r", "\n")


def build_one_representation(
    *,
    test_class: str,
    source_file: str | None,
    source_missing: bool,
    checkout_fixed: Path,
    query_tokens: Sequence[str],
) -> dict[str, Any]:
    """Build one model-ready representation document for a test class."""
    compaction: dict[str, Any]
    body = ""
    source_digest = None
    effective_missing = source_missing or not source_file

    if effective_missing:
        compaction = {
            "mode": "missing",
            "source_lines": 0,
            "windows_total": 0,
            "windows_selected": [],
            "window_scores": [],
        }
        body = ""
    else:
        path = checkout_fixed / source_file
        if not path.is_file():
            # Path claimed available but absent: treat as missing, keep class.
            effective_missing = True
            compaction = {
                "mode": "missing",
                "source_lines": 0,
                "windows_total": 0,
                "windows_selected": [],
                "window_scores": [],
                "note": "source_file missing on disk at representation time",
            }
            body = ""
        else:
            text = read_fixed_source(path)
            source_digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
            lines = text.splitlines()
            compact_lines, compaction = compact_source_lines(
                lines, query_tokens=query_tokens
            )
            if compaction["mode"] == "full":
                # Preserve file text (LF-normalized), including trailing newline.
                body = text
            else:
                body = "\n".join(compact_lines)
                if compact_lines:
                    body += "\n"

    representation = build_representation_text(
        test_class=test_class,
        source_file=None if effective_missing else source_file,
        test_source=body,
        source_missing=effective_missing,
    )
    original_chars = len(representation)
    capped, was_truncated = truncate_to_cap(
        representation,
        cap=REPRESENTATION_CHAR_CAP,
        marker=TEST_TRUNCATION_MARKER,
    )
    return {
        "representation_settings": representation_settings(),
        "source_sha256": source_digest,
        "test_class": test_class,
        "source_file": None if effective_missing else source_file,
        "source_missing": effective_missing,
        "representation_text": capped,
        "compaction": compaction,
        "representation_truncated": was_truncated,
        "original_representation_chars": original_chars,
        "representation_chars": len(capped),
        "representation_char_cap": REPRESENTATION_CHAR_CAP,
        "truncation_marker": TEST_TRUNCATION_MARKER,
        "character_count_convention": "python_len_unicode_code_points",
        "tokenizer_version": TOKENIZER_VERSION,
        "bm25_version": BM25_VERSION,
        "bm25_params": {"k1": BM25_K1, "b": BM25_B},
    }


def _load_patch_query_text(paths: Mapping[str, Path]) -> str:
    """Query text for window BM25: model-visible patch representation."""
    rep = paths["patch_representation"]
    if not rep.is_file():
        raise RepresentationError(
            f"missing patch representation {rep}; run extract_patch first"
        )
    return rep.read_text(encoding="utf-8")


def _require_inputs(
    paths: Mapping[str, Path],
    *,
    example: ExampleId,
) -> None:
    if not paths["checkout_provenance"].is_file():
        raise RepresentationError(
            f"missing checkout provenance for {example.qualified}"
        )
    prov = read_json(paths["checkout_provenance"])
    if prov.get("status") != "ok":
        raise RepresentationError("checkout provenance not ok")
    verify_checkout_tree(
        paths["checkout_fixed"],
        project=example.project,
        version_id=f"{example.bug_id}f",
    )
    if not paths["test_inventory"].is_file():
        raise RepresentationError(
            f"missing inventory for {example.qualified}; run extract_tests first"
        )
    if not paths["patch_representation"].is_file():
        raise RepresentationError(
            f"missing patch representation for {example.qualified}"
        )


def build_representations_for_example(
    example: ExampleId | str,
    *,
    data_root: Path | None = None,
    manifest: Mapping[str, Any] | None = None,
    allow_evaluation: bool = False,
) -> dict[str, Any]:
    """Write one representation JSON per test class plus an index."""
    data = manifest if manifest is not None else load_manifest()
    ex = example if isinstance(example, ExampleId) else ExampleId.parse(example)
    require_manifest_membership(
        ex, manifest=data, allow_evaluation=allow_evaluation
    )
    paths = example_paths(ex, data_root=data_root)

    try:
        _require_inputs(paths, example=ex)
        inventory = read_json(paths["test_inventory"])
        test_classes = inventory.get("test_classes")
        source_map = inventory.get("source_map")
        if not isinstance(test_classes, list) or not test_classes:
            raise RepresentationError("inventory.test_classes missing or empty")
        if not isinstance(source_map, list) or len(source_map) != len(test_classes):
            raise RepresentationError(
                "inventory.source_map missing or length mismatch"
            )

        by_class = {entry["test_class"]: entry for entry in source_map}
        for fqcn in test_classes:
            if fqcn not in by_class:
                raise RepresentationError(
                    f"source_map missing entry for {fqcn}"
                )

        query_text = _load_patch_query_text(paths)
        query_tokens = tokenize(query_text)

        if paths["example_json"].is_file():
            record = read_json(paths["example_json"])
            record["status"] = ExampleStatus.INCOMPLETE.value
            write_example_record(record, data_root=data_root)
        rep_dir = paths["representations_dir"]
        if rep_dir.exists():
            for old in rep_dir.glob("*.json"):
                old.unlink()
        rep_dir.mkdir(parents=True, exist_ok=True)

        index_entries: list[dict[str, Any]] = []
        truncated_count = 0
        missing_count = 0
        windowed_count = 0

        for fqcn in test_classes:
            src_entry = by_class[fqcn]
            doc = build_one_representation(
                test_class=fqcn,
                source_file=src_entry.get("source_file"),
                source_missing=bool(src_entry.get("source_missing", False)),
                checkout_fixed=paths["checkout_fixed"],
                query_tokens=query_tokens,
            )
            assert_no_private_fields(
                doc, context=f"{ex.qualified} representation {fqcn}"
            )
            filename = representation_filename(fqcn)
            out_path = rep_dir / filename
            atomic_write_json(out_path, doc)
            # Also write plain text sibling for easy inspection / hashing.
            txt_path = rep_dir / (filename[:-5] + ".txt")
            atomic_write_text(txt_path, doc["representation_text"])

            if doc["representation_truncated"]:
                truncated_count += 1
            if doc["source_missing"]:
                missing_count += 1
            if doc["compaction"].get("mode") == "windows":
                windowed_count += 1

            rel = _rel_to_workspace(out_path)
            index_entries.append(
                {
                    "test_class": fqcn,
                    "path": rel,
                    "text_path": _rel_to_workspace(txt_path),
                    "source_file": doc["source_file"],
                    "source_missing": doc["source_missing"],
                    "compaction_mode": doc["compaction"]["mode"],
                    "representation_truncated": doc["representation_truncated"],
                    "representation_chars": doc["representation_chars"],
                }
            )

        index = {
            "example_id": ex.slug,
            "qualified_id": ex.qualified,
            "num_representations": len(index_entries),
            "representations": index_entries,
            "counts": {
                "representations": len(index_entries),
                "source_missing": missing_count,
                "representation_truncated": truncated_count,
                "window_compacted": windowed_count,
            },
            "representation_settings": representation_settings(),
            "query": {
                "source": "data/patches/<id>/representation.txt",
                "tokenizer_version": TOKENIZER_VERSION,
                "query_token_count": len(query_tokens),
                "query_sha256": hashlib.sha256(query_text.encode("utf-8")).hexdigest(),
            },
            "bm25": {
                "version": BM25_VERSION,
                "k1": BM25_K1,
                "b": BM25_B,
                "role": "long_source_window_selection",
            },
            "extracted_at": _utcnow(),
        }
        atomic_write_json(paths["representations_index"], index)

        if paths["example_json"].is_file():
            record = read_json(paths["example_json"])
            record["status"] = ExampleStatus.INCOMPLETE.value
            record["representations"] = {
                "index": _rel_to_workspace(paths["representations_index"]),
                "dir": _rel_to_workspace(rep_dir),
                "num_representations": len(index_entries),
                "source_missing": missing_count,
                "representation_truncated": truncated_count,
                "window_compacted": windowed_count,
            }
            if record.get("error"):
                record["error"] = None
            write_example_record(record, data_root=data_root)
            if paths["error_json"].exists():
                paths["error_json"].unlink()

        return {
            "qualified_id": ex.qualified,
            "num_representations": len(index_entries),
            "source_missing": missing_count,
            "representation_truncated": truncated_count,
            "window_compacted": windowed_count,
            "index_path": _rel_to_workspace(paths["representations_index"]),
        }

    except (RepresentationError, ExampleContractError, OSError, KeyError) as exc:
        mark_example_error(
            ex,
            stage="representations",
            message=str(exc),
            detail={"qualified_id": ex.qualified},
            data_root=data_root,
            retryable=True,
        )
        if isinstance(exc, RepresentationError):
            raise
        raise RepresentationError(str(exc)) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build compact model-ready test representations for a "
            "manifest development bug"
        ),
    )
    parser.add_argument("example_id", help="Manifest id (Cli-30) or slug (Cli_30)")
    parser.add_argument(
        "--allow-evaluation",
        action="store_true",
        help="Allow evaluation-set IDs (post-freeze only)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = build_representations_for_example(
            args.example_id,
            allow_evaluation=args.allow_evaluation,
        )
    except (RepresentationError, ExampleContractError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(
        f"representations ok {result['qualified_id']} "
        f"n={result['num_representations']} "
        f"windowed={result['window_compacted']} "
        f"missing={result['source_missing']} "
        f"truncated={result['representation_truncated']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
