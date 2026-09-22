"""Defects4J bug selection helpers.

Phase 2-01: read and validate active bug IDs from the pinned installation.
Phase 2-02: deterministic sample and development/evaluation split.
Later tickets add manifest I/O and create/verify commands.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Sequence

# Fixed project order from overall.md / Phase 2. Do not reorder.
PROJECT_ORDER: tuple[str, ...] = (
    "Cli",
    "Lang",
    "Math",
    "Jsoup",
    "JacksonDatabind",
)

# Active-bug counts stated in overall.md §4 / Defects4J 3.0.1 table.
# Compared against the installed metadata before any sampling.
ASSUMED_ACTIVE_COUNTS: dict[str, int] = {
    "Cli": 39,
    "Lang": 61,
    "Math": 106,
    "Jsoup": 93,
    "JacksonDatabind": 110,
}

MIN_ACTIVE_IDS = 30
SAMPLE_SIZE = 30
DEVELOPMENT_PER_PROJECT = 5
EVALUATION_PER_PROJECT = 25
SELECTION_SEED = 20260922
BUG_ID_RE = re.compile(r"^[1-9][0-9]*$")
D4J_BIDS_COMMAND = ("defects4j", "bids", "-p", "{project}")


class ActiveIdError(Exception):
    """Validation or metadata error while reading active bug IDs."""


class SelectionError(Exception):
    """Error while sampling or splitting bug IDs."""


@dataclass(frozen=True)
class ProjectActiveIds:
    """Active bug IDs for one Defects4J project."""

    project: str
    bug_ids: tuple[str, ...]
    content_sha256: str
    source_command: str

    @property
    def qualified_ids(self) -> tuple[str, ...]:
        return tuple(qualify_bug_id(self.project, bug_id) for bug_id in self.bug_ids)


@dataclass(frozen=True)
class ActiveBugCatalog:
    """Auditable snapshot of active IDs from a Defects4J installation."""

    defects4j_version: str
    defects4j_commit: str
    d4j_home: str
    projects: tuple[ProjectActiveIds, ...]
    metadata_source: str

    def by_project(self) -> dict[str, ProjectActiveIds]:
        return {entry.project: entry for entry in self.projects}

    def active_id_lists(self) -> dict[str, tuple[str, ...]]:
        """Bare Defects4J bug-id strings per project (input to selection)."""
        return {entry.project: entry.bug_ids for entry in self.projects}


@dataclass(frozen=True)
class ProjectSelection:
    """Ordered sample and split for one project.

    ``selected_ids`` keeps ``random.sample`` order (not re-sorted).
    Positions 0–4 are development; 5–29 are evaluation.
    """

    project: str
    selected_ids: tuple[str, ...]
    development_ids: tuple[str, ...]
    evaluation_ids: tuple[str, ...]

    @property
    def selected_qualified_ids(self) -> tuple[str, ...]:
        return tuple(qualify_bug_id(self.project, bug_id) for bug_id in self.selected_ids)

    @property
    def development_qualified_ids(self) -> tuple[str, ...]:
        return tuple(
            qualify_bug_id(self.project, bug_id) for bug_id in self.development_ids
        )

    @property
    def evaluation_qualified_ids(self) -> tuple[str, ...]:
        return tuple(
            qualify_bug_id(self.project, bug_id) for bug_id in self.evaluation_ids
        )


@dataclass(frozen=True)
class SelectionResult:
    """Full deterministic selection across all experiment projects."""

    seed: int
    projects: tuple[ProjectSelection, ...]

    @property
    def development_bug_ids(self) -> tuple[str, ...]:
        """Project-qualified IDs in project order, then sample order within project."""
        ids: list[str] = []
        for entry in self.projects:
            ids.extend(entry.development_qualified_ids)
        return tuple(ids)

    @property
    def evaluation_bug_ids(self) -> tuple[str, ...]:
        ids: list[str] = []
        for entry in self.projects:
            ids.extend(entry.evaluation_qualified_ids)
        return tuple(ids)

    @property
    def all_qualified_ids(self) -> tuple[str, ...]:
        ids: list[str] = []
        for entry in self.projects:
            ids.extend(entry.selected_qualified_ids)
        return tuple(ids)


def qualify_bug_id(project: str, bug_id: str) -> str:
    """Stable project-qualified identifier, e.g. ``Cli-7``."""
    return f"{project}-{bug_id}"


def _fail(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def _run(cmd: Sequence[str], *, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(cmd),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise ActiveIdError(f"command not found: {cmd[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ActiveIdError(f"command timed out: {' '.join(cmd)}") from exc


def read_defects4j_commit(d4j_home: Path | None = None) -> str:
    home = Path(d4j_home or os.environ.get("D4J_HOME", "/opt/defects4j"))
    proc = _run(["git", "-C", str(home), "rev-parse", "HEAD"])
    if proc.returncode != 0:
        raise ActiveIdError(
            f"could not read Defects4J commit at {home}: {proc.stderr.strip()}"
        )
    commit = proc.stdout.strip()
    if not commit:
        raise ActiveIdError(f"empty Defects4J commit at {home}")
    return commit


def read_defects4j_version(d4j_home: Path | None = None) -> str:
    home = Path(d4j_home or os.environ.get("D4J_HOME", "/opt/defects4j"))
    readme = home / "README.md"
    if not readme.is_file():
        raise ActiveIdError(f"Defects4J README missing: {readme}")
    header = readme.read_text(encoding="utf-8", errors="replace").splitlines()[0]
    match = re.search(r"version\s+(\d+\.\d+\.\d+)", header)
    if not match:
        raise ActiveIdError(f"could not parse Defects4J version from: {header!r}")
    return match.group(1)


def normalize_bug_id(raw: str, *, project: str, line_no: int) -> str:
    value = raw.strip()
    if not value:
        raise ActiveIdError(f"{project}: empty bug id on line {line_no}")
    if not BUG_ID_RE.fullmatch(value):
        raise ActiveIdError(
            f"{project}: malformed bug id {raw!r} on line {line_no} "
            "(expected a positive integer string as emitted by defects4j bids)"
        )
    return value


def validate_active_ids(
    project: str,
    raw_lines: Iterable[str],
    *,
    min_count: int = MIN_ACTIVE_IDS,
) -> tuple[str, ...]:
    """Normalize and validate one project's active ID list.

    Excludes nothing by filter here: callers must already supply the *active*
    set (``defects4j bids -p`` without ``-D``/``-A``).
    """
    ids: list[str] = []
    seen: set[str] = set()
    for line_no, raw in enumerate(raw_lines, start=1):
        if not raw.strip():
            continue
        bug_id = normalize_bug_id(raw, project=project, line_no=line_no)
        if bug_id in seen:
            raise ActiveIdError(f"{project}: duplicate active bug id {bug_id}")
        seen.add(bug_id)
        ids.append(bug_id)

    if not ids:
        raise ActiveIdError(f"{project}: active bug id list is empty")
    if len(ids) < min_count:
        raise ActiveIdError(
            f"{project}: need at least {min_count} active bug ids, found {len(ids)}"
        )
    return tuple(ids)


def content_hash(bug_ids: Sequence[str]) -> str:
    payload = "\n".join(bug_ids) + ("\n" if bug_ids else "")
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def fetch_active_bug_ids(project: str) -> tuple[tuple[str, ...], str]:
    """Return validated active IDs and the exact command used.

    Metadata source: ``defects4j bids -p <project>``
    (active bugs only; deprecated IDs require ``-D`` and are not included).
    """
    if project not in PROJECT_ORDER:
        raise ActiveIdError(f"unsupported project for this experiment: {project}")

    cmd = ["defects4j", "bids", "-p", project]
    proc = _run(cmd)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()
        raise ActiveIdError(
            f"{project}: defects4j bids failed (exit {proc.returncode}): {detail}"
        )

    lines = (proc.stdout or "").splitlines()
    bug_ids = validate_active_ids(project, lines)
    return bug_ids, " ".join(cmd)


def check_overall_assumptions(
    counts: Mapping[str, int],
    *,
    assumed: Mapping[str, int] | None = None,
) -> None:
    """Fail clearly if installed active counts disagree with overall.md."""
    expected = assumed or ASSUMED_ACTIVE_COUNTS
    mismatches: list[str] = []
    for project in PROJECT_ORDER:
        got = counts.get(project)
        want = expected.get(project)
        if got != want:
            mismatches.append(f"{project}: installed={got}, overall.md assumes={want}")
    if mismatches:
        raise ActiveIdError(
            "active bug counts differ from overall.md assumptions; "
            "do not sample until the discrepancy is resolved: "
            + "; ".join(mismatches)
        )


def load_active_bug_catalog(
    *,
    d4j_home: Path | None = None,
    assumed_counts: Mapping[str, int] | None = None,
    check_assumptions: bool = True,
) -> ActiveBugCatalog:
    """Read active IDs for the required projects from the pinned Defects4J install."""
    home = Path(d4j_home or os.environ.get("D4J_HOME", "/opt/defects4j"))
    version = read_defects4j_version(home)
    commit = read_defects4j_commit(home)

    entries: list[ProjectActiveIds] = []
    counts: dict[str, int] = {}
    for project in PROJECT_ORDER:
        bug_ids, source_command = fetch_active_bug_ids(project)
        entry = ProjectActiveIds(
            project=project,
            bug_ids=bug_ids,
            content_sha256=content_hash(bug_ids),
            source_command=source_command,
        )
        entries.append(entry)
        counts[project] = len(bug_ids)

    if check_assumptions:
        check_overall_assumptions(counts, assumed=assumed_counts)

    return ActiveBugCatalog(
        defects4j_version=version,
        defects4j_commit=commit,
        d4j_home=str(home),
        projects=tuple(entries),
        metadata_source=(
            "defects4j bids -p <project> (active bugs only; "
            "deprecated IDs from -D are excluded)"
        ),
    )


def catalog_to_jsonable(catalog: ActiveBugCatalog) -> dict:
    return {
        "defects4j_version": catalog.defects4j_version,
        "defects4j_commit": catalog.defects4j_commit,
        "d4j_home": catalog.d4j_home,
        "metadata_source": catalog.metadata_source,
        "projects": {
            entry.project: {
                "bug_ids": list(entry.bug_ids),
                "qualified_ids": list(entry.qualified_ids),
                "count": len(entry.bug_ids),
                "content_sha256": entry.content_sha256,
                "source_command": entry.source_command,
            }
            for entry in catalog.projects
        },
    }


def select_bugs(
    active_ids_by_project: Mapping[str, Sequence[str]],
    *,
    seed: int = SELECTION_SEED,
    project_order: Sequence[str] = PROJECT_ORDER,
    sample_size: int = SAMPLE_SIZE,
    development_count: int = DEVELOPMENT_PER_PROJECT,
) -> SelectionResult:
    """Deterministically sample and split bugs for every project.

    Pure function of the five active-ID lists and the seed. Uses one
    ``random.Random(seed)`` instance continuously across ``project_order``.
    For each project: ``rng.sample(sorted(active_bug_ids), sample_size)`` where
    ``sorted`` is lexicographic on **strings** (not numeric). The sampled order
    is preserved; it is not sorted again. Development = first
    ``development_count`` sampled IDs; evaluation = the remainder.
    """
    if list(project_order) != list(PROJECT_ORDER):
        raise SelectionError(
            "project_order must be exactly "
            f"{list(PROJECT_ORDER)}; got {list(project_order)}"
        )
    if sample_size != SAMPLE_SIZE or development_count != DEVELOPMENT_PER_PROJECT:
        raise SelectionError(
            f"experiment requires sample_size={SAMPLE_SIZE} and "
            f"development_count={DEVELOPMENT_PER_PROJECT}"
        )
    if seed != SELECTION_SEED:
        raise SelectionError(f"experiment selection seed must be {SELECTION_SEED}")

    return select_bugs_raw(
        active_ids_by_project,
        seed=seed,
        project_order=project_order,
        sample_size=sample_size,
        development_count=development_count,
    )


def select_bugs_raw(
    active_ids_by_project: Mapping[str, Sequence[str]],
    *,
    seed: int,
    project_order: Sequence[str] = PROJECT_ORDER,
    sample_size: int = SAMPLE_SIZE,
    development_count: int = DEVELOPMENT_PER_PROJECT,
) -> SelectionResult:
    """Same algorithm as ``select_bugs`` but without freezing seed/order checks.

    Intended for tests that assert algorithm properties with synthetic lists.
    """
    if development_count < 1 or development_count >= sample_size:
        raise SelectionError("development_count must be in 1 .. sample_size-1")

    missing = [p for p in project_order if p not in active_ids_by_project]
    if missing:
        raise SelectionError(f"missing active id lists for projects: {missing}")

    rng = random.Random(seed)
    selections: list[ProjectSelection] = []

    for project in project_order:
        raw_ids = list(active_ids_by_project[project])
        bug_ids = validate_active_ids(project, raw_ids, min_count=sample_size)
        # Lexicographic string sort — do not use key=int.
        population = sorted(bug_ids)
        selected = rng.sample(population, sample_size)
        development = tuple(selected[:development_count])
        evaluation = tuple(selected[development_count:])
        if len(development) != development_count:
            raise SelectionError(f"{project}: expected {development_count} development ids")
        if len(evaluation) != sample_size - development_count:
            raise SelectionError(
                f"{project}: expected {sample_size - development_count} evaluation ids"
            )
        if len(set(selected)) != sample_size:
            raise SelectionError(f"{project}: sampled ids are not unique")

        selections.append(
            ProjectSelection(
                project=project,
                selected_ids=tuple(selected),
                development_ids=development,
                evaluation_ids=evaluation,
            )
        )

    result = SelectionResult(seed=seed, projects=tuple(selections))
    all_ids = result.all_qualified_ids
    if len(all_ids) != len(project_order) * sample_size:
        raise SelectionError("unexpected total selected id count")
    if len(set(all_ids)) != len(all_ids):
        raise SelectionError("project-qualified selected ids are not unique")
    if len(result.development_bug_ids) != len(project_order) * development_count:
        raise SelectionError("unexpected development id count")
    if len(result.evaluation_bug_ids) != len(project_order) * (
        sample_size - development_count
    ):
        raise SelectionError("unexpected evaluation id count")
    return result


def selection_to_jsonable(result: SelectionResult) -> dict:
    return {
        "selection_seed": result.seed,
        "development_bug_ids": list(result.development_bug_ids),
        "evaluation_bug_ids": list(result.evaluation_bug_ids),
        "projects": {
            entry.project: {
                "selected_ids": list(entry.selected_ids),
                "selected_qualified_ids": list(entry.selected_qualified_ids),
                "development_ids": list(entry.development_ids),
                "development_qualified_ids": list(entry.development_qualified_ids),
                "evaluation_ids": list(entry.evaluation_ids),
                "evaluation_qualified_ids": list(entry.evaluation_qualified_ids),
            }
            for entry in result.projects
        },
    }


DEFAULT_MANIFEST_PATH = Path("/workspace/data/manifest.json")
DEFAULT_ENVIRONMENT_RECORD_PATH = Path("/workspace/results/environment.json")


class ManifestError(Exception):
    """Error building or writing the dataset manifest."""


class ManifestCorruptionError(ManifestError):
    """Manifest is internally inconsistent or fails the frozen selection rules."""


class ManifestDriftError(ManifestError):
    """Upstream Defects4J metadata no longer matches the recorded active snapshot.

    The existing manifest must be preserved; do not resample in place.
    """


def experiment_git_commit(workspace: Path | None = None) -> str | None:
    """Return the jev-ci repo commit, or None if unavailable (never '')."""
    root = workspace or Path("/workspace")
    if not (root / ".git").exists():
        return None
    proc = _run(["git", "-C", str(root), "rev-parse", "HEAD"])
    if proc.returncode != 0:
        return None
    commit = proc.stdout.strip()
    return commit or None


def load_environment_record(path: Path | None = None) -> dict:
    """Load Phase 1 ``results/environment.json`` (container environment)."""
    record_path = path or DEFAULT_ENVIRONMENT_RECORD_PATH
    if not record_path.is_file():
        raise ManifestError(
            f"environment record not found: {record_path} "
            "(run: python scripts/check_environment.py)"
        )
    try:
        data = json.loads(record_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ManifestError(f"invalid environment record JSON: {record_path}: {exc}") from exc
    required = (
        "python_version",
        "java_version",
        "os",
        "architecture",
        "timezone",
        "defects4j_version",
        "defects4j_commit",
    )
    missing = [key for key in required if key not in data]
    if missing:
        raise ManifestError(
            f"environment record missing fields {missing}: {record_path}"
        )
    return data


def build_manifest(
    catalog: ActiveBugCatalog,
    selection: SelectionResult,
    *,
    environment: Mapping[str, object],
    created_at: str | None = None,
    git_commit: str | None = None,
    environment_record_path: str = "results/environment.json",
) -> dict:
    """Assemble ``data/manifest.json`` content with selection + provenance.

    ID conventions:
    - Per-project ``active_bug_ids`` / ``selected_ids`` / ``development_ids`` /
      ``evaluation_ids``: bare Defects4J bug-id strings.
    - Top-level ``development_bug_ids`` / ``evaluation_bug_ids`` and per-project
      ``*_qualified_ids``: ``Project-<id>`` strings.
    """
    if selection.seed != SELECTION_SEED:
        raise ManifestError(f"selection seed must be {SELECTION_SEED}")
    if catalog.defects4j_commit != environment.get("defects4j_commit"):
        raise ManifestError(
            "Defects4J commit mismatch between catalog "
            f"({catalog.defects4j_commit}) and environment record "
            f"({environment.get('defects4j_commit')})"
        )
    if catalog.defects4j_version != environment.get("defects4j_version"):
        raise ManifestError(
            "Defects4J version mismatch between catalog "
            f"({catalog.defects4j_version}) and environment record "
            f"({environment.get('defects4j_version')})"
        )

    timestamp = created_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    repo_commit = git_commit if git_commit is not None else experiment_git_commit()

    projects_block: dict[str, dict] = {}
    active_by_project = catalog.by_project()
    for entry in selection.projects:
        active = active_by_project[entry.project]
        projects_block[entry.project] = {
            "active_bug_ids": list(active.bug_ids),
            "active_count": len(active.bug_ids),
            "active_content_sha256": active.content_sha256,
            "active_source_command": active.source_command,
            "selected_ids": list(entry.selected_ids),
            "development_ids": list(entry.development_ids),
            "evaluation_ids": list(entry.evaluation_ids),
            "selected_qualified_ids": list(entry.selected_qualified_ids),
            "development_qualified_ids": list(entry.development_qualified_ids),
            "evaluation_qualified_ids": list(entry.evaluation_qualified_ids),
        }

    # Insertion order is part of the stable serialization contract.
    return {
        "defects4j_version": catalog.defects4j_version,
        "defects4j_commit": catalog.defects4j_commit,
        "selection_seed": selection.seed,
        "project_order": list(PROJECT_ORDER),
        "projects": projects_block,
        "development_bug_ids": list(selection.development_bug_ids),
        "evaluation_bug_ids": list(selection.evaluation_bug_ids),
        "created_at": timestamp,
        "git_commit": repo_commit,
        "environment": {
            "python_version": environment["python_version"],
            "java_version": environment["java_version"],
            "os": environment["os"],
            "architecture": environment["architecture"],
            "timezone": environment["timezone"],
            "environment_record_path": environment_record_path,
            "environment_checked_at": environment.get("checked_at"),
        },
        "id_format": {
            "active_and_per_project_selected": (
                "bare Defects4J bug id string (e.g. \"7\")"
            ),
            "combined_development_evaluation": (
                "project-qualified string (e.g. \"Cli-7\")"
            ),
        },
        "metadata_source": catalog.metadata_source,
    }


def serialize_manifest(manifest: Mapping[str, object]) -> str:
    """Stable JSON text: 2-space indent, trailing newline, insertion-ordered keys."""
    return json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"


def write_manifest_atomic(path: Path, manifest: Mapping[str, object]) -> None:
    """Write manifest JSON via a temporary file then replace (no partial final)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = serialize_manifest(manifest)
    tmp_path = path.with_name(path.name + ".tmp")
    try:
        tmp_path.write_text(payload, encoding="utf-8")
        tmp_path.replace(path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def build_manifest_from_installation(
    *,
    environment_record_path: Path | None = None,
    check_assumptions: bool = True,
) -> dict:
    """Load catalog + environment, sample, and return a complete manifest object."""
    env_path = environment_record_path or DEFAULT_ENVIRONMENT_RECORD_PATH
    environment = load_environment_record(env_path)
    catalog = load_active_bug_catalog(check_assumptions=check_assumptions)
    selection = select_bugs(catalog.active_id_lists())
    rel_env = "results/environment.json"
    try:
        rel_env = str(env_path.relative_to(Path("/workspace")))
    except ValueError:
        rel_env = str(env_path)
    return build_manifest(
        catalog,
        selection,
        environment=environment,
        environment_record_path=rel_env,
    )


def load_manifest(path: Path | None = None) -> dict:
    """Parse manifest JSON from disk."""
    manifest_path = Path(path or DEFAULT_MANIFEST_PATH)
    if not manifest_path.is_file():
        raise ManifestError(f"manifest not found: {manifest_path}")
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ManifestCorruptionError(
            f"manifest is not valid JSON: {manifest_path}: {exc}"
        ) from exc


def _require(mapping: Mapping[str, object], key: str, *, context: str) -> object:
    if key not in mapping:
        raise ManifestCorruptionError(f"{context}: missing field {key!r}")
    return mapping[key]


def _require_list(mapping: Mapping[str, object], key: str, *, context: str) -> list:
    value = _require(mapping, key, context=context)
    if not isinstance(value, list):
        raise ManifestCorruptionError(f"{context}.{key}: expected list, got {type(value).__name__}")
    return value


def verify_manifest_integrity(manifest: Mapping[str, object]) -> None:
    """Validate schema, counts, uniqueness, and selection against the recorded active sets.

    Does not contact Defects4J. Raises ManifestCorruptionError on failure.
    """
    for key in (
        "defects4j_version",
        "defects4j_commit",
        "selection_seed",
        "projects",
        "development_bug_ids",
        "evaluation_bug_ids",
        "created_at",
        "git_commit",
        "project_order",
        "environment",
    ):
        _require(manifest, key, context="manifest")

    if manifest["selection_seed"] != SELECTION_SEED:
        raise ManifestCorruptionError(
            f"manifest.selection_seed: expected {SELECTION_SEED}, "
            f"got {manifest['selection_seed']!r}"
        )
    if manifest["project_order"] != list(PROJECT_ORDER):
        raise ManifestCorruptionError(
            f"manifest.project_order: expected {list(PROJECT_ORDER)}, "
            f"got {manifest['project_order']!r}"
        )
    if not isinstance(manifest["defects4j_version"], str) or not manifest["defects4j_version"]:
        raise ManifestCorruptionError("manifest.defects4j_version: must be a nonempty string")
    if not isinstance(manifest["defects4j_commit"], str) or not manifest["defects4j_commit"]:
        raise ManifestCorruptionError("manifest.defects4j_commit: must be a nonempty string")

    environment = manifest["environment"]
    if not isinstance(environment, Mapping):
        raise ManifestCorruptionError("manifest.environment: expected object")
    for key in ("python_version", "java_version", "os", "architecture", "timezone"):
        _require(environment, key, context="manifest.environment")

    projects = manifest["projects"]
    if not isinstance(projects, Mapping):
        raise ManifestCorruptionError("manifest.projects: expected object")

    active_lists: dict[str, list[str]] = {}
    for project in PROJECT_ORDER:
        if project not in projects:
            raise ManifestCorruptionError(f"manifest.projects: missing project {project}")
        entry = projects[project]
        if not isinstance(entry, Mapping):
            raise ManifestCorruptionError(f"manifest.projects.{project}: expected object")

        active = _require_list(entry, "active_bug_ids", context=f"projects.{project}")
        try:
            validated_active = validate_active_ids(project, [str(x) for x in active])
        except ActiveIdError as exc:
            raise ManifestCorruptionError(f"projects.{project}.active_bug_ids: {exc}") from exc
        active_lists[project] = list(validated_active)

        count = _require(entry, "active_count", context=f"projects.{project}")
        if count != len(validated_active):
            raise ManifestCorruptionError(
                f"projects.{project}.active_count: expected {len(validated_active)}, got {count}"
            )
        digest = _require(entry, "active_content_sha256", context=f"projects.{project}")
        expected_digest = content_hash(validated_active)
        if digest != expected_digest:
            raise ManifestCorruptionError(
                f"projects.{project}.active_content_sha256: does not match active_bug_ids"
            )

        selected = [str(x) for x in _require_list(entry, "selected_ids", context=f"projects.{project}")]
        development = [
            str(x) for x in _require_list(entry, "development_ids", context=f"projects.{project}")
        ]
        evaluation = [
            str(x) for x in _require_list(entry, "evaluation_ids", context=f"projects.{project}")
        ]
        if len(selected) != SAMPLE_SIZE:
            raise ManifestCorruptionError(
                f"projects.{project}.selected_ids: expected {SAMPLE_SIZE}, got {len(selected)}"
            )
        if len(set(selected)) != SAMPLE_SIZE:
            raise ManifestCorruptionError(
                f"projects.{project}.selected_ids: contains duplicates"
            )
        if development != selected[:DEVELOPMENT_PER_PROJECT]:
            raise ManifestCorruptionError(
                f"projects.{project}.development_ids: must equal selected_ids[0:5] in order"
            )
        if evaluation != selected[DEVELOPMENT_PER_PROJECT:]:
            raise ManifestCorruptionError(
                f"projects.{project}.evaluation_ids: must equal selected_ids[5:30] in order"
            )
        active_set = set(validated_active)
        for bug_id in selected:
            if bug_id not in active_set:
                raise ManifestCorruptionError(
                    f"projects.{project}.selected_ids: {bug_id!r} not in active_bug_ids"
                )

        for field, bare in (
            ("selected_qualified_ids", selected),
            ("development_qualified_ids", development),
            ("evaluation_qualified_ids", evaluation),
        ):
            qualified = [
                str(x) for x in _require_list(entry, field, context=f"projects.{project}")
            ]
            expected = [qualify_bug_id(project, bug_id) for bug_id in bare]
            if qualified != expected:
                raise ManifestCorruptionError(
                    f"projects.{project}.{field}: does not match bare ids"
                )

    try:
        expected_selection = select_bugs(active_lists)
    except (ActiveIdError, SelectionError) as exc:
        raise ManifestCorruptionError(
            f"could not recompute selection from recorded active sets: {exc}"
        ) from exc

    for entry in expected_selection.projects:
        recorded = projects[entry.project]
        if list(recorded["selected_ids"]) != list(entry.selected_ids):
            raise ManifestCorruptionError(
                f"projects.{entry.project}.selected_ids: does not match "
                f"recomputed sample for seed {SELECTION_SEED}"
            )

    development_bug_ids = [
        str(x) for x in _require_list(manifest, "development_bug_ids", context="manifest")
    ]
    evaluation_bug_ids = [
        str(x) for x in _require_list(manifest, "evaluation_bug_ids", context="manifest")
    ]
    if development_bug_ids != list(expected_selection.development_bug_ids):
        raise ManifestCorruptionError(
            "manifest.development_bug_ids: does not match recomputed development split"
        )
    if evaluation_bug_ids != list(expected_selection.evaluation_bug_ids):
        raise ManifestCorruptionError(
            "manifest.evaluation_bug_ids: does not match recomputed evaluation split"
        )
    if len(development_bug_ids) != len(PROJECT_ORDER) * DEVELOPMENT_PER_PROJECT:
        raise ManifestCorruptionError(
            f"manifest.development_bug_ids: expected "
            f"{len(PROJECT_ORDER) * DEVELOPMENT_PER_PROJECT}, got {len(development_bug_ids)}"
        )
    if len(evaluation_bug_ids) != len(PROJECT_ORDER) * EVALUATION_PER_PROJECT:
        raise ManifestCorruptionError(
            f"manifest.evaluation_bug_ids: expected "
            f"{len(PROJECT_ORDER) * EVALUATION_PER_PROJECT}, got {len(evaluation_bug_ids)}"
        )
    combined = development_bug_ids + evaluation_bug_ids
    if len(set(combined)) != len(combined):
        raise ManifestCorruptionError(
            "manifest development/evaluation ids are not unique across splits"
        )
    overlap = set(development_bug_ids) & set(evaluation_bug_ids)
    if overlap:
        raise ManifestCorruptionError(
            f"manifest: ids appear in both development and evaluation: {sorted(overlap)[:5]}"
        )


def check_manifest_upstream_drift(
    manifest: Mapping[str, object],
    *,
    check_assumptions: bool = True,
) -> None:
    """Compare recorded active snapshots to the current pinned Defects4J install.

    Raises ManifestDriftError when metadata changed. Never modifies the manifest.
    """
    try:
        catalog = load_active_bug_catalog(check_assumptions=check_assumptions)
    except ActiveIdError as exc:
        raise ManifestDriftError(
            f"could not read current Defects4J metadata for drift check: {exc}"
        ) from exc

    problems: list[str] = []
    if catalog.defects4j_version != manifest.get("defects4j_version"):
        problems.append(
            f"defects4j_version: manifest={manifest.get('defects4j_version')!r}, "
            f"installed={catalog.defects4j_version!r}"
        )
    if catalog.defects4j_commit != manifest.get("defects4j_commit"):
        problems.append(
            f"defects4j_commit: manifest={manifest.get('defects4j_commit')!r}, "
            f"installed={catalog.defects4j_commit!r}"
        )

    projects = manifest.get("projects")
    if isinstance(projects, Mapping):
        current = catalog.by_project()
        for project in PROJECT_ORDER:
            if project not in projects or not isinstance(projects[project], Mapping):
                continue
            recorded = projects[project]
            live = current[project]
            recorded_hash = recorded.get("active_content_sha256")
            if recorded_hash != live.content_sha256:
                problems.append(
                    f"projects.{project}.active_content_sha256: "
                    f"manifest={recorded_hash!r}, installed={live.content_sha256!r}"
                )
            recorded_ids = recorded.get("active_bug_ids")
            if list(recorded_ids or []) != list(live.bug_ids):
                problems.append(
                    f"projects.{project}.active_bug_ids: installed active set differs "
                    f"(manifest count={len(recorded_ids or [])}, "
                    f"installed count={len(live.bug_ids)})"
                )

    if problems:
        raise ManifestDriftError(
            "upstream Defects4J metadata differs from the locked manifest; "
            "preserving the existing file (do not resample in place): "
            + "; ".join(problems)
        )


def verify_manifest_file(
    path: Path | None = None,
    *,
    check_upstream_drift: bool = True,
    check_assumptions: bool = True,
) -> dict:
    """Load and verify a manifest without modifying it.

    Returns the parsed manifest on success.
    """
    manifest_path = Path(path or DEFAULT_MANIFEST_PATH)
    before = manifest_path.read_bytes()
    manifest = load_manifest(manifest_path)
    verify_manifest_integrity(manifest)
    if check_upstream_drift:
        check_manifest_upstream_drift(manifest, check_assumptions=check_assumptions)
    after = manifest_path.read_bytes()
    if after != before:
        raise ManifestError(
            f"verify mutated manifest bytes unexpectedly: {manifest_path}"
        )
    return manifest


def create_manifest_file(
    path: Path | None = None,
    *,
    environment_record_path: Path | None = None,
    check_assumptions: bool = True,
) -> tuple[dict, bool]:
    """Create the manifest once.

    Returns ``(manifest, created)`` where ``created`` is False when the file
    already existed and was verified without rewriting.
    """
    manifest_path = Path(path or DEFAULT_MANIFEST_PATH)
    if manifest_path.exists():
        manifest = verify_manifest_file(
            manifest_path,
            check_upstream_drift=True,
            check_assumptions=check_assumptions,
        )
        return manifest, False

    manifest = build_manifest_from_installation(
        environment_record_path=environment_record_path,
        check_assumptions=check_assumptions,
    )
    write_manifest_atomic(manifest_path, manifest)
    verify_manifest_file(
        manifest_path,
        check_upstream_drift=True,
        check_assumptions=check_assumptions,
    )
    return manifest, True


def cmd_list_active(args: argparse.Namespace) -> int:
    try:
        catalog = load_active_bug_catalog(check_assumptions=not args.skip_assumption_check)
    except ActiveIdError as exc:
        _fail(str(exc))

    payload = catalog_to_jsonable(catalog)
    if args.json:
        json.dump(payload, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    else:
        print(f"Defects4J {catalog.defects4j_version} @ {catalog.defects4j_commit}")
        print(f"source: {catalog.metadata_source}")
        for entry in catalog.projects:
            print(
                f"{entry.project}: {len(entry.bug_ids)} active "
                f"(sha256={entry.content_sha256[:12]}…) "
                f"via `{entry.source_command}`"
            )
    return 0


def cmd_sample(args: argparse.Namespace) -> int:
    try:
        catalog = load_active_bug_catalog(check_assumptions=not args.skip_assumption_check)
        result = select_bugs(catalog.active_id_lists())
    except (ActiveIdError, SelectionError) as exc:
        _fail(str(exc))

    payload = selection_to_jsonable(result)
    if args.json:
        json.dump(payload, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    else:
        print(f"seed={result.seed}")
        print(
            f"development={len(result.development_bug_ids)} "
            f"evaluation={len(result.evaluation_bug_ids)} "
            f"total={len(result.all_qualified_ids)}"
        )
        for entry in result.projects:
            print(
                f"{entry.project}: selected={len(entry.selected_ids)} "
                f"dev={list(entry.development_qualified_ids)} "
                f"eval_head={list(entry.evaluation_qualified_ids[:3])}…"
            )
    return 0


def cmd_build_manifest(args: argparse.Namespace) -> int:
    try:
        manifest = build_manifest_from_installation(
            environment_record_path=args.environment_record,
            check_assumptions=not args.skip_assumption_check,
        )
    except (ActiveIdError, SelectionError, ManifestError) as exc:
        _fail(str(exc))

    if args.output is not None:
        write_manifest_atomic(args.output, manifest)
        print(f"wrote {args.output}")
    else:
        sys.stdout.write(serialize_manifest(manifest))
    return 0


def cmd_create(args: argparse.Namespace) -> int:
    try:
        manifest, created = create_manifest_file(
            path=args.path,
            environment_record_path=args.environment_record,
            check_assumptions=not args.skip_assumption_check,
        )
    except ManifestDriftError as exc:
        print(f"error: drift: {exc}", file=sys.stderr)
        print(
            "hint: existing manifest was not modified; investigate Defects4J pin/install",
            file=sys.stderr,
        )
        return 2
    except ManifestCorruptionError as exc:
        print(f"error: corruption: {exc}", file=sys.stderr)
        print(
            "hint: run `python src/select_bugs.py verify` for details; "
            "do not force-resample",
            file=sys.stderr,
        )
        return 1
    except (ActiveIdError, SelectionError, ManifestError) as exc:
        _fail(str(exc))

    path = Path(args.path)
    if created:
        print(f"created {path}")
    else:
        print(f"manifest already exists at {path}; verified; not rewritten")
    print(
        f"development={len(manifest['development_bug_ids'])} "
        f"evaluation={len(manifest['evaluation_bug_ids'])} "
        f"seed={manifest['selection_seed']}"
    )
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    path = Path(args.path)
    before = path.read_bytes() if path.is_file() else None
    try:
        manifest = verify_manifest_file(
            path,
            check_upstream_drift=not args.skip_upstream_drift,
            check_assumptions=not args.skip_assumption_check,
        )
    except ManifestDriftError as exc:
        print(f"error: drift: {exc}", file=sys.stderr)
        if before is not None and path.is_file() and path.read_bytes() != before:
            print("error: verify mutated the manifest unexpectedly", file=sys.stderr)
        return 2
    except ManifestCorruptionError as exc:
        print(f"error: corruption: {exc}", file=sys.stderr)
        return 1
    except ManifestError as exc:
        _fail(str(exc))

    after = path.read_bytes()
    if before is not None and after != before:
        print("error: verify mutated the manifest bytes", file=sys.stderr)
        return 1

    print(f"verified {path}")
    print(
        f"defects4j={manifest['defects4j_version']}@{manifest['defects4j_commit'][:12]} "
        f"created_at={manifest['created_at']} unchanged"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Defects4J bug selection for the Jev CI experiment",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    list_active = sub.add_parser(
        "list-active",
        help="Read and validate active bug IDs for the five experiment projects",
    )
    list_active.add_argument(
        "--json",
        action="store_true",
        help="Print the auditable catalog as JSON",
    )
    list_active.add_argument(
        "--skip-assumption-check",
        action="store_true",
        help="Do not compare counts to overall.md assumptions (debug only)",
    )
    list_active.set_defaults(func=cmd_list_active)

    sample = sub.add_parser(
        "sample",
        help="Deterministically sample 30 bugs/project and show the 5/25 split",
    )
    sample.add_argument(
        "--json",
        action="store_true",
        help="Print the selection as JSON",
    )
    sample.add_argument(
        "--skip-assumption-check",
        action="store_true",
        help="Do not compare counts to overall.md assumptions (debug only)",
    )
    sample.set_defaults(func=cmd_sample)

    build_manifest_cmd = sub.add_parser(
        "build-manifest",
        help="Build manifest JSON (schema/writer); does not lock data/manifest.json",
    )
    build_manifest_cmd.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write atomically to this path (default: print to stdout)",
    )
    build_manifest_cmd.add_argument(
        "--environment-record",
        type=Path,
        default=DEFAULT_ENVIRONMENT_RECORD_PATH,
        help="Path to Phase 1 results/environment.json",
    )
    build_manifest_cmd.add_argument(
        "--skip-assumption-check",
        action="store_true",
        help="Do not compare counts to overall.md assumptions (debug only)",
    )
    build_manifest_cmd.set_defaults(func=cmd_build_manifest)

    create_cmd = sub.add_parser(
        "create",
        help="Create data/manifest.json once; if it exists, verify and do not rewrite",
    )
    create_cmd.add_argument(
        "--path",
        type=Path,
        default=DEFAULT_MANIFEST_PATH,
        help="Manifest path (default: /workspace/data/manifest.json)",
    )
    create_cmd.add_argument(
        "--environment-record",
        type=Path,
        default=DEFAULT_ENVIRONMENT_RECORD_PATH,
        help="Path to Phase 1 results/environment.json",
    )
    create_cmd.add_argument(
        "--skip-assumption-check",
        action="store_true",
        help="Do not compare counts to overall.md assumptions (debug only)",
    )
    create_cmd.set_defaults(func=cmd_create)

    verify_cmd = sub.add_parser(
        "verify",
        help="Read-only verification of an existing manifest (byte-preserving)",
    )
    verify_cmd.add_argument(
        "--path",
        type=Path,
        default=DEFAULT_MANIFEST_PATH,
        help="Manifest path (default: /workspace/data/manifest.json)",
    )
    verify_cmd.add_argument(
        "--skip-upstream-drift",
        action="store_true",
        help="Skip comparison against the current Defects4J install",
    )
    verify_cmd.add_argument(
        "--skip-assumption-check",
        action="store_true",
        help="Do not compare counts to overall.md assumptions (debug only)",
    )
    verify_cmd.set_defaults(func=cmd_verify)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
