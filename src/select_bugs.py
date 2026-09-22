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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
