"""Isolated Defects4J fixed (Bf) and buggy (Bb) checkouts for one example.

Work directories are always:

  data/bugs/<Project>_<id>/checkouts/fixed
  data/bugs/<Project>_<id>/checkouts/buggy

Reuse only when ``checkout_provenance.json`` and each tree's
``.defects4j.config`` match the requested example and pinned Defects4J commit.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

# Support `python src/checkout.py` from the repository root.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.example_contract import (
    WORKSPACE,
    ExampleContractError,
    ExampleId,
    ExampleStatus,
    atomic_write_json,
    example_paths,
    init_example_skeleton,
    load_manifest,
    mark_example_error,
    read_json,
    require_manifest_membership,
    write_example_record,
)

D4J_CONFIG_NAME = ".defects4j.config"


class CheckoutError(Exception):
    """Checkout failed or provenance does not match."""


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _rel_to_workspace(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(WORKSPACE.resolve()))
    except ValueError:
        # Keep deterministic repo-relative style when possible; never put home paths
        # into provenance consumed as model input (this file is private anyway).
        return str(path)


def read_defects4j_config(checkout_dir: Path) -> dict[str, str]:
    config_path = checkout_dir / D4J_CONFIG_NAME
    if not config_path.is_file():
        raise CheckoutError(f"missing {D4J_CONFIG_NAME} in {checkout_dir}")
    values: dict[str, str] = {}
    for raw in config_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    if "pid" not in values or "vid" not in values:
        raise CheckoutError(f"incomplete {config_path}: {values}")
    return values


def verify_checkout_tree(
    checkout_dir: Path,
    *,
    project: str,
    version_id: str,
) -> dict[str, str]:
    if not checkout_dir.is_dir():
        raise CheckoutError(f"checkout directory missing: {checkout_dir}")
    if not any(checkout_dir.iterdir()):
        raise CheckoutError(f"checkout directory empty: {checkout_dir}")
    cfg = read_defects4j_config(checkout_dir)
    if cfg["pid"] != project:
        raise CheckoutError(
            f"{checkout_dir}: expected pid={project}, found {cfg['pid']}"
        )
    if cfg["vid"] != version_id:
        raise CheckoutError(
            f"{checkout_dir}: expected vid={version_id}, found {cfg['vid']}"
        )
    return cfg


def _run_defects4j_checkout(
    *,
    project: str,
    version_id: str,
    work_dir: Path,
    timeout: int = 600,
) -> dict[str, Any]:
    """Run ``defects4j checkout`` into an empty work_dir."""
    work_dir.parent.mkdir(parents=True, exist_ok=True)
    if work_dir.exists():
        shutil.rmtree(work_dir)
    # defects4j creates the work directory.
    cmd = [
        "defects4j",
        "checkout",
        "-p",
        project,
        "-v",
        version_id,
        "-w",
        str(work_dir),
    ]
    try:
        proc = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise CheckoutError("defects4j not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise CheckoutError(
            f"defects4j checkout timed out after {timeout}s: {' '.join(cmd)}"
        ) from exc

    record = {
        "command": [
            "defects4j",
            "checkout",
            "-p",
            project,
            "-v",
            version_id,
            "-w",
            _rel_to_workspace(work_dir),
        ],
        "exit_status": proc.returncode,
        "stdout_tail": (proc.stdout or "")[-4000:],
        "stderr_tail": (proc.stderr or "")[-4000:],
    }
    if proc.returncode != 0:
        raise CheckoutError(
            f"defects4j checkout failed (exit {proc.returncode}) for "
            f"{project}-{version_id}: {(proc.stderr or proc.stdout or '').strip()}"
        )
    verify_checkout_tree(work_dir, project=project, version_id=version_id)
    return record


def _provenance_matches(
    existing: Mapping[str, Any],
    *,
    example: ExampleId,
    defects4j_commit: str,
    defects4j_version: str,
) -> bool:
    try:
        return (
            existing.get("qualified_id") == example.qualified
            and existing.get("project") == example.project
            and existing.get("bug_id") == example.bug_id
            and existing.get("defects4j_commit") == defects4j_commit
            and existing.get("defects4j_version") == defects4j_version
            and existing.get("status") == "ok"
            and (existing.get("fixed") or {}).get("version_id")
            == f"{example.bug_id}f"
            and (existing.get("buggy") or {}).get("version_id")
            == f"{example.bug_id}b"
        )
    except Exception:
        return False


def _trees_match_request(
    paths: Mapping[str, Path],
    *,
    example: ExampleId,
) -> bool:
    try:
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
        return True
    except CheckoutError:
        return False


def checkout_example(
    example: ExampleId | str,
    *,
    data_root: Path | None = None,
    manifest: Mapping[str, Any] | None = None,
    force: bool = False,
    allow_evaluation: bool = False,
) -> dict[str, Any]:
    """Ensure verified Bf/Bb checkouts exist for a manifest-listed bug.

    Returns the provenance document. On failure, marks the example as ERROR /
    incomplete and re-raises ``CheckoutError``.
    """
    data = manifest if manifest is not None else load_manifest()
    ex = example if isinstance(example, ExampleId) else ExampleId.parse(example)
    split = require_manifest_membership(
        ex, manifest=data, allow_evaluation=allow_evaluation
    )
    defects4j_commit = str(data["defects4j_commit"])
    defects4j_version = str(data["defects4j_version"])
    # Confirm installed Defects4J matches the manifest pin.
    installed = os.environ.get("D4J_HOME", "/opt/defects4j")
    pin_proc = subprocess.run(
        ["git", "-C", installed, "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    if pin_proc.returncode != 0:
        raise CheckoutError(f"cannot read Defects4J commit at {installed}")
    installed_commit = pin_proc.stdout.strip()
    if installed_commit != defects4j_commit:
        raise CheckoutError(
            f"installed Defects4J commit {installed_commit} does not match "
            f"manifest pin {defects4j_commit}"
        )

    init_example_skeleton(
        ex,
        data_root=data_root,
        manifest=data,
        allow_evaluation=allow_evaluation,
    )
    paths = example_paths(ex, data_root=data_root)
    provenance_path = paths["checkout_provenance"]

    if not force and provenance_path.is_file():
        existing = read_json(provenance_path)
        if _provenance_matches(
            existing,
            example=ex,
            defects4j_commit=defects4j_commit,
            defects4j_version=defects4j_version,
        ) and _trees_match_request(paths, example=ex):
            existing["reused"] = True
            existing["checked_at"] = _utcnow()
            atomic_write_json(provenance_path, existing)
            return existing

    # Stale / partial / mismatched: rebuild both sides so they cannot mix.
    try:
        fixed_run = _run_defects4j_checkout(
            project=ex.project,
            version_id=f"{ex.bug_id}f",
            work_dir=paths["checkout_fixed"],
        )
        buggy_run = _run_defects4j_checkout(
            project=ex.project,
            version_id=f"{ex.bug_id}b",
            work_dir=paths["checkout_buggy"],
        )
    except CheckoutError as exc:
        mark_example_error(
            ex,
            stage="checkout",
            message=str(exc),
            detail={"qualified_id": ex.qualified},
            data_root=data_root,
            retryable=True,
        )
        # Keep example.json as error/incomplete — never complete.
        raise

    provenance = {
        "qualified_id": ex.qualified,
        "example_id": ex.slug,
        "project": ex.project,
        "bug_id": ex.bug_id,
        "split": split,
        "status": "ok",
        "reused": False,
        "checked_at": _utcnow(),
        "defects4j_version": defects4j_version,
        "defects4j_commit": defects4j_commit,
        "d4j_home": "D4J_HOME",  # logical; avoid baking host absolute paths
        "fixed": {
            "version_id": f"{ex.bug_id}f",
            "role": "base",
            "work_dir": _rel_to_workspace(paths["checkout_fixed"]),
            "defects4j_config": read_defects4j_config(paths["checkout_fixed"]),
            "command": fixed_run["command"],
            "exit_status": fixed_run["exit_status"],
        },
        "buggy": {
            "version_id": f"{ex.bug_id}b",
            "role": "proposed_change",
            "work_dir": _rel_to_workspace(paths["checkout_buggy"]),
            "defects4j_config": read_defects4j_config(paths["checkout_buggy"]),
            "command": buggy_run["command"],
            "exit_status": buggy_run["exit_status"],
        },
        # Captured for debugging only; not model-visible.
        "logs": {
            "fixed_stdout_tail": fixed_run["stdout_tail"],
            "fixed_stderr_tail": fixed_run["stderr_tail"],
            "buggy_stdout_tail": buggy_run["stdout_tail"],
            "buggy_stderr_tail": buggy_run["stderr_tail"],
        },
    }
    atomic_write_json(provenance_path, provenance)

    # Refresh example.json but keep status incomplete until later tickets finish.
    record = read_json(paths["example_json"])
    record["status"] = ExampleStatus.INCOMPLETE.value
    record["split"] = split
    record["checkouts"] = {
        "fixed": provenance["fixed"]["work_dir"],
        "buggy": provenance["buggy"]["work_dir"],
        "provenance": _rel_to_workspace(provenance_path),
    }
    if record.get("error"):
        record["error"] = None
    write_example_record(record, data_root=data_root)
    if paths["error_json"].exists():
        paths["error_json"].unlink()

    return provenance


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check out isolated Defects4J Bf/Bb trees for a manifest bug",
    )
    parser.add_argument(
        "example_id",
        help="Manifest id (Cli-30) or slug (Cli_30); development bugs only by default",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild checkouts even when provenance matches",
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
        provenance = checkout_example(
            args.example_id,
            force=args.force,
            allow_evaluation=args.allow_evaluation,
        )
    except (CheckoutError, ExampleContractError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(
        f"checkout ok {provenance['qualified_id']} "
        f"reused={provenance.get('reused', False)}"
    )
    print(f"fixed={provenance['fixed']['work_dir']} vid={provenance['fixed']['version_id']}")
    print(f"buggy={provenance['buggy']['work_dir']} vid={provenance['buggy']['version_id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
