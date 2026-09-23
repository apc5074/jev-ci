"""Load the P6-04 locked experiment configuration (JSON companion to experiment.yaml)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.example_contract import WORKSPACE, read_json

EXPERIMENT_JSON = WORKSPACE / "results" / "phase6" / "experiment.json"
EXPERIMENT_YAML = WORKSPACE / "experiment.yaml"


class ExperimentConfigError(Exception):
    """Locked experiment configuration missing or invalid."""


def load_experiment_config(*, path: Path | None = None) -> dict[str, Any]:
    """Load machine-readable locked config (JSON). YAML is the human twin."""
    target = path or EXPERIMENT_JSON
    if not target.is_file():
        raise ExperimentConfigError(f"missing experiment config: {target}")
    doc = read_json(target)
    if doc.get("schema_version") != "jev-experiment-config-v1":
        raise ExperimentConfigError(
            f"unexpected schema_version: {doc.get('schema_version')!r}"
        )
    if doc.get("status") != "methodological_choices_locked":
        raise ExperimentConfigError(
            f"config not locked: status={doc.get('status')!r}"
        )
    required = ("systems", "jev", "gpt_nano", "bm25", "outcomes", "manifest")
    missing = [k for k in required if k not in doc]
    if missing:
        raise ExperimentConfigError(f"config missing keys: {missing}")
    if doc["jev"].get("prompt_revision_count") != 0:
        raise ExperimentConfigError(
            "unexpected jev prompt_revision_count for locked retain_original"
        )
    if not EXPERIMENT_YAML.is_file():
        raise ExperimentConfigError(f"missing companion YAML: {EXPERIMENT_YAML}")
    return doc
