#!/usr/bin/env python3
"""Assemble evaluation rankings (P7-07): Random already separate; assemble Jev/GPT.

BM25 + Embedding artifacts already exist from P7-03/P7-04. This script:
- Assembles GPT-Nano for all 125 evaluation bugs (fail closed).
- Assembles Jev for bugs with complete shortlist scores.
- Records accepted A-001 WAF gaps without inventing Jev scores.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.assemble_rankings import (
    AssembleError,
    assemble_gpt_ranking,
    assemble_jev_ranking,
    verify_five_systems_present,
)
from src.example_contract import (
    WORKSPACE,
    ExampleId,
    atomic_write_json,
    load_manifest,
    require_manifest_membership,
)
from src.evaluation_preflight import append_execution_log, load_preflight
from src.freeze_guard import assert_evaluation_allowed
from src.gpt_ranker import primary_comparison_model
from src.random_baseline import evaluation_example_ids

# From results/phase7/jev_missing_diagnosis.json / docs/phase7-jev.md
ACCEPTED_JEV_GAPS: dict[str, str] = {
    "Jsoup-33": "org.jsoup.integration.UrlConnectTest",
    "Jsoup-54": "org.jsoup.integration.UrlConnectTest",
    "Jsoup-40": "org.jsoup.integration.UrlConnectTest",
    "Jsoup-47": "org.jsoup.integration.UrlConnectTest",
    "Jsoup-78": "org.jsoup.integration.ConnectTest",
    "Jsoup-81": "org.jsoup.integration.ConnectTest",
    "Jsoup-86": "org.jsoup.integration.ConnectTest",
    "Jsoup-69": "org.jsoup.integration.ConnectTest",
    "Jsoup-75": "org.jsoup.integration.ConnectTest",
    "Jsoup-85": "org.jsoup.integration.ConnectTest",
    "Jsoup-72": "org.jsoup.integration.ConnectTest",
    "Jsoup-84": "org.jsoup.integration.ConnectTest",
}


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def assemble_one(ex: ExampleId) -> dict[str, Any]:
    require_manifest_membership(ex, allow_evaluation=True)
    row: dict[str, Any] = {
        "qualified_id": ex.qualified,
        "assembled": [],
        "errors": [],
        "accepted_jev_gap": None,
    }
    gap_cls = ACCEPTED_JEV_GAPS.get(ex.qualified)
    if gap_cls:
        row["accepted_jev_gap"] = {
            "test_class": gap_cls,
            "reason": "OpenRouter WAF A-001 on file://etc/passwd",
        }
    else:
        try:
            jev = assemble_jev_ranking(ex)
            row["assembled"].append(
                {
                    "method": jev.method,
                    "path": str(jev.path.relative_to(WORKSPACE)),
                    "N": jev.document["N"],
                    "K": jev.document["K"],
                }
            )
        except Exception as exc:  # noqa: BLE001
            row["errors"].append({"method": "Jev", "error": str(exc)})

    try:
        gpt = assemble_gpt_ranking(ex, model=primary_comparison_model())
        row["assembled"].append(
            {
                "method": gpt.method,
                "path": str(gpt.path.relative_to(WORKSPACE)),
                "N": gpt.document["N"],
                "K": gpt.document["K"],
            }
        )
    except Exception as exc:  # noqa: BLE001
        row["errors"].append({"method": "GPT-Nano", "error": str(exc)})

    require_sem = ("GPT-Nano",) if gap_cls else ("Jev", "GPT-Nano")
    five = verify_five_systems_present(ex, require_semantic=require_sem)
    if gap_cls:
        five["Jev"] = False  # intentionally absent
        five["Jev_accepted_gap"] = True
    row["five_systems"] = five
    row["ok"] = not row["errors"] and all(
        five.get(k) for k in ("BM25", "Embedding", "Random", "GPT-Nano")
    ) and (five.get("Jev") or bool(gap_cls))
    return row


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", nargs="+", default=None)
    args = parser.parse_args(argv)

    lock = assert_evaluation_allowed()
    manifest = load_manifest()
    targets = list(evaluation_example_ids(manifest))
    if args.only:
        wanted = {ExampleId.parse(x).qualified for x in args.only}
        targets = [ex for ex in targets if ex.qualified in wanted]

    rows = []
    for ex in targets:
        print(f"==> {ex.qualified}", flush=True)
        row = assemble_one(ex)
        rows.append(row)
        status = "ok" if row["ok"] else "FAIL"
        gap = " gap" if row.get("accepted_jev_gap") else ""
        print(
            f"    {status}{gap} assembled={len(row['assembled'])} "
            f"errors={len(row['errors'])}",
            flush=True,
        )
        for err in row["errors"]:
            print(f"      ! {err['method']}: {err['error']}", file=sys.stderr)

    failed = [r for r in rows if not r["ok"]]
    pre = load_preflight() or {}
    report = {
        "schema_version": "jev-phase7-assembly-v1",
        "generated_at": _utcnow(),
        "split": "evaluation",
        "experiment_commit": pre.get("experiment_commit") or lock.get("commit_sha"),
        "run_id": pre.get("run_id"),
        "counts": {
            "targets": len(rows),
            "passed": len(rows) - len(failed),
            "failed": len(failed),
            "jev_assembled": sum(
                1
                for r in rows
                if any(a.get("method") == "Jev" for a in r.get("assembled") or [])
            ),
            "gpt_assembled": sum(
                1
                for r in rows
                if any(a.get("method") == "GPT-Nano" for a in r.get("assembled") or [])
            ),
            "accepted_jev_gaps": sum(1 for r in rows if r.get("accepted_jev_gap")),
        },
        "accepted_jev_gaps": [
            {
                "qualified_id": r["qualified_id"],
                **(r.get("accepted_jev_gap") or {}),
            }
            for r in rows
            if r.get("accepted_jev_gap")
        ],
        "failed_ids": [r["qualified_id"] for r in failed],
        "bugs": rows,
        "ok": not failed and len(rows) == 125,
        "notes": (
            "Jev omitted (not invented) for 12 A-001 WAF bugs; GPT/BM25/Embedding/"
            "Random required for all 125."
        ),
    }
    out = WORKSPACE / "results" / "phase7" / "assembly.json"
    atomic_write_json(out, report)
    append_execution_log(
        {
            "event": "assemble_evaluation",
            "ok": report["ok"],
            "passed": report["counts"]["passed"],
            "failed": report["counts"]["failed"],
            "accepted_jev_gaps": report["counts"]["accepted_jev_gaps"],
            "experiment_commit": report["experiment_commit"],
            "run_id": report.get("run_id"),
        }
    )
    print(
        f"assembly evaluation: passed={report['counts']['passed']}/"
        f"{report['counts']['targets']} "
        f"jev={report['counts']['jev_assembled']} "
        f"gpt={report['counts']['gpt_assembled']} "
        f"gaps={report['counts']['accepted_jev_gaps']} "
        f"report={out}"
    )
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
