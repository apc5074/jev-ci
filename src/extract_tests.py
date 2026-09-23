"""Extract fixed-revision test inventory and private positive labels (Phase 3).

Model-visible ``inventory.json`` lists test class IDs and source-map metadata.
Private ``labels.json`` holds trigger methods and positive classes.
Non-triggering classes stay unlabeled (never treated as negatives).

Source resolution (P3-05) maps each FQCN to a repository-relative Java path under
the fixed checkout. Encoding policy: UTF-8 strict when probing readability.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

# Support `python src/extract_tests.py` from the repository root.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.checkout import verify_checkout_tree
from src.example_contract import (
    WORKSPACE,
    ExampleContractError,
    ExampleId,
    ExampleStatus,
    PRIVATE_LABEL_FIELDS,
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
from src.extract_patch import PatchExtractionError, parse_src_dir

# Trigger method form: ``org.foo.BarTest::testSomething`` (class :: method).
TRIGGER_SEP = "::"

# Test source encoding when probing / reading fixed-base Java files.
SOURCE_ENCODING = "utf-8"
SOURCE_ENCODING_ERRORS = "strict"

RESOLUTION_DIRECT = "direct"
RESOLUTION_FALLBACK = "fallback"
RESOLUTION_MISSING = "missing"
RESOLUTION_AMBIGUOUS = "ambiguous"


class TestExtractionError(Exception):
    """Test inventory / trigger export or validation failed."""


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _rel_to_workspace(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(WORKSPACE.resolve()))
    except ValueError:
        return str(path)


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
        raise TestExtractionError("defects4j not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise TestExtractionError(
            f"defects4j export timed out for {property_name}"
        ) from exc

    if proc.returncode != 0:
        if out_path.exists():
            out_path.unlink(missing_ok=True)
        raise TestExtractionError(
            f"defects4j export -p {property_name} failed "
            f"(exit {proc.returncode}): {(proc.stderr or proc.stdout or '').strip()}"
        )
    if not out_path.is_file():
        raise TestExtractionError(
            f"defects4j export -p {property_name} produced no output file"
        )
    try:
        return out_path.read_text(encoding="utf-8")
    finally:
        out_path.unlink(missing_ok=True)


def parse_test_classes(raw: str) -> list[str]:
    """Parse ``tests.all``: unique nonempty FQCNs, sorted lexicographically."""
    classes: list[str] = []
    seen: set[str] = set()
    duplicates: list[str] = []
    for line in raw.splitlines():
        name = line.strip()
        if not name:
            continue
        if name in seen:
            duplicates.append(name)
            continue
        seen.add(name)
        classes.append(name)
    if duplicates:
        raise TestExtractionError(
            f"tests.all contains duplicate class IDs: {sorted(set(duplicates))}"
        )
    if not classes:
        raise TestExtractionError("tests.all is empty")
    classes.sort()
    return classes


def parse_trigger_methods(raw: str) -> list[str]:
    """Parse ``tests.trigger``: nonempty method IDs, preserve export order."""
    methods: list[str] = []
    seen: set[str] = set()
    for line in raw.splitlines():
        name = line.strip()
        if not name:
            continue
        if TRIGGER_SEP not in name:
            raise TestExtractionError(
                f"trigger method missing {TRIGGER_SEP!r}: {name!r}"
            )
        class_part, method_part = name.split(TRIGGER_SEP, 1)
        if not class_part.strip() or not method_part.strip():
            raise TestExtractionError(f"malformed trigger method: {name!r}")
        if name in seen:
            continue
        seen.add(name)
        methods.append(name)
    if not methods:
        raise TestExtractionError("tests.trigger is empty")
    return methods


def positive_classes_from_triggers(trigger_methods: Sequence[str]) -> list[str]:
    """``org.foo.BarTest::testX`` → ``org.foo.BarTest``; unique, sorted."""
    classes: set[str] = set()
    for method in trigger_methods:
        class_name = method.split(TRIGGER_SEP, 1)[0].strip()
        if not class_name:
            raise TestExtractionError(f"empty class in trigger method: {method!r}")
        classes.add(class_name)
    return sorted(classes)


def validate_trigger_consistency(
    *,
    test_classes: Sequence[str],
    positive_classes: Sequence[str],
) -> dict[str, Any]:
    """Every positive class must appear in ``tests.all``.

    Never silently add a missing trigger to the inventory. An unexplained
    mismatch is a hard extraction error (no drop, no invent).
    """
    inventory = set(test_classes)
    missing = [c for c in positive_classes if c not in inventory]
    if missing:
        raise TestExtractionError(
            "triggering class(es) not present in tests.all (refusing to "
            f"silently add): {missing}. Document a Defects4J metadata "
            "exception with source evidence before special-casing."
        )
    if not positive_classes:
        raise TestExtractionError("expected at least one positive (triggering) class")
    return {
        "all_positives_in_inventory": True,
        "anomalies": [],
    }


def outer_test_class(fqcn: str) -> str:
    """Map nested FQCNs (``pkg.FooTest$Nested``) to the outer class."""
    name = fqcn.strip()
    if not name:
        raise TestExtractionError("empty test class FQCN")
    if "$" in name:
        name = name.split("$", 1)[0]
    return name


def fqcn_to_java_relpath(fqcn: str, *, dir_src_tests: str) -> str:
    """Direct package-relative path for the outer class source file."""
    outer = outer_test_class(fqcn)
    rel_java = outer.replace(".", "/") + ".java"
    return f"{dir_src_tests.rstrip('/')}/{rel_java}"


def package_path_for_fqcn(fqcn: str) -> str:
    """``org.foo.BarTest`` → ``org/foo``; top-level class → ``\"\"``."""
    outer = outer_test_class(fqcn)
    parts = outer.split(".")
    if len(parts) < 2:
        return ""
    return "/".join(parts[:-1])


