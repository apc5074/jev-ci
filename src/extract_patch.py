"""Extract the fixed → buggy production change for one example (Phase 3).

Direction is always fixed (Bf) source as the ``-`` side and buggy (Bb) as ``+``.
Model-visible text never includes checkout directory names or revision labels.
"""

from __future__ import annotations

import argparse
import difflib
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

# Support `python src/extract_patch.py` from the repository root.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.example_contract import (
    WORKSPACE,
    ExampleContractError,
    ExampleId,
    ExampleStatus,
    atomic_write_json,
    atomic_write_text,
    example_paths,
    load_manifest,
    mark_example_error,
    read_json,
    require_manifest_membership,
    write_example_record,
)

# Hard cap for the full model-visible patch representation (Unicode code points).
REPRESENTATION_CHAR_CAP = 12_000
PATCH_TRUNCATION_MARKER = "[...PATCH TRUNCATED...]"
# Character-count convention: Python ``len(str)`` on the Unicode text (code points).
# For ASCII Java sources this equals UTF-8 byte length. See docs/patch-truncation.md.


class PatchExtractionError(Exception):
    """Patch export, path resolution, or representation failed."""


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _rel_to_workspace(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(WORKSPACE.resolve()))
    except ValueError:
        return str(path)


def truncate_to_cap(
    text: str,
    *,
    cap: int = REPRESENTATION_CHAR_CAP,
    marker: str = PATCH_TRUNCATION_MARKER,
) -> tuple[str, bool]:
    """Truncate ``text`` to ``cap`` code points, reserving space for ``marker``.

    When truncation is required, keep approximately equal prefix and suffix
    context such that ``len(prefix) + len(marker) + len(suffix) == cap``.
    The naive 6_000 + marker + 6_000 outline exceeds the 12_000 cap; this rule
    is the preregistered fix (Phase 6).
    """
    if cap < 0:
        raise ValueError("cap must be non-negative")
    if len(text) <= cap:
        return text, False
    marker_len = len(marker)
    if marker_len > cap:
        raise ValueError(
            f"truncation marker length {marker_len} exceeds cap {cap}"
        )
    remaining = cap - marker_len
    prefix_budget = remaining // 2
    suffix_budget = remaining - prefix_budget
    truncated = text[:prefix_budget] + marker + text[-suffix_budget:]
    assert len(truncated) == cap
    return truncated, True


def outer_class_name(fqcn: str) -> str:
    """Map nested FQCNs (``pkg.Foo$Bar``) to the outer class (``pkg.Foo``)."""
    name = fqcn.strip()
    if not name:
        raise PatchExtractionError("empty class name in classes.modified")
    if "$" in name:
        name = name.split("$", 1)[0]
    return name


def fqcn_to_relative_java(fqcn: str) -> str:
    """``org.apache.commons.cli.Parser`` → ``org/apache/commons/cli/Parser.java``."""
    outer = outer_class_name(fqcn)
    return outer.replace(".", "/") + ".java"


def parse_modified_classes(raw: str) -> list[str]:
    """Parse ``classes.modified`` export: one FQCN per nonempty line, sorted unique."""
    classes: list[str] = []
    seen: set[str] = set()
    for line in raw.splitlines():
        name = line.strip()
        if not name:
            continue
        if name in seen:
            continue
        seen.add(name)
        classes.append(name)
    classes.sort()
    if not classes:
        raise PatchExtractionError("classes.modified is empty")
    return classes


def parse_src_dir(raw: str) -> str:
    text = raw.strip()
    if not text:
        raise PatchExtractionError("dir.src.classes is empty")
    # Single relative directory; reject absolute / multi-line surprises.
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) != 1:
        raise PatchExtractionError(
            f"dir.src.classes expected one path, got {lines!r}"
        )
    value = lines[0]
    if value.startswith("/") or value.startswith("\\"):
        raise PatchExtractionError(
            f"dir.src.classes must be repository-relative, got {value!r}"
        )
    return value


