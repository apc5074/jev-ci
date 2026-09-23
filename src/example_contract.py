"""Example data contract: paths, status, and load/validate helpers (Phase 3).

Manifest-qualified IDs look like ``Cli-30``. On-disk example IDs use an underscore:
``Cli_30``. Layout and field visibility are documented in ``docs/example-contract.md``.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

WORKSPACE = Path("/workspace")
DEFAULT_MANIFEST_PATH = WORKSPACE / "data" / "manifest.json"
DATA_ROOT = WORKSPACE / "data"
BUGS_ROOT = DATA_ROOT / "bugs"
PATCHES_ROOT = DATA_ROOT / "patches"
TESTS_ROOT = DATA_ROOT / "tests"

# Manifest-qualified ID: Project-<digits>
QUALIFIED_ID_RE = re.compile(r"^([A-Za-z][A-Za-z0-9]*)-([1-9][0-9]*)$")

EXAMPLE_STATUS_FILENAME = "example.json"
CHECKOUT_PROVENANCE_FILENAME = "checkout_provenance.json"
ERROR_FILENAME = "error.json"

# Relative paths under each roots for one example.
BUG_REL_PATHS = {
    "example": EXAMPLE_STATUS_FILENAME,
    "checkout_provenance": CHECKOUT_PROVENANCE_FILENAME,
    "error": ERROR_FILENAME,
    "checkout_fixed": "checkouts/fixed",
    "checkout_buggy": "checkouts/buggy",
    "raw_exports": "raw",
}

PATCH_REL_PATHS = {
    "meta": "patch_meta.json",
    "full_diff": "regression_patch.diff",
    "representation": "representation.txt",  # model-visible
}

TEST_REL_PATHS = {
    "raw_tests_all": "raw/tests.all",
    "raw_tests_trigger": "raw/tests.trigger",  # private raw
    "raw_dir_src_tests": "raw/dir.src.tests",
    "inventory": "inventory.json",  # model-visible test IDs (+ lookup meta)
    "labels": "labels.json",  # PRIVATE ground truth
    "representations_dir": "representations",
    "representations_index": "representations_index.json",
}


class ExampleStatus(str, Enum):
    """Lifecycle of one example on disk.

    Only ``COMPLETE`` may be consumed by later ranking phases.
    ``INCOMPLETE`` / ``ERROR`` must never be treated as finished examples.
    """

    INCOMPLETE = "incomplete"
    COMPLETE = "complete"
    ERROR = "error"


class ExampleContractError(Exception):
    """Invalid example id, path, or on-disk contract."""


class ExampleIncompleteError(ExampleContractError):
    """Example exists but is not a complete, loadable artifact set."""


class ExampleMismatchError(ExampleContractError):
    """Example provenance does not match the locked manifest / Defects4J pin."""


@dataclass(frozen=True)
class ExampleId:
    """Stable identity for one Defects4J bug in this experiment."""

    project: str
    bug_id: str

    @property
    def qualified(self) -> str:
        """Manifest form, e.g. ``Cli-30``."""
        return f"{self.project}-{self.bug_id}"

    @property
    def slug(self) -> str:
        """Directory slug, e.g. ``Cli_30``."""
        return f"{self.project}_{self.bug_id}"

    @classmethod
    def parse(cls, value: str) -> ExampleId:
        text = value.strip()
        if "_" in text and "-" not in text.split("_", 1)[0]:
            # slug form Project_bug
            project, bug_id = text.split("_", 1)
            if not project or not bug_id:
                raise ExampleContractError(f"malformed example slug: {value!r}")
            return cls(project=project, bug_id=bug_id)
        match = QUALIFIED_ID_RE.fullmatch(text)
        if not match:
            raise ExampleContractError(
                f"malformed example id {value!r}; expected Project-N or Project_N"
            )
        return cls(project=match.group(1), bug_id=match.group(2))


def parse_example_id(value: str) -> ExampleId:
    return ExampleId.parse(value)


def bugs_dir(example: ExampleId | str, *, root: Path | None = None) -> Path:
    ex = example if isinstance(example, ExampleId) else ExampleId.parse(example)
    return (root or BUGS_ROOT) / ex.slug


def patches_dir(example: ExampleId | str, *, root: Path | None = None) -> Path:
    ex = example if isinstance(example, ExampleId) else ExampleId.parse(example)
    return (root or PATCHES_ROOT) / ex.slug


def tests_dir(example: ExampleId | str, *, root: Path | None = None) -> Path:
    ex = example if isinstance(example, ExampleId) else ExampleId.parse(example)
    return (root or TESTS_ROOT) / ex.slug


def example_paths(example: ExampleId | str, *, data_root: Path | None = None) -> dict[str, Path]:
    """Absolute paths for one example's contract files."""
    ex = example if isinstance(example, ExampleId) else ExampleId.parse(example)
    if data_root is None:
        bugs = BUGS_ROOT / ex.slug
        patches = PATCHES_ROOT / ex.slug
        tests = TESTS_ROOT / ex.slug
    else:
        bugs = data_root / "bugs" / ex.slug
        patches = data_root / "patches" / ex.slug
        tests = data_root / "tests" / ex.slug

    return {
        "bugs_dir": bugs,
        "patches_dir": patches,
        "tests_dir": tests,
        "example_json": bugs / BUG_REL_PATHS["example"],
        "checkout_provenance": bugs / BUG_REL_PATHS["checkout_provenance"],
        "error_json": bugs / BUG_REL_PATHS["error"],
        "checkout_fixed": bugs / BUG_REL_PATHS["checkout_fixed"],
        "checkout_buggy": bugs / BUG_REL_PATHS["checkout_buggy"],
        "raw_exports": bugs / BUG_REL_PATHS["raw_exports"],
        "patch_meta": patches / PATCH_REL_PATHS["meta"],
        "patch_diff": patches / PATCH_REL_PATHS["full_diff"],
        "patch_representation": patches / PATCH_REL_PATHS["representation"],
        "raw_tests_all": tests / TEST_REL_PATHS["raw_tests_all"],
        "raw_tests_trigger": tests / TEST_REL_PATHS["raw_tests_trigger"],
        "raw_dir_src_tests": tests / TEST_REL_PATHS["raw_dir_src_tests"],
        "test_inventory": tests / TEST_REL_PATHS["inventory"],
        "test_labels": tests / TEST_REL_PATHS["labels"],
        "representations_dir": tests / TEST_REL_PATHS["representations_dir"],
        "representations_index": tests / TEST_REL_PATHS["representations_index"],
    }