def simple_class_filename(fqcn: str) -> str:
    outer = outer_test_class(fqcn)
    return outer.rsplit(".", 1)[-1] + ".java"


def _find_simple_name_candidates(
    *,
    checkout_root: Path,
    dir_src_tests: str,
    filename: str,
) -> list[str]:
    """Recursive search for ``filename`` under the test source root; sorted."""
    src_root = checkout_root / dir_src_tests
    if not src_root.is_dir():
        return []
    matches: list[str] = []
    for path in src_root.rglob(filename):
        if not path.is_file() or path.name != filename:
            continue
        rel = path.relative_to(checkout_root).as_posix()
        matches.append(rel)
    matches.sort()
    return matches


def _filter_by_package_evidence(
    candidates: Sequence[str],
    *,
    package_path: str,
    filename: str,
) -> list[str]:
    """Prefer candidates whose path matches the FQCN package; never invent."""
    if not candidates:
        return []
    if not package_path:
        return list(candidates)
    expected_tail = f"{package_path}/{filename}"
    exact = [
        c
        for c in candidates
        if c == expected_tail or c.endswith("/" + expected_tail)
    ]
    if exact:
        return exact
    needle = f"/{package_path}/"
    soft = [c for c in candidates if needle in f"/{c}"]
    if soft:
        return soft
    return list(candidates)


def probe_source_file(path: Path) -> dict[str, Any]:
    """Readability probe: UTF-8 strict. Does not store file contents."""
    try:
        text = path.read_text(
            encoding=SOURCE_ENCODING,
            errors=SOURCE_ENCODING_ERRORS,
        )
    except UnicodeDecodeError as exc:
        return {
            "readable": False,
            "encoding": SOURCE_ENCODING,
            "encoding_error": str(exc),
            "line_count": None,
        }
    except OSError as exc:
        return {
            "readable": False,
            "encoding": SOURCE_ENCODING,
            "encoding_error": str(exc),
            "line_count": None,
        }
    line_count = len(text.splitlines())
    return {
        "readable": True,
        "encoding": SOURCE_ENCODING,
        "encoding_error": None,
        "line_count": line_count,
    }


def resolve_test_source(
    fqcn: str,
    *,
    checkout_root: Path,
    dir_src_tests: str,
) -> dict[str, Any]:
    """Resolve one test FQCN to a repo-relative source path (or missing/ambiguous).

    Order: direct package path → recursive simple-name search with package
    evidence → missing. Ambiguous matches are recorded, never arbitrarily picked.
    The class ID is always retained (``source_missing`` may be true).
    """
    direct_rel = fqcn_to_java_relpath(fqcn, dir_src_tests=dir_src_tests)
    direct_path = checkout_root / direct_rel
    filename = simple_class_filename(fqcn)
    package_path = package_path_for_fqcn(fqcn)

    entry: dict[str, Any] = {
        "test_class": fqcn,
        "outer_class": outer_test_class(fqcn),
        "source_file": None,
        "source_missing": True,
        "ambiguous": False,
        "resolution": RESOLUTION_MISSING,
        "candidates": [],
        "readable": False,
        "encoding": SOURCE_ENCODING,
        "encoding_error": None,
        "line_count": None,
    }

    if direct_path.is_file():
        entry["source_file"] = direct_rel
        entry["source_missing"] = False
        entry["resolution"] = RESOLUTION_DIRECT
        entry.update(probe_source_file(direct_path))
        return entry

    candidates = _find_simple_name_candidates(
        checkout_root=checkout_root,
        dir_src_tests=dir_src_tests,
        filename=filename,
    )
    filtered = _filter_by_package_evidence(
        candidates,
        package_path=package_path,
        filename=filename,
    )
    entry["candidates"] = list(filtered)

    if len(filtered) == 1:
        chosen = filtered[0]
        entry["source_file"] = chosen
        entry["source_missing"] = False
        entry["resolution"] = RESOLUTION_FALLBACK
        entry.update(probe_source_file(checkout_root / chosen))
        return entry

    if len(filtered) > 1:
        entry["resolution"] = RESOLUTION_AMBIGUOUS
        entry["ambiguous"] = True
        entry["source_missing"] = True
        entry["source_file"] = None
        return entry

    entry["resolution"] = RESOLUTION_MISSING
    entry["candidates"] = list(candidates)
    return entry


