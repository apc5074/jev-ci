#!/usr/bin/env python3
"""Verify the Phase 1 experiment toolchain and write results/environment.json.

Noninteractive. Exit 0 only when all checks pass and the record is written.
Does not validate bug lists (Phase 2) and does not read or record credentials.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

WORKSPACE = Path("/workspace")
PIN_CANDIDATES = (
    WORKSPACE / "config" / "defects4j.pin",
    Path(os.environ.get("D4J_HOME", "/opt/defects4j")) / "defects4j.pin",
)
OUTPUT_PATH = WORKSPACE / "results" / "environment.json"
REQUIRED_TZ = "America/Los_Angeles"
REQUIRED_EXECUTABLES = ("git", "svn", "perl", "cpanm", "java", "javac", "defects4j")


def fail(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    sys.exit(1)


def run(cmd: list[str], *, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        fail(f"command not found: {cmd[0]}")
    except subprocess.TimeoutExpired:
        fail(f"command timed out after {timeout}s: {' '.join(cmd)}")


def parse_pin(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    for required in ("D4J_VERSION", "D4J_COMMIT"):
        if required not in values or not values[required]:
            fail(f"pin file {path} missing {required}")
    return values


def load_pin() -> tuple[Path, dict[str, str]]:
    for candidate in PIN_CANDIDATES:
        if candidate.is_file():
            return candidate, parse_pin(candidate)
    fail(
        "Defects4J pin file not found; expected "
        + " or ".join(str(p) for p in PIN_CANDIDATES)
    )


def check_python() -> str:
    if sys.version_info[:2] != (3, 12):
        fail(
            f"Python 3.12 required, found "
            f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        )
    return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"


def check_timezone() -> str:
    tz = os.environ.get("TZ")
    if tz != REQUIRED_TZ:
        fail(f"TZ must be {REQUIRED_TZ!r}, found {tz!r}")
    return tz


def check_java() -> str:
    java_home = os.environ.get("JAVA_HOME")
    if not java_home:
        fail("JAVA_HOME is not set")
    if not Path(java_home).is_dir():
        fail(f"JAVA_HOME does not exist: {java_home}")

    proc = run(["java", "-version"])
    # OpenJDK prints version on stderr.
    text = (proc.stderr or "") + (proc.stdout or "")
    if proc.returncode != 0:
        fail(f"java -version failed (exit {proc.returncode}): {text.strip()}")

    match = re.search(r'version "(?P<ver>[^"]+)"', text)
    if not match:
        fail(f"could not parse java version from: {text.strip()}")
    version = match.group("ver")
    # Accept 11 or 11.x.y forms.
    if not (version == "11" or version.startswith("11.")):
        fail(f"Java 11 required, found {version!r}")
    return version


def check_executables() -> dict[str, str]:
    found: dict[str, str] = {}
    for name in REQUIRED_EXECUTABLES:
        path = shutil.which(name)
        if not path:
            fail(f"required executable not on PATH: {name}")
        found[name] = path
    return found


def check_defects4j(pin: dict[str, str]) -> tuple[str, str, str]:
    d4j_home = os.environ.get("D4J_HOME", "/opt/defects4j")
    home = Path(d4j_home)
    if not home.is_dir():
        fail(f"D4J_HOME does not exist: {d4j_home}")

    expected_commit = pin["D4J_COMMIT"]
    expected_version = pin["D4J_VERSION"]

    rev = run(["git", "-C", str(home), "rev-parse", "HEAD"])
    if rev.returncode != 0:
        fail(f"could not read Defects4J commit: {rev.stderr.strip()}")
    commit = rev.stdout.strip()
    if commit != expected_commit:
        fail(
            f"Defects4J commit mismatch: expected {expected_commit}, found {commit}"
        )

    readme = home / "README.md"
    if not readme.is_file():
        fail(f"Defects4J README missing at {readme}")
    header = readme.read_text(encoding="utf-8", errors="replace").splitlines()[0]
    if f"version {expected_version}" not in header:
        fail(
            f"Defects4J README does not declare version {expected_version}: {header!r}"
        )

    info = run(["defects4j", "info", "-p", "Lang"])
    if info.returncode != 0:
        fail(
            "defects4j info -p Lang failed "
            f"(exit {info.returncode}): {(info.stderr or info.stdout).strip()}"
        )
    combined = (info.stdout or "") + (info.stderr or "")
    if "Project ID: Lang" not in combined and "Project: Lang" not in combined:
        # defects4j prints "Project ID: Lang" in the summary block
        if "Lang" not in combined:
            fail("defects4j info -p Lang did not include Lang project output")

    return expected_version, commit, combined.strip()


def repo_commit() -> str | None:
    """Return the jev-ci git commit, or None if unavailable (never '')."""
    if not (WORKSPACE / ".git").exists():
        return None
    proc = run(["git", "-C", str(WORKSPACE), "rev-parse", "HEAD"])
    if proc.returncode != 0:
        return None
    commit = proc.stdout.strip()
    return commit or None


def os_pretty_name() -> str:
    os_release = Path("/etc/os-release")
    if os_release.is_file():
        for line in os_release.read_text(encoding="utf-8").splitlines():
            if line.startswith("PRETTY_NAME="):
                return line.split("=", 1)[1].strip().strip('"')
    return f"{platform.system()} {platform.release()}"


def build_record(
    *,
    python_version: str,
    java_version: str,
    tz: str,
    d4j_version: str,
    d4j_commit: str,
    executables: dict[str, str],
) -> dict[str, Any]:
    checked_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    return {
        "checked_at": checked_at,
        "defects4j_version": d4j_version,
        "defects4j_commit": d4j_commit,
        "python_version": python_version,
        "java_version": java_version,
        "os": os_pretty_name(),
        "architecture": platform.machine(),
        "timezone": tz,
        "repository_commit": repo_commit(),
        "d4j_home": os.environ.get("D4J_HOME", "/opt/defects4j"),
        "java_home": os.environ.get("JAVA_HOME"),
        "executables": executables,
    }


def write_record(record: dict[str, Any]) -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = OUTPUT_PATH.with_suffix(".json.tmp")
    tmp_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(OUTPUT_PATH)


def main() -> None:
    pin_path, pin = load_pin()
    python_version = check_python()
    tz = check_timezone()
    java_version = check_java()
    executables = check_executables()
    d4j_version, d4j_commit, _info = check_defects4j(pin)

    record = build_record(
        python_version=python_version,
        java_version=java_version,
        tz=tz,
        d4j_version=d4j_version,
        d4j_commit=d4j_commit,
        executables=executables,
    )
    write_record(record)

    print(f"environment ok (pin={pin_path})")
    print(f"wrote {OUTPUT_PATH}")
    print(f"defects4j {d4j_version} @ {d4j_commit}")


if __name__ == "__main__":
    main()