# Fields that may appear in model-facing payloads (patch/test representations).
MODEL_VISIBLE_PATCH_FIELDS = frozenset(
    {
        "modified_files",
        "modified_classes",
        "proposed_code_change",
        "representation_text",
        "patch_truncated",
        "original_patch_chars",
        "representation_chars",
    }
)

MODEL_VISIBLE_TEST_FIELDS = frozenset(
    {
        "test_class",
        "source_file",
        "test_source",
        "source_missing",
        "representation_chars",
    }
)

PRIVATE_LABEL_FIELDS = frozenset(
    {
        "trigger_methods",
        "positive_classes",
        "tests_trigger_raw",
    }
)

FORBIDDEN_MODEL_TOKENS = (
    "buggy",
    "fixed",
    "tests.trigger",
    "triggering",
    "bug_id",
    "defects4j",
    "reverse_fix",
    "bug_patch",
)


def load_manifest(path: Path | None = None) -> dict[str, Any]:
    manifest_path = path or DEFAULT_MANIFEST_PATH
    if not manifest_path.is_file():
        raise ExampleContractError(f"manifest not found: {manifest_path}")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def development_example_ids(manifest: Mapping[str, Any] | None = None) -> tuple[ExampleId, ...]:
    """Return development ExampleIds from the locked manifest (never resample)."""
    data = manifest if manifest is not None else load_manifest()
    ids = data.get("development_bug_ids")
    if not isinstance(ids, list) or not ids:
        raise ExampleContractError("manifest.development_bug_ids missing or empty")
    evaluation = set(data.get("evaluation_bug_ids") or [])
    out: list[ExampleId] = []
    seen: set[str] = set()
    for raw in ids:
        ex = ExampleId.parse(str(raw))
        if ex.qualified in evaluation:
            raise ExampleContractError(
                f"{ex.qualified} is listed as both development and evaluation"
            )
        if ex.qualified in seen:
            raise ExampleContractError(f"duplicate development id {ex.qualified}")
        seen.add(ex.qualified)
        out.append(ex)
    if len(out) != 25:
        raise ExampleContractError(
            f"expected 25 development ids, found {len(out)}"
        )
    return tuple(out)