def resolve_all_test_sources(
    test_classes: Sequence[str],
    *,
    checkout_root: Path,
    dir_src_tests: str,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Resolve every inventory ID; never drop a class."""
    source_map = [
        resolve_test_source(
            fqcn,
            checkout_root=checkout_root,
            dir_src_tests=dir_src_tests,
        )
        for fqcn in test_classes
    ]
    counts = {
        "test_classes": len(source_map),
        "source_resolved": sum(1 for e in source_map if not e["source_missing"]),
        "source_missing": sum(1 for e in source_map if e["source_missing"]),
        "source_ambiguous": sum(1 for e in source_map if e["ambiguous"]),
        "source_direct": sum(
            1 for e in source_map if e["resolution"] == RESOLUTION_DIRECT
        ),
        "source_fallback": sum(
            1 for e in source_map if e["resolution"] == RESOLUTION_FALLBACK
        ),
        "source_unreadable": sum(
            1
            for e in source_map
            if e["source_file"] is not None and not e["readable"]
        ),
    }
    return source_map, counts


def _require_fixed_checkout(
    paths: Mapping[str, Path],
    *,
    example: ExampleId,
) -> None:
    if not paths["checkout_provenance"].is_file():
        raise TestExtractionError(
            f"missing checkout provenance for {example.qualified}; run checkout first"
        )
    prov = read_json(paths["checkout_provenance"])
    if prov.get("status") != "ok":
        raise TestExtractionError(
            f"checkout provenance status is {prov.get('status')!r}, not ok"
        )
    verify_checkout_tree(
        paths["checkout_fixed"],
        project=example.project,
        version_id=f"{example.bug_id}f",
    )


def extract_tests_for_example(
    example: ExampleId | str,
    *,
    data_root: Path | None = None,
    manifest: Mapping[str, Any] | None = None,
    allow_evaluation: bool = False,
) -> dict[str, Any]:
    """Export inventory, labels, and per-class source map for one manifest bug."""
    data = manifest if manifest is not None else load_manifest()
    ex = example if isinstance(example, ExampleId) else ExampleId.parse(example)
    require_manifest_membership(
        ex, manifest=data, allow_evaluation=allow_evaluation
    )
    paths = example_paths(ex, data_root=data_root)

    try:
        _require_fixed_checkout(paths, example=ex)
        fixed_root = paths["checkout_fixed"]

        tests_all_raw = _run_defects4j_export(
            property_name="tests.all",
            checkout_dir=fixed_root,
        )
        tests_trigger_raw = _run_defects4j_export(
            property_name="tests.trigger",
            checkout_dir=fixed_root,
        )
        dir_src_tests_raw = _run_defects4j_export(
            property_name="dir.src.tests",
            checkout_dir=fixed_root,
        )

        test_classes = parse_test_classes(tests_all_raw)
        trigger_methods = parse_trigger_methods(tests_trigger_raw)
        positive_classes = positive_classes_from_triggers(trigger_methods)
        consistency = validate_trigger_consistency(
            test_classes=test_classes,
            positive_classes=positive_classes,
        )
        try:
            dir_src_tests = parse_src_dir(dir_src_tests_raw)
        except PatchExtractionError as exc:
            raise TestExtractionError(str(exc)) from exc

        source_map, source_counts = resolve_all_test_sources(
            test_classes,
            checkout_root=fixed_root,
            dir_src_tests=dir_src_tests,
        )
        if len(source_map) != len(test_classes):
            raise TestExtractionError(
                "source map length diverged from tests.all "
                f"({len(source_map)} vs {len(test_classes)})"
            )
        mapped_ids = [e["test_class"] for e in source_map]
        if mapped_ids != list(test_classes):
            raise TestExtractionError(
                "source map class order/identity diverged from tests.all"
            )

        # Raw exports under data/tests/<slug>/raw/ (trigger raw is private).
        raw_dir = paths["tests_dir"] / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_text(paths["raw_tests_all"], tests_all_raw)
        atomic_write_text(paths["raw_tests_trigger"], tests_trigger_raw)
        atomic_write_text(paths["raw_dir_src_tests"], dir_src_tests_raw)

        inventory: dict[str, Any] = {
            "example_id": ex.slug,
            "qualified_id": ex.qualified,
            "revision": "Bf",
            "dir_src_tests": dir_src_tests,
            "test_classes": test_classes,
            "num_test_classes": len(test_classes),
            "source_map": source_map,
            "source_encoding": {
                "encoding": SOURCE_ENCODING,
                "errors": SOURCE_ENCODING_ERRORS,
                "notes": (
                    "Fixed-checkout Java sources are probed as UTF-8 strict. "
                    "Decode failures set readable=false without dropping the class."
                ),
            },
            "counts": {
                "test_classes": len(test_classes),
                **{k: v for k, v in source_counts.items() if k != "test_classes"},
            },
            "extracted_at": _utcnow(),
        }
        # Hard guarantee: no private label keys in model-visible inventory.
        assert_no_private_fields(inventory, context=f"{ex.qualified} inventory.json")
        leaked = PRIVATE_LABEL_FIELDS.intersection(inventory.keys())
        if leaked:
            raise TestExtractionError(
                f"refusing to write private fields into inventory: {sorted(leaked)}"
            )

        labels: dict[str, Any] = {
            "example_id": ex.slug,
            "qualified_id": ex.qualified,
            "visibility": "private",
            "trigger_methods": trigger_methods,
            "positive_classes": positive_classes,
            "num_trigger_methods": len(trigger_methods),
            "num_positive_classes": len(positive_classes),
            "consistency": consistency,
            "notes": (
                "Non-triggering test classes are unlabeled; do not treat them "
                "as negatives for accuracy/precision metrics."
            ),
            "extracted_at": _utcnow(),
        }

        paths["tests_dir"].mkdir(parents=True, exist_ok=True)
        atomic_write_json(paths["test_inventory"], inventory)
        atomic_write_json(paths["test_labels"], labels)

        if paths["example_json"].is_file():
            record = read_json(paths["example_json"])
            record["status"] = ExampleStatus.INCOMPLETE.value
            record["tests"] = {
                "inventory": _rel_to_workspace(paths["test_inventory"]),
                "labels": _rel_to_workspace(paths["test_labels"]),
                "num_test_classes": len(test_classes),
                "num_positive_classes": len(positive_classes),
                "num_trigger_methods": len(trigger_methods),
                "source_resolved": source_counts["source_resolved"],
                "source_missing": source_counts["source_missing"],
                "source_ambiguous": source_counts["source_ambiguous"],
            }
            if record.get("error"):
                record["error"] = None
            write_example_record(record, data_root=data_root)
            if paths["error_json"].exists():
                paths["error_json"].unlink()

        return {
            "qualified_id": ex.qualified,
            "num_test_classes": len(test_classes),
            "num_positive_classes": len(positive_classes),
            "num_trigger_methods": len(trigger_methods),
            "dir_src_tests": dir_src_tests,
            "source_resolved": source_counts["source_resolved"],
            "source_missing": source_counts["source_missing"],
            "source_ambiguous": source_counts["source_ambiguous"],
            "inventory_path": _rel_to_workspace(paths["test_inventory"]),
            "labels_path": _rel_to_workspace(paths["test_labels"]),
        }

    except (TestExtractionError, ExampleContractError, OSError) as exc:
        mark_example_error(
            ex,
            stage="extract_tests",
            message=str(exc),
            detail={"qualified_id": ex.qualified},
            data_root=data_root,
            retryable=True,
        )
        if isinstance(exc, TestExtractionError):
            raise
        raise TestExtractionError(str(exc)) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Extract fixed-base test inventory, source map, and private "
            "triggering labels for a manifest development bug"
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
        result = extract_tests_for_example(
            args.example_id,
            allow_evaluation=args.allow_evaluation,
        )
    except (TestExtractionError, ExampleContractError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(
        f"tests ok {result['qualified_id']} "
        f"classes={result['num_test_classes']} "
        f"positives={result['num_positive_classes']} "
        f"triggers={result['num_trigger_methods']} "
        f"resolved={result['source_resolved']} "
        f"missing={result['source_missing']} "
        f"ambiguous={result['source_ambiguous']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
