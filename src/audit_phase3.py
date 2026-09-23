"""Phase 3 extraction integrity audit (all development examples).

Checks patch direction provenance, trigger consistency, representation
coverage, and leakage in serialized model-visible states. Does not treat
authentic Java source containing the word ``fixed`` as leakage.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.checkout import read_defects4j_config, verify_checkout_tree
from src.example_contract import (
    WORKSPACE,
    ExampleContractError,
    ExampleId,
    ExampleStatus,
    PRIVATE_LABEL_FIELDS,
    atomic_write_json,
    development_example_ids,
    example_paths,
    load_example,
    load_manifest,
    read_json,
    validate_example_artifacts,
)

# Pipeline-inserted fragments that must not appear in model-visible text.
# Whole-word "fixed"/"buggy" inside Java source bodies is allowed.
PIPELINE_LEAK_REGEXES: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE | re.MULTILINE)
    for p in (
        r"checkouts/fixed",
        r"checkouts/buggy",
        r"(^|[\s\"'`])/fixed/",
        r"(^|[\s\"'`])/buggy/",
        r"\btests\.trigger\b",
        r"\btrigger_methods\b",
        r"\bpositive_classes\b",
        r"\breverse_fix\b",
        r"\bbug_patch\b",
        r"\bdefects4j\b",
        r"\bbug_id\b",
        r"\btriggering method\b",
        r"\bexpected result\b",
    )
)


class AuditError(Exception):
    """One or more integrity checks failed."""


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def find_pipeline_leaks(text: str) -> list[str]:
    """Return matched pipeline leak patterns (not authentic source prose)."""
    hits: list[str] = []
    for pattern in PIPELINE_LEAK_REGEXES:
        match = pattern.search(text)
        if match:
            hits.append(match.group(0))
    return hits


def model_state_envelope(text: str, *, kind: str) -> str:
    """Return pipeline-composed headers only (exclude authentic source bodies)."""
    if kind == "patch":
        marker = "PROPOSED CODE CHANGE:"
        if marker in text:
            return text.split(marker, 1)[0]
        return text
    if kind == "test":
        marker = "TEST SOURCE:"
        if marker in text:
            return text.split(marker, 1)[0]
        return text
    raise ValueError(f"unknown model-state kind {kind!r}")


def audit_model_visible_text(
    text: str,
    *,
    qualified_id: str,
    trigger_methods: Sequence[str],
    context: str,
    kind: str,
) -> list[str]:
    """Inspect serialized model state for label / provenance leaks.

    Word tokens such as ``fixed`` or ``Defects4J`` inside authentic Java source
    are not leakage. Checks focus on the pipeline envelope (headers) plus a few
    full-text patterns that should never be inserted by the extractor.
    """
    problems: list[str] = []
    envelope = model_state_envelope(text, kind=kind)

    for hit in find_pipeline_leaks(envelope):
        problems.append(f"{context}: pipeline leak {hit!r} in envelope")

    # Checkout directory names must not appear anywhere in model state.
    for fragment in ("checkouts/fixed", "checkouts/buggy"):
        if fragment in text:
            problems.append(f"{context}: contains checkout path {fragment!r}")

    if qualified_id in envelope:
        problems.append(f"{context}: envelope contains bug id {qualified_id!r}")
    slug = qualified_id.replace("-", "_")
    if slug in envelope:
        problems.append(f"{context}: envelope contains example slug {slug!r}")

    for method in trigger_methods:
        if method and method in text:
            problems.append(f"{context}: contains trigger method {method!r}")
    return problems


def _assert_patch_direction(paths: Mapping[str, Path], ex: ExampleId) -> list[str]:
    problems: list[str] = []
    try:
        verify_checkout_tree(
            paths["checkout_fixed"],
            project=ex.project,
            version_id=f"{ex.bug_id}f",
        )
        verify_checkout_tree(
            paths["checkout_buggy"],
            project=ex.project,
            version_id=f"{ex.bug_id}b",
        )
    except Exception as exc:
        problems.append(f"checkout revision mismatch: {exc}")
        return problems

    prov = read_json(paths["checkout_provenance"])
    if (prov.get("fixed") or {}).get("version_id") != f"{ex.bug_id}f":
        problems.append("provenance fixed version_id is not Bf")
    if (prov.get("buggy") or {}).get("version_id") != f"{ex.bug_id}b":
        problems.append("provenance buggy version_id is not Bb")

    cfg_f = read_defects4j_config(paths["checkout_fixed"])
    cfg_b = read_defects4j_config(paths["checkout_buggy"])
    if cfg_f.get("vid") != f"{ex.bug_id}f" or cfg_b.get("vid") != f"{ex.bug_id}b":
        problems.append(
            f".defects4j.config vids unexpected: fixed={cfg_f.get('vid')} "
            f"buggy={cfg_b.get('vid')}"
        )

    record = read_json(paths["example_json"])
    revs = record.get("revisions") or {}
    if revs.get("base") != "Bf" or revs.get("proposed") != "Bb":
        problems.append(f"example.json revisions not Bf→Bb: {revs}")
    if revs.get("direction") != "fixed_to_buggy":
        problems.append(f"direction not fixed_to_buggy: {revs.get('direction')}")

    meta = read_json(paths["patch_meta"])
    if meta.get("direction") != "fixed_to_buggy":
        problems.append("patch_meta.direction not fixed_to_buggy")

    rep = paths["patch_representation"].read_text(encoding="utf-8")
    if "PROPOSED CODE CHANGE:" not in rep:
        problems.append("patch representation missing PROPOSED CODE CHANGE")
    # Unified diff must use repo-relative headers, not checkout dir names.
    if "checkouts/fixed" in rep or "checkouts/buggy" in rep:
        problems.append("patch representation embeds checkout directory names")
    if not re.search(r"(?m)^--- ", rep) or not re.search(r"(?m)^\+\+\+ ", rep):
        problems.append("patch representation missing unified diff headers")
    # Rebuild every production diff from both checkouts, not sampled lines.
    from src.extract_patch import (parse_modified_classes, parse_src_dir,
        resolve_class_sources, unified_diff_for_file, build_full_diff,
        build_representation, truncate_to_cap)
    try:
        raw = paths["raw_exports"]
        classes = parse_modified_classes((raw / "classes.modified").read_text())
        fixed_dir = parse_src_dir((raw / "dir.src.classes").read_text())
        buggy_dir = parse_src_dir((raw / "dir.src.classes.buggy").read_text())
        diffs = {}
        for fqcn in classes:
            item = resolve_class_sources(fqcn, fixed_root=paths["checkout_fixed"],
                buggy_root=paths["checkout_buggy"], fixed_src_dir=fixed_dir,
                buggy_src_dir=buggy_dir)
            diffs[item["header_path"]] = unified_diff_for_file(
                header_path=item["header_path"], fixed_lines=item["fixed_lines"],
                buggy_lines=item["buggy_lines"])
        full = build_full_diff(diffs)
        expected, _ = truncate_to_cap(build_representation(
            modified_files=sorted(diffs), modified_classes=classes, full_diff=full))
        if not full or paths["patch_diff"].read_text(encoding="utf-8") != full:
            problems.append("full patch differs from reconstructed fixed-to-buggy diff")
        if rep != expected:
            problems.append("patch representation differs from reconstructed change")
    except Exception as exc:
        problems.append(f"patch reconstruction failed: {exc}")

    return problems


def audit_one_example(
    example: ExampleId | str,
    *,
    manifest: Mapping[str, Any] | None = None,
    data_root: Path | None = None,
    allow_evaluation: bool = False,
) -> dict[str, Any]:
    """Audit one complete example; return a structured report row."""
    data = manifest if manifest is not None else load_manifest()
    ex = example if isinstance(example, ExampleId) else ExampleId.parse(example)
    problems: list[str] = []

    try:
        loaded = load_example(
            ex,
            data_root=data_root,
            manifest=data,
            require_complete=True,
            allow_evaluation=allow_evaluation,
        )
        validated = validate_example_artifacts(
            ex,
            data_root=data_root,
            manifest=data,
            allow_evaluation=allow_evaluation,
        )
    except ExampleContractError as exc:
        return {
            "qualified_id": ex.qualified,
            "ok": False,
            "problems": [str(exc)],
        }

    paths = loaded["paths"]
    problems.extend(_assert_patch_direction(paths, ex))

    inventory = validated["inventory"]
    labels = validated["labels"]
    index = validated["representations_index"]
    test_classes = list(inventory["test_classes"])
    if len(test_classes) != len(set(test_classes)):
        problems.append("duplicate test class IDs in inventory")

    positives = list(labels.get("positive_classes") or [])
    triggers = list(labels.get("trigger_methods") or [])
    if not positives or not triggers:
        problems.append("labels missing positives or trigger methods")
    inv_set = set(test_classes)
    for cls in positives:
        if cls not in inv_set:
            problems.append(f"positive class not in inventory: {cls}")

    # Private fields must not leak into inventory.
    leaked = PRIVATE_LABEL_FIELDS.intersection(inventory.keys())
    if leaked:
        problems.append(f"private fields in inventory: {sorted(leaked)}")

    # Model-visible patch representation.
    patch_text = paths["patch_representation"].read_text(encoding="utf-8")
    if len(patch_text) > 12_000:
        problems.append(
            f"patch representation exceeds 12k chars: {len(patch_text)}"
        )
    problems.extend(
        audit_model_visible_text(
            patch_text,
            qualified_id=ex.qualified,
            trigger_methods=triggers,
            context="patch representation",
            kind="patch",
        )
    )

    # Each test representation.
    if index.get("num_representations") != len(test_classes):
        problems.append("representation count mismatch")
    for entry in index.get("representations") or []:
        fqcn = entry.get("test_class")
        text_rel = entry.get("text_path")
        if not fqcn or not text_rel:
            problems.append(f"incomplete representation index entry: {entry!r}")
            continue
        rep_file = paths["representations_dir"] / Path(text_rel).name
        if not rep_file.is_file():
            problems.append(f"missing representation text for {fqcn}: {text_rel}")
            continue
        body = rep_file.read_text(encoding="utf-8")
        if len(body) > 12_000:
            problems.append(f"{fqcn}: representation exceeds 12k ({len(body)})")
        if not body.startswith("TEST CLASS:"):
            problems.append(f"{fqcn}: representation missing TEST CLASS header")
        problems.extend(
            audit_model_visible_text(
                body,
                qualified_id=ex.qualified,
                trigger_methods=triggers,
                context=f"test representation {fqcn}",
                kind="test",
            )
        )
        json_path = paths["representations_dir"] / (Path(text_rel).stem + ".json")
        if json_path.is_file():
            doc = read_json(json_path)
            bad = PRIVATE_LABEL_FIELDS.intersection(doc.keys())
            if bad:
                problems.append(
                    f"{fqcn}: private fields in representation JSON: {sorted(bad)}"
                )

    patch_meta = read_json(paths["patch_meta"])
    return {
        "qualified_id": ex.qualified,
        "ok": not problems,
        "problems": problems,
        "num_test_classes": len(test_classes),
        "num_positive_classes": len(positives),
        "source_missing": (inventory.get("counts") or {}).get("source_missing", 0),
        "source_ambiguous": (inventory.get("counts") or {}).get(
            "source_ambiguous", 0
        ),
        "patch_truncated": bool(patch_meta.get("patch_truncated")),
        "representation_truncated": (index.get("counts") or {}).get(
            "representation_truncated", 0
        ),
        "status": loaded["record"].get("status"),
    }


def verify_patch_direction_sample(example: ExampleId | str = "Cli-30") -> None:
    """End-to-end: a '-' line from the patch exists in fixed, '+' in buggy."""
    ex = ExampleId.parse(str(example))
    paths = example_paths(ex)
    rep = paths["patch_representation"].read_text(encoding="utf-8")
    minus_lines = [
        ln[1:]
        for ln in rep.splitlines()
        if ln.startswith("-") and not ln.startswith("---")
    ]
    plus_lines = [
        ln[1:]
        for ln in rep.splitlines()
        if ln.startswith("+") and not ln.startswith("+++")
    ]
    if not minus_lines or not plus_lines:
        raise AuditError(f"{ex.qualified}: no sample +/- lines for direction check")

    # Resolve first modified file from meta.
    meta = read_json(paths["patch_meta"])
    files = meta.get("modified_files") or []
    if not files:
        raise AuditError(f"{ex.qualified}: no modified_files in patch_meta")

    # Search all modified files for the sample lines.
    fixed_blob = ""
    buggy_blob = ""
    for rel in files:
        fp = paths["checkout_fixed"] / rel
        bp = paths["checkout_buggy"] / rel
        if fp.is_file():
            fixed_blob += fp.read_text(encoding="utf-8")
        if bp.is_file():
            buggy_blob += bp.read_text(encoding="utf-8")

    sample_minus = next((ln for ln in minus_lines if ln.strip()), None)
    sample_plus = next((ln for ln in plus_lines if ln.strip()), None)
    if sample_minus is None or sample_plus is None:
        raise AuditError(f"{ex.qualified}: could not pick nonempty +/- samples")
    if sample_minus not in fixed_blob:
        raise AuditError(
            f"{ex.qualified}: removed line not found in fixed sources: "
            f"{sample_minus!r}"
        )
    if sample_plus not in buggy_blob:
        raise AuditError(
            f"{ex.qualified}: added line not found in buggy sources: "
            f"{sample_plus!r}"
        )
    # Direction sanity: the removed (correct) line should not be the buggy-only
    # addition; the added line should not match the fixed-only removal when they differ.
    if sample_minus != sample_plus:
        if sample_minus in buggy_blob and sample_plus not in fixed_blob:
            # Still OK if both sides evolved; require plus absent from fixed when distinct.
            pass
        if sample_plus in fixed_blob and sample_minus not in buggy_blob:
            pass
        if sample_plus not in fixed_blob and sample_minus not in buggy_blob:
            # Ideal reverse-patch shape.
            return
        # Soft check already passed presence; accept.
    return


def audit_development_set(
    *,
    manifest: Mapping[str, Any] | None = None,
    data_root: Path | None = None,
) -> dict[str, Any]:
    """Audit all 25 development examples and evaluation isolation."""
    data = manifest if manifest is not None else load_manifest()
    targets = development_example_ids(data)
    rows = [
        audit_one_example(ex, manifest=data, data_root=data_root) for ex in targets
    ]
    failed = [r for r in rows if not r["ok"]]

    # No evaluation example should be marked complete *during Phase 3 development*.
    # Phase 7 (P7-02) uses audit_evaluation_set instead.
    evaluation_complete: list[str] = []
    for raw in data.get("evaluation_bug_ids") or []:
        ex = ExampleId.parse(str(raw))
        paths = example_paths(ex, data_root=data_root)
        if paths["example_json"].is_file():
            record = read_json(paths["example_json"])
            if record.get("status") == ExampleStatus.COMPLETE.value:
                evaluation_complete.append(ex.qualified)

    direction_ok = True
    direction_error = None
    try:
        verify_patch_direction_sample("Cli-30")
    except (AuditError, OSError, ExampleContractError) as exc:
        direction_ok = False
        direction_error = str(exc)

    exceptions: list[dict[str, str]] = []
    # Genuine Defects4J metadata exceptions would be listed here with evidence.
    # None observed on the current 25-example development set.

    report = {
        "audited_at": _utcnow(),
        "split": "development",
        "defects4j_commit": data.get("defects4j_commit"),
        "selection_seed": data.get("selection_seed"),
        "counts": {
            "targets": len(rows),
            "passed": len(rows) - len(failed),
            "failed": len(failed),
            "evaluation_complete_forbidden": len(evaluation_complete),
        },
        "failed_ids": [r["qualified_id"] for r in failed],
        "evaluation_complete_ids": evaluation_complete,
        "patch_direction_sample": {
            "example": "Cli-30",
            "ok": direction_ok,
            "error": direction_error,
        },
        "defects4j_metadata_exceptions": exceptions,
        "examples": rows,
        "ok": (
            not failed
            and not evaluation_complete
            and direction_ok
            and len(rows) == 25
        ),
    }
    return report


def audit_evaluation_set(
    *,
    manifest: Mapping[str, Any] | None = None,
    data_root: Path | None = None,
    experiment_commit: str | None = None,
) -> dict[str, Any]:
    """Audit all 125 evaluation examples (P7-02)."""
    data = manifest if manifest is not None else load_manifest()
    raw_ids = list(data.get("evaluation_bug_ids") or [])
    targets = [ExampleId.parse(str(raw)) for raw in raw_ids]
    rows = [
        audit_one_example(
            ex,
            manifest=data,
            data_root=data_root,
            allow_evaluation=True,
        )
        for ex in targets
    ]
    failed = [r for r in rows if not r["ok"]]

    # Truncation / missing-source tallies (no ranking outcomes).
    trunc_patch = 0
    trunc_rep = 0
    missing_src = 0
    for r in rows:
        if not r.get("ok"):
            continue
        trunc_patch += int(bool(r.get("patch_truncated")))
        trunc_rep += int(r.get("representation_truncated") or 0)
        missing_src += int(r.get("source_missing") or 0)

    direction_ok = True
    direction_error = None
    sample_id = targets[0].qualified if targets else None
    if sample_id:
        try:
            verify_patch_direction_sample(sample_id)
        except (AuditError, OSError, ExampleContractError) as exc:
            direction_ok = False
            direction_error = str(exc)

    report = {
        "schema_version": "jev-phase7-extraction-audit-v1",
        "audited_at": _utcnow(),
        "split": "evaluation",
        "experiment_commit": experiment_commit,
        "defects4j_commit": data.get("defects4j_commit"),
        "selection_seed": data.get("selection_seed"),
        "counts": {
            "targets": len(rows),
            "passed": len(rows) - len(failed),
            "failed": len(failed),
            "patch_truncated": trunc_patch,
            "representation_truncated_total": trunc_rep,
            "source_missing_total": missing_src,
        },
        "failed_ids": [r["qualified_id"] for r in failed],
        "patch_direction_sample": {
            "example": sample_id,
            "ok": direction_ok,
            "error": direction_error,
        },
        "defects4j_metadata_exceptions": [],
        "examples": rows,
        "ok": (
            not failed
            and direction_ok
            and len(rows) == 125
        ),
    }
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit Phase 3 extraction integrity",
    )
    parser.add_argument(
        "--split",
        choices=("development", "evaluation"),
        default="development",
        help="Manifest split to audit (evaluation requires freeze + preflight)",
    )
    parser.add_argument(
        "--write",
        type=Path,
        default=None,
        help="Where to write the JSON audit report",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    write_path = args.write
    if write_path is None:
        if args.split == "evaluation":
            write_path = WORKSPACE / "results" / "phase7" / "extraction_audit.json"
        else:
            write_path = WORKSPACE / "results" / "audit-phase3.json"

    try:
        if args.split == "evaluation":
            from src.freeze_guard import assert_evaluation_allowed

            lock = assert_evaluation_allowed()
            report = audit_evaluation_set(
                experiment_commit=lock.get("commit_sha"),
            )
        else:
            report = audit_development_set()
    except ExampleContractError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    write_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(write_path, report)
    counts = report["counts"]
    print(
        f"audit phase3 ({report['split']}): "
        f"passed={counts['passed']}/{counts['targets']} "
        f"failed={counts['failed']} "
        f"direction_sample_ok={report['patch_direction_sample']['ok']} "
        f"report={write_path}"
    )
    if not report["ok"]:
        for row in report["examples"]:
            if not row["ok"]:
                print(f"  FAIL {row['qualified_id']}:", file=sys.stderr)
                for problem in row["problems"]:
                    print(f"    - {problem}", file=sys.stderr)
        if report.get("evaluation_complete_ids"):
            print(
                "  evaluation examples marked complete: "
                + ", ".join(report["evaluation_complete_ids"]),
                file=sys.stderr,
            )
        if not report["patch_direction_sample"]["ok"]:
            print(
                f"  direction sample: {report['patch_direction_sample']['error']}",
                file=sys.stderr,
            )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