def require_manifest_membership(
    example: ExampleId | str,
    *,
    manifest: Mapping[str, Any] | None = None,
    allow_evaluation: bool = False,
) -> str:
    """Ensure the example is in the locked split.

    Phase 3 extraction may use development bugs only unless ``allow_evaluation``
    is explicitly set (post-freeze evaluation runs).
    """
    data = manifest if manifest is not None else load_manifest()
    ex = example if isinstance(example, ExampleId) else ExampleId.parse(example)
    development = set(data.get("development_bug_ids") or [])
    evaluation = set(data.get("evaluation_bug_ids") or [])
    if ex.qualified in development:
        return "development"
    if ex.qualified in evaluation:
        if not allow_evaluation:
            raise ExampleContractError(
                f"{ex.qualified} is an evaluation bug; Phase 3 may only extract "
                "development examples until the design is frozen"
            )
        return "evaluation"
    raise ExampleContractError(f"{ex.qualified} is not in the locked manifest")


def atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Write JSON atomically (tmp + replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ExampleContractError(f"missing file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def new_example_record(
    example: ExampleId,
    *,
    split: str,
    manifest: Mapping[str, Any],
    status: ExampleStatus = ExampleStatus.INCOMPLETE,
) -> dict[str, Any]:
    """Create the initial ``example.json`` document (always starts incomplete)."""
    return {
        "example_id": example.slug,
        "qualified_id": example.qualified,
        "project": example.project,
        "bug_id": example.bug_id,
        "split": split,
        "status": status.value,
        "revisions": {
            "base": "Bf",
            "proposed": "Bb",
            "direction": "fixed_to_buggy",
            "notes": (
                "Fixed (Bf) is the working base for tests/source. "
                "Buggy (Bb) is the proposed production change."
            ),
        },
        "manifest": {
            "path": "data/manifest.json",
            "selection_seed": manifest.get("selection_seed"),
            "defects4j_version": manifest.get("defects4j_version"),
            "defects4j_commit": manifest.get("defects4j_commit"),
            "manifest_created_at": manifest.get("created_at"),
            "manifest_git_commit": manifest.get("git_commit"),
        },
        "artifacts": {
            "bugs": f"data/bugs/{example.slug}/",
            "patches": f"data/patches/{example.slug}/",
            "tests": f"data/tests/{example.slug}/",
        },
        "visibility": {
            "model_visible": [
                "data/patches/<id>/representation.txt",
                "data/patches/<id>/patch_meta.json (truncation stats only)",
                "data/tests/<id>/inventory.json (test class ids + source paths)",
                "data/tests/<id>/representations/*.json (compact test source)",
            ],
            "private": [
                "data/tests/<id>/labels.json",
                "data/tests/<id>/raw/tests.trigger",
                "data/bugs/<id>/error.json",
                "checkout trees under data/bugs/<id>/checkouts/",
            ],
        },
        "complete_requirements": COMPLETE_REQUIREMENTS,
        "error": None,
    }


COMPLETE_REQUIREMENTS: tuple[str, ...] = (
    "example_json",
    "checkout_provenance",
    "checkout_fixed",
    "checkout_buggy",
    "patch_meta",
    "patch_diff",
    "patch_representation",
    "raw_tests_all",
    "raw_tests_trigger",
    "test_inventory",
    "test_labels",
    "representations_index",
)


def write_example_record(record: Mapping[str, Any], *, data_root: Path | None = None) -> Path:
    ex = ExampleId.parse(str(record["qualified_id"]))
    paths = example_paths(ex, data_root=data_root)
    paths["bugs_dir"].mkdir(parents=True, exist_ok=True)
    atomic_write_json(paths["example_json"], record)
    return paths["example_json"]


def mark_example_error(
    example: ExampleId | str,
    *,
    stage: str,
    message: str,
    detail: Mapping[str, Any] | None = None,
    data_root: Path | None = None,
    retryable: bool = True,
) -> Path:
    """Record a failed extraction. Status becomes ERROR; never COMPLETE."""
    ex = example if isinstance(example, ExampleId) else ExampleId.parse(example)
    paths = example_paths(ex, data_root=data_root)
    paths["bugs_dir"].mkdir(parents=True, exist_ok=True)
    error_doc = {
        "example_id": ex.slug,
        "qualified_id": ex.qualified,
        "status": ExampleStatus.ERROR.value,
        "stage": stage,
        "message": message,
        "retryable": retryable,
        "detail": dict(detail or {}),
    }
    atomic_write_json(paths["error_json"], error_doc)

    if paths["example_json"].is_file():
        record = read_json(paths["example_json"])
    else:
        # Minimal stub if example.json was never written.
        record = {
            "example_id": ex.slug,
            "qualified_id": ex.qualified,
            "project": ex.project,
            "bug_id": ex.bug_id,
            "status": ExampleStatus.ERROR.value,
        }
    record["status"] = ExampleStatus.ERROR.value
    error_path_str = str(paths["error_json"])
    try:
        error_path_str = str(paths["error_json"].relative_to(WORKSPACE))
    except ValueError:
        pass
    record["error"] = {
        "stage": stage,
        "message": message,
        "retryable": retryable,
        "path": error_path_str,
    }
    atomic_write_json(paths["example_json"], record)
    return paths["error_json"]


def _present(path: Path, *, directory: bool = False) -> bool:
    if directory:
        return path.is_dir() and any(path.iterdir())
    return path.is_file() and path.stat().st_size > 0


def completeness_report(
    example: ExampleId | str,
    *,
    data_root: Path | None = None,
) -> dict[str, Any]:
    """Describe which required artifacts exist (does not require status=complete)."""
    ex = example if isinstance(example, ExampleId) else ExampleId.parse(example)
    paths = example_paths(ex, data_root=data_root)
    checks = {
        "example_json": _present(paths["example_json"]),
        "checkout_provenance": _present(paths["checkout_provenance"]),
        "checkout_fixed": _present(paths["checkout_fixed"], directory=True),
        "checkout_buggy": _present(paths["checkout_buggy"], directory=True),
        "patch_meta": _present(paths["patch_meta"]),
        "patch_diff": _present(paths["patch_diff"]),
        "patch_representation": _present(paths["patch_representation"]),
        "raw_tests_all": _present(paths["raw_tests_all"]),
        "raw_tests_trigger": _present(paths["raw_tests_trigger"]),
        "test_inventory": _present(paths["test_inventory"]),
        "test_labels": _present(paths["test_labels"]),
        "representations_index": _present(paths["representations_index"]),
    }
    missing = [name for name, ok in checks.items() if not ok]
    return {
        "example_id": ex.slug,
        "qualified_id": ex.qualified,
        "checks": checks,
        "missing": missing,
        "artifacts_complete": not missing,
    }


def load_example(
    example: ExampleId | str,
    *,
    data_root: Path | None = None,
    manifest: Mapping[str, Any] | None = None,
    require_complete: bool = True,
    allow_evaluation: bool = False,
) -> dict[str, Any]:
    """Load and validate an example; reject incomplete or mismatched records."""
    ex = example if isinstance(example, ExampleId) else ExampleId.parse(example)
    data = manifest if manifest is not None else load_manifest()
    split = require_manifest_membership(
        ex, manifest=data, allow_evaluation=allow_evaluation
    )
    paths = example_paths(ex, data_root=data_root)

    if not paths["example_json"].is_file():
        raise ExampleIncompleteError(f"missing example.json for {ex.qualified}")

    record = read_json(paths["example_json"])
    status = record.get("status")
    if status == ExampleStatus.ERROR.value:
        raise ExampleIncompleteError(
            f"{ex.qualified} is in error state: {record.get('error')}"
        )
    if status != ExampleStatus.COMPLETE.value and require_complete:
        raise ExampleIncompleteError(
            f"{ex.qualified} status is {status!r}, not {ExampleStatus.COMPLETE.value}"
        )

    if record.get("qualified_id") != ex.qualified:
        raise ExampleMismatchError(
            f"example.json qualified_id {record.get('qualified_id')!r} "
            f"does not match {ex.qualified}"
        )
    if record.get("split") != split:
        raise ExampleMismatchError(
            f"{ex.qualified}: example.json split {record.get('split')!r} "
            f"does not match manifest ({split})"
        )

    stored_commit = (record.get("manifest") or {}).get("defects4j_commit")
    if stored_commit != data.get("defects4j_commit"):
        raise ExampleMismatchError(
            f"{ex.qualified}: defects4j_commit mismatch "
            f"(example={stored_commit!r}, manifest={data.get('defects4j_commit')!r})"
        )
    stored_seed = (record.get("manifest") or {}).get("selection_seed")
    if stored_seed != data.get("selection_seed"):
        raise ExampleMismatchError(
            f"{ex.qualified}: selection_seed mismatch "
            f"(example={stored_seed!r}, manifest={data.get('selection_seed')!r})"
        )

    report = completeness_report(ex, data_root=data_root)
    if require_complete and not report["artifacts_complete"]:
        raise ExampleIncompleteError(
            f"{ex.qualified} missing artifacts: {report['missing']}"
        )

    # Private labels must never be merged into model-visible blobs by the loader.
    labels = None
    if paths["test_labels"].is_file():
        labels = read_json(paths["test_labels"])
        leaked = PRIVATE_LABEL_FIELDS.intersection(labels.keys())
        # labels.json is allowed to contain private fields; ensure inventory does not.
        if paths["test_inventory"].is_file():
            inventory = read_json(paths["test_inventory"])
            bad = PRIVATE_LABEL_FIELDS.intersection(inventory.keys())
            if bad:
                raise ExampleMismatchError(
                    f"{ex.qualified}: private label fields in inventory.json: {sorted(bad)}"
                )

    return {
        "example_id": ex,
        "record": record,
        "paths": paths,
        "split": split,
        "completeness": report,
        "labels": labels,
    }


def assert_no_private_fields(payload: Mapping[str, Any], *, context: str) -> None:
    bad = PRIVATE_LABEL_FIELDS.intersection(payload.keys())
    if bad:
        raise ExampleMismatchError(
            f"{context}: contains private label fields {sorted(bad)}"
        )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compute_example_content_hashes(
    example: ExampleId | str,
    *,
    data_root: Path | None = None,
) -> dict[str, str]:
    """Hash key persisted artifacts used for resume / staleness checks."""
    paths = example_paths(example, data_root=data_root)
    required = {
        "patch_representation": paths["patch_representation"],
        "patch_meta": paths["patch_meta"],
        "test_inventory": paths["test_inventory"],
        "test_labels": paths["test_labels"],
        "representations_index": paths["representations_index"],
        "checkout_provenance": paths["checkout_provenance"],
    }
    missing = [name for name, path in required.items() if not path.is_file()]
    if missing:
        raise ExampleIncompleteError(f"cannot hash; missing {missing}")
    index = read_json(paths["representations_index"])
    from src.representations import representation_settings, read_fixed_source
    if index.get("representation_settings") != representation_settings():
        raise ExampleIncompleteError("representation settings changed; refresh representations")
    query_hash = hashlib.sha256(paths["patch_representation"].read_text(encoding="utf-8").encode("utf-8")).hexdigest()
    if (index.get("query") or {}).get("query_sha256") != query_hash:
        raise ExampleMismatchError("representation query changed; refresh representations")
    for entry in index.get("representations", []):
        json_path = paths["representations_dir"] / Path(entry["path"]).name
        text_path = paths["representations_dir"] / Path(entry["text_path"]).name
        if not json_path.is_file() or not text_path.is_file():
            raise ExampleIncompleteError(f"missing representation for {entry['test_class']}")
        doc = read_json(json_path)
        if (doc.get("test_class") != entry["test_class"]
                or doc.get("representation_settings") != representation_settings()
                or doc.get("representation_text") != text_path.read_text(encoding="utf-8")):
            raise ExampleMismatchError(f"representation mismatch for {entry['test_class']}")
        if not doc.get("source_missing"):
            source = paths["checkout_fixed"] / doc["source_file"]
            digest = hashlib.sha256(read_fixed_source(source).encode("utf-8")).hexdigest()
            if digest != doc.get("source_sha256"):
                raise ExampleMismatchError(f"source changed for {entry['test_class']}")
        required[f"representation_json:{entry['test_class']}"] = json_path
        required[f"representation_text:{entry['test_class']}"] = text_path
    required["patch_diff"] = paths["patch_diff"]
    return {name: sha256_file(path) for name, path in required.items()}


def validate_example_artifacts(
    example: ExampleId | str,
    *,
    data_root: Path | None = None,
    manifest: Mapping[str, Any] | None = None,
    allow_evaluation: bool = False,
) -> dict[str, Any]:
    """Check artifacts are present, consistent, and match the locked manifest pin."""
    ex = example if isinstance(example, ExampleId) else ExampleId.parse(example)
    data = manifest if manifest is not None else load_manifest()
    split = require_manifest_membership(
        ex, manifest=data, allow_evaluation=allow_evaluation
    )
    paths = example_paths(ex, data_root=data_root)
    report = completeness_report(ex, data_root=data_root)
    if not report["artifacts_complete"]:
        raise ExampleIncompleteError(
            f"{ex.qualified} missing artifacts: {report['missing']}"
        )

    if not paths["example_json"].is_file():
        raise ExampleIncompleteError(f"missing example.json for {ex.qualified}")
    record = read_json(paths["example_json"])
    if record.get("qualified_id") != ex.qualified:
        raise ExampleMismatchError(
            f"example.json qualified_id mismatch for {ex.qualified}"
        )
    if record.get("split") != split:
        raise ExampleMismatchError(
            f"{ex.qualified}: split {record.get('split')!r} != {split}"
        )
    stored_commit = (record.get("manifest") or {}).get("defects4j_commit")
    if stored_commit != data.get("defects4j_commit"):
        raise ExampleMismatchError(
            f"{ex.qualified}: defects4j_commit mismatch "
            f"(example={stored_commit!r}, manifest={data.get('defects4j_commit')!r})"
        )

    inventory = read_json(paths["test_inventory"])
    labels = read_json(paths["test_labels"])
    index = read_json(paths["representations_index"])
    bad = PRIVATE_LABEL_FIELDS.intersection(inventory.keys())
    if bad:
        raise ExampleMismatchError(
            f"{ex.qualified}: private fields in inventory.json: {sorted(bad)}"
        )

    test_classes = inventory.get("test_classes")
    if not isinstance(test_classes, list) or not test_classes:
        raise ExampleIncompleteError(f"{ex.qualified}: empty test_classes")
    if index.get("num_representations") != len(test_classes):
        raise ExampleIncompleteError(
            f"{ex.qualified}: representations {index.get('num_representations')} "
            f"!= test_classes {len(test_classes)}"
        )
    index_ids = [e.get("test_class") for e in index.get("representations") or []]
    if index_ids != test_classes:
        raise ExampleIncompleteError(
            f"{ex.qualified}: representation index order/ids diverge from inventory"
        )
    positives = labels.get("positive_classes") or []
    if not positives:
        raise ExampleIncompleteError(f"{ex.qualified}: no positive_classes in labels")
    missing_pos = [c for c in positives if c not in set(test_classes)]
    if missing_pos:
        raise ExampleMismatchError(
            f"{ex.qualified}: positive classes not in inventory: {missing_pos}"
        )

    hashes = compute_example_content_hashes(ex, data_root=data_root)
    if (record.get("status") == ExampleStatus.COMPLETE.value
            and record.get("content_hashes") != hashes):
        raise ExampleMismatchError(f"{ex.qualified}: completed artifact contents changed")
    return {
        "example_id": ex,
        "split": split,
        "record": record,
        "paths": paths,
        "inventory": inventory,
        "labels": labels,
        "representations_index": index,
        "content_hashes": hashes,
        "completeness": report,
    }


def example_is_current_complete(
    example: ExampleId | str,
    *,
    data_root: Path | None = None,
    manifest: Mapping[str, Any] | None = None,
    allow_evaluation: bool = False,
) -> bool:
    """True when status=complete, artifacts valid, and stored hashes still match."""
    ex = example if isinstance(example, ExampleId) else ExampleId.parse(example)
    paths = example_paths(ex, data_root=data_root)
    if not paths["example_json"].is_file():
        return False
    try:
        record = read_json(paths["example_json"])
        if record.get("status") != ExampleStatus.COMPLETE.value:
            return False
        validated = validate_example_artifacts(
            ex,
            data_root=data_root,
            manifest=manifest,
            allow_evaluation=allow_evaluation,
        )
        stored = record.get("content_hashes") or {}
        if not stored:
            return False
        return stored == validated["content_hashes"]
    except (ExampleContractError, OSError, json.JSONDecodeError, KeyError):
        return False


def mark_example_complete(
    example: ExampleId | str,
    *,
    data_root: Path | None = None,
    manifest: Mapping[str, Any] | None = None,
    allow_evaluation: bool = False,
) -> dict[str, Any]:
    """Validate artifacts and set status=complete with content hashes."""
    validated = validate_example_artifacts(
        example,
        data_root=data_root,
        manifest=manifest,
        allow_evaluation=allow_evaluation,
    )
    ex = validated["example_id"]
    record = validated["record"]
    record["status"] = ExampleStatus.COMPLETE.value
    record["content_hashes"] = validated["content_hashes"]
    record["error"] = None
    write_example_record(record, data_root=data_root)
    paths = validated["paths"]
    if paths["error_json"].exists():
        paths["error_json"].unlink()
    return {
        "qualified_id": ex.qualified,
        "status": ExampleStatus.COMPLETE.value,
        "content_hashes": validated["content_hashes"],
        "num_test_classes": len(validated["inventory"]["test_classes"]),
        "num_positive_classes": len(validated["labels"].get("positive_classes") or []),
        "source_missing": (validated["inventory"].get("counts") or {}).get(
            "source_missing", 0
        ),
        "patch_truncated": bool(
            (read_json(paths["patch_meta"])).get("patch_truncated")
        ),
        "representation_truncated": (
            validated["representations_index"].get("counts") or {}
        ).get("representation_truncated", 0),
    }


def init_example_skeleton(
    example: ExampleId | str,
    *,
    data_root: Path | None = None,
    manifest: Mapping[str, Any] | None = None,
    allow_evaluation: bool = False,
) -> dict[str, Any]:
    """Create directories + incomplete example.json for a manifest-listed bug."""
    data = manifest if manifest is not None else load_manifest()
    ex = example if isinstance(example, ExampleId) else ExampleId.parse(example)
    split = require_manifest_membership(
        ex, manifest=data, allow_evaluation=allow_evaluation
    )
    paths = example_paths(ex, data_root=data_root)
    for key in ("bugs_dir", "patches_dir", "tests_dir"):
        paths[key].mkdir(parents=True, exist_ok=True)
    (paths["bugs_dir"] / "checkouts").mkdir(parents=True, exist_ok=True)
    (paths["bugs_dir"] / "raw").mkdir(parents=True, exist_ok=True)
    (paths["tests_dir"] / "raw").mkdir(parents=True, exist_ok=True)
    (paths["tests_dir"] / "representations").mkdir(parents=True, exist_ok=True)

    record = new_example_record(ex, split=split, manifest=data)
    write_example_record(record, data_root=data_root)
    return record
