#!/usr/bin/env python3
"""Refresh development representations and audits using existing checkouts only."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.example_contract import (
    WORKSPACE, atomic_write_json, development_example_ids, load_manifest,
    mark_example_complete,
)
from src.representations import build_representations_for_example
from src.audit_phase3 import audit_development_set as audit_phase3
from src.audit_phase4 import audit_development_set as audit_phase4
from src.candidates import is_shortlist_locked
from src.select_bugs import verify_manifest_integrity


def main() -> int:
    manifest = load_manifest()
    verify_manifest_integrity(manifest)
    examples = development_example_ids(manifest)
    # Preflight all locks before changing any model-visible input.
    if any(is_shortlist_locked(ex) for ex in examples):
        raise RuntimeError("semantic lock present; finish the scoring run before refreshing inputs")
    for ex in examples:
        print(f"Refreshing representations: {ex.qualified}", flush=True)
        build_representations_for_example(ex, manifest=manifest)
        mark_example_complete(ex, manifest=manifest)
    reports = {"audit-phase3": audit_phase3(manifest=manifest),
               "audit-phase4": audit_phase4()}
    for name, report in reports.items():
        atomic_write_json(WORKSPACE / "results" / f"{name}.json", report)
    return 0 if all(report["ok"] for report in reports.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