def _run_defects4j_export(
    *,
    property_name: str,
    checkout_dir: Path,
    timeout: int = 300,
) -> str:
    """Run ``defects4j export -p <prop> -o <tmp>`` and return file contents."""
    out_path = checkout_dir / f".jev_export_{property_name.replace('.', '_')}.tmp"
    cmd = [
        "defects4j",
        "export",
        "-p",
        property_name,
        "-o",
        str(out_path),
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(checkout_dir),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise PatchExtractionError("defects4j not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise PatchExtractionError(
            f"defects4j export timed out for {property_name}"
        ) from exc
    finally:
        pass

    if proc.returncode != 0:
        if out_path.exists():
            out_path.unlink(missing_ok=True)
        raise PatchExtractionError(
            f"defects4j export -p {property_name} failed "
            f"(exit {proc.returncode}): {(proc.stderr or proc.stdout or '').strip()}"
        )
    if not out_path.is_file():
        raise PatchExtractionError(
            f"defects4j export -p {property_name} produced no output file"
        )
    try:
        return out_path.read_text(encoding="utf-8")
    finally:
        out_path.unlink(missing_ok=True)


def read_source_lines(path: Path) -> list[str] | None:
    """Read source as UTF-8 lines with trailing ``\\n``; ``None`` if missing.

    Encoding policy: strict UTF-8. Decode failures raise ``PatchExtractionError``.

    Lines keep ``\\n`` so ``difflib.unified_diff`` emits a well-formed patch
    (without them, Python 3.12 leaves body lines unterminated).
    """
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise PatchExtractionError(f"UTF-8 decode failed for {path}: {exc}") from exc
    # Normalize any CRLF/CR to LF, then ensure each line ends with \\n for difflib.
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if normalized and not normalized.endswith("\n"):
        normalized += "\n"
    return normalized.splitlines(keepends=True)


def resolve_class_sources(
    fqcn: str,
    *,
    fixed_root: Path,
    buggy_root: Path,
    fixed_src_dir: str,
    buggy_src_dir: str,
) -> dict[str, Any]:
    """Resolve one modified class to repo-relative path and both side contents."""
    rel_java = fqcn_to_relative_java(fqcn)
    fixed_rel = f"{fixed_src_dir.rstrip('/')}/{rel_java}"
    buggy_rel = f"{buggy_src_dir.rstrip('/')}/{rel_java}"
    # Prefer a single repo-relative path for headers when both sides agree.
    if fixed_rel == buggy_rel:
        header_path = fixed_rel
    else:
        # Different source roots: still use the fixed-base path as the identity
        # of the production file in the proposed change (documented).
        header_path = fixed_rel

    fixed_path = fixed_root / fixed_rel
    buggy_path = buggy_root / buggy_rel
    fixed_lines = read_source_lines(fixed_path)
    buggy_lines = read_source_lines(buggy_path)

    if fixed_lines is None and buggy_lines is None:
        raise PatchExtractionError(
            f"modified class {fqcn} missing on both sides "
            f"(fixed={fixed_rel}, buggy={buggy_rel})"
        )

    existence = "both"
    if fixed_lines is None:
        existence = "buggy_only"
        fixed_lines = []
    elif buggy_lines is None:
        existence = "fixed_only"
        buggy_lines = []

    return {
        "fqcn": fqcn,
        "outer_class": outer_class_name(fqcn),
        "header_path": header_path,
        "fixed_rel": fixed_rel,
        "buggy_rel": buggy_rel,
        "fixed_lines": fixed_lines,
        "buggy_lines": buggy_lines,
        "existence": existence,
    }


def unified_diff_for_file(
    *,
    header_path: str,
    fixed_lines: Sequence[str],
    buggy_lines: Sequence[str],
) -> str:
    """Unified diff with repository-relative headers (never checkout dir names)."""
    diff_iter = difflib.unified_diff(
        list(fixed_lines),
        list(buggy_lines),
        fromfile=header_path,
        tofile=header_path,
        n=3,
        lineterm="\n",
    )
    return "".join(diff_iter)


def build_full_diff(file_diffs: Mapping[str, str]) -> str:
    """Concatenate per-file diffs in sorted path order."""
    parts = [file_diffs[path] for path in sorted(file_diffs)]
    # Ensure a trailing newline when there is content.
    text = "".join(parts)
    if text and not text.endswith("\n"):
        text += "\n"
    return text


def build_representation(
    *,
    modified_files: Sequence[str],
    modified_classes: Sequence[str],
    full_diff: str,
) -> str:
    files_block = "\n".join(modified_files)
    classes_block = "\n".join(modified_classes)
    return (
        "MODIFIED FILES:\n"
        f"{files_block}\n"
        "\n"
        "MODIFIED CLASSES:\n"
        f"{classes_block}\n"
        "\n"
        "PROPOSED CODE CHANGE:\n"
        "\n"
        f"{full_diff}"
    )


def _require_verified_checkouts(
    paths: Mapping[str, Path],
    *,
    example: ExampleId,
) -> None:
    from src.checkout import verify_checkout_tree

    if not paths["checkout_provenance"].is_file():
        raise PatchExtractionError(
            f"missing checkout provenance for {example.qualified}; run checkout first"
        )
    prov = read_json(paths["checkout_provenance"])
    if prov.get("status") != "ok":
        raise PatchExtractionError(
            f"checkout provenance status is {prov.get('status')!r}, not ok"
        )
    verify_checkout_tree(
        paths["checkout_fixed"],
        project=example.project,
        version_id=f"{example.bug_id}f",
    )
    verify_checkout_tree(
        paths["checkout_buggy"],
        project=example.project,
        version_id=f"{example.bug_id}b",
    )


def extract_patch_for_example(
    example: ExampleId | str,
    *,
    data_root: Path | None = None,
    manifest: Mapping[str, Any] | None = None,
    allow_evaluation: bool = False,
) -> dict[str, Any]:
    """Export modified classes, build fixed→buggy diffs, write patch artifacts."""
    data = manifest if manifest is not None else load_manifest()
    ex = example if isinstance(example, ExampleId) else ExampleId.parse(example)
    require_manifest_membership(
        ex, manifest=data, allow_evaluation=allow_evaluation
    )
    paths = example_paths(ex, data_root=data_root)

    try:
        _require_verified_checkouts(paths, example=ex)

        fixed_root = paths["checkout_fixed"]
        buggy_root = paths["checkout_buggy"]

        classes_raw = _run_defects4j_export(
            property_name="classes.modified",
            checkout_dir=fixed_root,
        )
        fixed_src_raw = _run_defects4j_export(
            property_name="dir.src.classes",
            checkout_dir=fixed_root,
        )
        buggy_src_raw = _run_defects4j_export(
            property_name="dir.src.classes",
            checkout_dir=buggy_root,
        )

        modified_classes = parse_modified_classes(classes_raw)
        fixed_src_dir = parse_src_dir(fixed_src_raw)
        buggy_src_dir = parse_src_dir(buggy_src_raw)

        # Persist raw exports for audit (not model-visible).
        raw_dir = paths["raw_exports"]
        raw_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_text(raw_dir / "classes.modified", classes_raw)
        atomic_write_text(raw_dir / "dir.src.classes", fixed_src_raw)
        atomic_write_text(raw_dir / "dir.src.classes.buggy", buggy_src_raw)

        resolved: list[dict[str, Any]] = []
        for fqcn in modified_classes:
            resolved.append(
                resolve_class_sources(
                    fqcn,
                    fixed_root=fixed_root,
                    buggy_root=buggy_root,
                    fixed_src_dir=fixed_src_dir,
                    buggy_src_dir=buggy_src_dir,
                )
            )

        # One diff per unique header path (multiple nested classes → one file).
        file_diffs: dict[str, str] = {}
        file_meta: list[dict[str, Any]] = []
        for item in resolved:
            header = item["header_path"]
            if header not in file_diffs:
                file_diffs[header] = unified_diff_for_file(
                    header_path=header,
                    fixed_lines=item["fixed_lines"],
                    buggy_lines=item["buggy_lines"],
                )
            file_meta.append(
                {
                    "fqcn": item["fqcn"],
                    "outer_class": item["outer_class"],
                    "path": header,
                    "existence": item["existence"],
                    "diff_empty": not file_diffs[header].strip(),
                }
            )

        modified_files = sorted(file_diffs.keys())
        full_diff = build_full_diff(file_diffs)
        representation = build_representation(
            modified_files=modified_files,
            modified_classes=modified_classes,
            full_diff=full_diff,
        )
        original_chars = len(representation)
        capped, was_truncated = truncate_to_cap(representation)
        representation_chars = len(capped)
        if representation_chars > REPRESENTATION_CHAR_CAP:
            raise PatchExtractionError(
                f"representation exceeds cap after truncation: {representation_chars}"
            )

        # Guard: pipeline must not inject checkout/revision labels into model text.
        for forbidden in ("checkouts/fixed", "checkouts/buggy", "/fixed/", "/buggy/"):
            if forbidden in capped:
                raise PatchExtractionError(
                    f"model representation contains forbidden path fragment {forbidden!r}"
                )

        paths["patches_dir"].mkdir(parents=True, exist_ok=True)
        atomic_write_text(paths["patch_diff"], full_diff)
        atomic_write_text(paths["patch_representation"], capped)

        meta = {
            "qualified_id": ex.qualified,
            "example_id": ex.slug,
            "direction": "fixed_to_buggy",
            "patch_truncated": was_truncated,
            "original_patch_chars": original_chars,
            "representation_chars": representation_chars,
            "representation_char_cap": REPRESENTATION_CHAR_CAP,
            "truncation_marker": PATCH_TRUNCATION_MARKER,
            "character_count_convention": (
                "python_len_unicode_code_points"
            ),
            "modified_files": modified_files,
            "modified_classes": modified_classes,
            "file_resolutions": [
                {
                    "fqcn": m["fqcn"],
                    "outer_class": m["outer_class"],
                    "path": m["path"],
                    "existence": m["existence"],
                    "diff_empty": m["diff_empty"],
                }
                for m in file_meta
            ],
            "dir_src_classes": {
                "fixed": fixed_src_dir,
                "buggy": buggy_src_dir,
            },
            "artifacts": {
                "regression_patch": _rel_to_workspace(paths["patch_diff"]),
                "representation": _rel_to_workspace(paths["patch_representation"]),
                "raw_classes_modified": _rel_to_workspace(
                    raw_dir / "classes.modified"
                ),
            },
            "extracted_at": _utcnow(),
        }
        atomic_write_json(paths["patch_meta"], meta)

        # Keep example incomplete until later tickets finish.
        if paths["example_json"].is_file():
            record = read_json(paths["example_json"])
            record["status"] = ExampleStatus.INCOMPLETE.value
            record["patch"] = {
                "meta": _rel_to_workspace(paths["patch_meta"]),
                "diff": _rel_to_workspace(paths["patch_diff"]),
                "representation": _rel_to_workspace(paths["patch_representation"]),
                "patch_truncated": was_truncated,
                "original_patch_chars": original_chars,
                "representation_chars": representation_chars,
            }
            if record.get("error"):
                record["error"] = None
            write_example_record(record, data_root=data_root)
            if paths["error_json"].exists():
                paths["error_json"].unlink()

        return meta

    except (PatchExtractionError, ExampleContractError, OSError) as exc:
        mark_example_error(
            ex,
            stage="extract_patch",
            message=str(exc),
            detail={"qualified_id": ex.qualified},
            data_root=data_root,
            retryable=True,
        )
        if isinstance(exc, PatchExtractionError):
            raise
        raise PatchExtractionError(str(exc)) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Extract fixed→buggy regression patch representation for a "
            "manifest development bug"
        ),
    )
    parser.add_argument(
        "example_id",
        help="Manifest id (Cli-30) or slug (Cli_30)",
    )
    parser.add_argument(
        "--allow-evaluation",
        action="store_true",
        help="Allow evaluation-set IDs (post-freeze only)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        meta = extract_patch_for_example(
            args.example_id,
            allow_evaluation=args.allow_evaluation,
        )
    except (PatchExtractionError, ExampleContractError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(
        f"patch ok {meta['qualified_id']} "
        f"files={len(meta['modified_files'])} "
        f"classes={len(meta['modified_classes'])} "
        f"truncated={meta['patch_truncated']} "
        f"chars={meta['representation_chars']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
