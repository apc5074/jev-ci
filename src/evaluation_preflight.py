"""Phase 7 / P7-01 — evaluation preflight and run registry.

Verifies the freeze tag, locked config hashes, manifest split, empty evaluation
namespace, credentials/provider pin, and spend ceiling before any evaluation
extraction or scoring. Creates a run ID and append-only execution log.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.example_contract import WORKSPACE, atomic_write_json, load_manifest, read_json
from src.experiment_config import load_experiment_config
from src.freeze_guard import (
    REQUIRED_TAG,
    assert_evaluation_allowed,
    freeze_lock_summary,
)
from src.select_bugs import ManifestError, verify_manifest_integrity

PHASE7_DIR = WORKSPACE / "results" / "phase7"
PREFLIGHT_JSON = PHASE7_DIR / "preflight.json"
PREFLIGHT_MD = WORKSPACE / "results" / "phase7" / "preflight.md"
RUN_JSON = PHASE7_DIR / "run.json"
EXECUTION_LOG = PHASE7_DIR / "execution.log.jsonl"

# Files that must match the freeze tag blob (methodological lock).
FROZEN_HASH_PATHS = (
    "prompts/jev/v1.json",
    "prompts/gpt/v1.json",
    "results/phase6/experiment.json",
    "results/pricing_snapshot.json",
    "data/manifest.json",
)

# Documentation may drift after tagging (tag rename notes); record only.
DOC_HASH_PATHS = (
    "experiment.yaml",
    "README.md",
)

EXPECTED_D4J_COMMIT = "6d54320e0db5a357f9ab38a8e4d2e5aead7e1c09"
EXPECTED_D4J_VERSION = "3.0.1"
EXPECTED_PROJECT_ORDER = ["Cli", "Lang", "Math", "Jsoup", "JacksonDatabind"]
PINNED_JEV_PREFIX = "typesafe/jev-1.13"
OBSERVED_JEV_DEV = "typesafe/jev-1.13-20260917"


class PreflightError(Exception):
    """Evaluation preflight failed; runners must refuse to start."""


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    return _sha256_bytes(path.read_bytes())


def _git(*args: str) -> tuple[int, str, str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(WORKSPACE if (WORKSPACE / ".git").exists() else _REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def _git_show_hash(tag: str, relpath: str) -> str | None:
    code, out, _ = _git("show", f"{tag}:{relpath}")
    if code != 0:
        # Annotated tag peel sometimes needs ^{}
        code, out, _ = _git("show", f"{tag}^{{commit}}:{relpath}")
        if code != 0:
            return None
        # git show of binary via text may be wrong; use cat-file
    code2, blob, _ = _git("cat-file", "-p", f"{tag}:{relpath}")
    if code2 != 0:
        code2, blob, _ = _git(
            "cat-file", "-p", f"{tag}^{{commit}}:{relpath}"
        )
    if code2 != 0:
        return None
    # Prefer raw bytes via subprocess for hash
    root = WORKSPACE if (WORKSPACE / ".git").exists() else _REPO_ROOT
    proc = subprocess.run(
        ["git", "show", f"{tag}:{relpath}"],
        cwd=str(root),
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        proc = subprocess.run(
            ["git", "show", f"{tag}^{{commit}}:{relpath}"],
            cwd=str(root),
            capture_output=True,
            check=False,
        )
    if proc.returncode != 0:
        return None
    return _sha256_bytes(proc.stdout)


def load_dotenv_if_present(*, path: Path | None = None) -> list[str]:
    """Load KEY=VAL from .env into os.environ without overriding existing."""
    target = path or (WORKSPACE / ".env")
    if not target.is_file():
        alt = _REPO_ROOT / ".env"
        target = alt if alt.is_file() else target
    loaded: list[str] = []
    if not target.is_file():
        return loaded
    for raw in target.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val
            loaded.append(key)
    return loaded


def append_execution_log(event: Mapping[str, Any]) -> None:
    PHASE7_DIR.mkdir(parents=True, exist_ok=True)
    row = {"ts": _utcnow(), **dict(event)}
    with EXECUTION_LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def check_freeze() -> dict[str, Any]:
    summary = freeze_lock_summary()
    errors: list[str] = []
    try:
        lock = assert_evaluation_allowed()
    except Exception as exc:  # noqa: BLE001 — surface as preflight error
        return {
            "ok": False,
            "freeze_lock": summary,
            "errors": [str(exc)],
        }

    code, tag_commit, err = _git("rev-parse", f"{REQUIRED_TAG}^{{commit}}")
    if code != 0:
        errors.append(f"git tag {REQUIRED_TAG} missing: {err}")
        tag_commit = None
    elif tag_commit != lock.get("commit_sha"):
        errors.append(
            f"freeze_lock.commit_sha={lock.get('commit_sha')!r} "
            f"!= tag commit {tag_commit!r}"
        )

    return {
        "ok": not errors,
        "tag": REQUIRED_TAG,
        "commit_sha": lock.get("commit_sha"),
        "tag_commit": tag_commit,
        "freeze_lock": summary,
        "errors": errors,
    }


def check_frozen_hashes(*, tag: str) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for rel in FROZEN_HASH_PATHS:
        path = WORKSPACE / rel
        wt = _sha256_file(path)
        tagged = _git_show_hash(tag, rel)
        ok = bool(wt and tagged and wt == tagged)
        rows.append(
            {
                "path": rel,
                "working_tree_sha256": wt,
                "tag_sha256": tagged,
                "match": ok,
            }
        )
        if not ok:
            errors.append(f"hash mismatch or missing: {rel}")

    doc_rows: list[dict[str, Any]] = []
    for rel in DOC_HASH_PATHS:
        path = WORKSPACE / rel
        wt = _sha256_file(path)
        tagged = _git_show_hash(tag, rel)
        doc_rows.append(
            {
                "path": rel,
                "working_tree_sha256": wt,
                "tag_sha256": tagged,
                "match": bool(wt and tagged and wt == tagged),
                "note": "documentation; drift after tag is recorded, not fatal",
            }
        )

    return {
        "ok": not errors,
        "frozen": rows,
        "documentation": doc_rows,
        "errors": errors,
    }


def check_manifest_and_config() -> dict[str, Any]:
    manifest = load_manifest()
    errors: list[str] = []
    try:
        verify_manifest_integrity(manifest)
        manifest_ok = True
    except ManifestError as exc:
        manifest_ok = False
        errors.append(f"manifest integrity: {exc}")

    eval_ids = list(manifest.get("evaluation_bug_ids") or [])
    dev_ids = list(manifest.get("development_bug_ids") or [])
    if len(eval_ids) != 125:
        errors.append(f"expected 125 evaluation IDs, got {len(eval_ids)}")
    if len(dev_ids) != 25:
        errors.append(f"expected 25 development IDs, got {len(dev_ids)}")
    if set(eval_ids) & set(dev_ids):
        errors.append("development/evaluation ID overlap")
    if manifest.get("defects4j_commit") != EXPECTED_D4J_COMMIT:
        errors.append(
            f"defects4j_commit mismatch: {manifest.get('defects4j_commit')}"
        )
    if manifest.get("defects4j_version") != EXPECTED_D4J_VERSION:
        errors.append(
            f"defects4j_version mismatch: {manifest.get('defects4j_version')}"
        )
    if list(manifest.get("project_order") or []) != EXPECTED_PROJECT_ORDER:
        errors.append(f"project_order mismatch: {manifest.get('project_order')}")

    try:
        cfg = load_experiment_config()
        cfg_ok = True
        systems = cfg.get("systems")
    except Exception as exc:  # noqa: BLE001
        cfg = {}
        cfg_ok = False
        systems = None
        errors.append(f"experiment config: {exc}")

    env_path = WORKSPACE / "results" / "environment.json"
    env = read_json(env_path) if env_path.is_file() else None
    env_ok = bool(
        env
        and env.get("defects4j_commit") == EXPECTED_D4J_COMMIT
        and env.get("defects4j_version") == EXPECTED_D4J_VERSION
    )
    if not env_ok:
        errors.append(
            "results/environment.json missing or Defects4J pin mismatch "
            "(re-run scripts/check_environment.py in the Phase 1 container)"
        )

    return {
        "ok": not errors and manifest_ok and cfg_ok and env_ok,
        "evaluation_count": len(eval_ids),
        "development_count": len(dev_ids),
        "evaluation_bug_ids": eval_ids,
        "project_order": manifest.get("project_order"),
        "defects4j_commit": manifest.get("defects4j_commit"),
        "defects4j_version": manifest.get("defects4j_version"),
        "systems": systems,
        "environment_record_ok": env_ok,
        "errors": errors,
    }


def _slug(qid: str) -> str:
    return qid.replace("-", "_")


def check_evaluation_namespace_empty(eval_ids: list[str]) -> dict[str, Any]:
    hits: list[str] = []
    for qid in eval_ids:
        s = _slug(qid)
        for base in (
            WORKSPACE / "data" / "bugs" / s,
            WORKSPACE / "data" / "patches" / s,
            WORKSPACE / "data" / "tests" / s,
            WORKSPACE / "data" / "candidates" / f"{s}.json",
            WORKSPACE / "results" / "rankings" / f"{s}.json",
            WORKSPACE / "results" / "embeddings" / f"{s}.json",
            WORKSPACE / "results" / "random" / f"{s}.json",
        ):
            if base.exists():
                hits.append(str(base.relative_to(WORKSPACE)))
        sem = WORKSPACE / "results" / "semantic"
        if sem.is_dir():
            for p in sem.rglob("*"):
                if not p.is_file():
                    continue
                if p.stem == s or f"/{s}/" in str(p).replace("\\", "/"):
                    hits.append(str(p.relative_to(WORKSPACE)))
    return {
        "ok": len(hits) == 0,
        "hits": hits[:50],
        "hit_count": len(hits),
        "errors": (
            [f"evaluation artifacts already present ({len(hits)}); refuse start"]
            if hits
            else []
        ),
    }


def estimate_spend() -> dict[str, Any]:
    pricing = read_json(WORKSPACE / "results" / "pricing_snapshot.json")
    usage_path = WORKSPACE / "results" / "phase5_usage_report.json"
    usage = read_json(usage_path) if usage_path.is_file() else {}
    by_kind = ((usage.get("usage_ledger") or {}).get("by_kind")) or {}

    # Scale development measured tokens 25 → 125.
    scale = 125 / 25
    measured: dict[str, Any] = {}
    for kind in ("jev", "gpt", "embedding"):
        row = by_kind.get(kind) or {}
        inp = float(row.get("input_tokens") or 0) * scale
        out = float(row.get("output_tokens") or 0) * scale
        measured[kind] = {
            "scaled_input_tokens": inp,
            "scaled_output_tokens": out,
            "development_rows": row.get("rows"),
        }

    jev_route = ((pricing.get("jev") or {}).get("routes") or {}).get("openrouter") or {}
    gpt_rates = ((pricing.get("openai") or {}).get("gpt") or {})
    emb_rates = ((pricing.get("openai") or {}).get("embedding") or {})

    def _cost(tokens_in: float, tokens_out: float, rates: Mapping[str, Any]) -> float:
        pin = float(rates.get("input_usd_per_mtok") or 0)
        pout = float(rates.get("output_usd_per_mtok") or 0)
        fee = float(rates.get("platform_fee_rate") or 0)
        base = (tokens_in / 1e6) * pin + (tokens_out / 1e6) * pout
        return base * (1.0 + fee)

    jev_usd = _cost(
        measured["jev"]["scaled_input_tokens"],
        measured["jev"]["scaled_output_tokens"],
        jev_route,
    )
    gpt_usd = _cost(
        measured["gpt"]["scaled_input_tokens"],
        measured["gpt"]["scaled_output_tokens"],
        {
            "input_usd_per_mtok": gpt_rates.get("input_usd_per_mtok"),
            "output_usd_per_mtok": gpt_rates.get("output_usd_per_mtok"),
            "platform_fee_rate": 0.055,  # OpenRouter path used in development
        },
    )
    emb_usd = _cost(
        measured["embedding"]["scaled_input_tokens"],
        0.0,
        {
            "input_usd_per_mtok": emb_rates.get("input_usd_per_mtok"),
            "output_usd_per_mtok": 0.0,
            "platform_fee_rate": 0.055,
        },
    )
    snapshot_eval = (
        ((pricing.get("workload_estimates") or {}).get("evaluation") or {}).get(
            "openrouter"
        )
        or {}
    )
    total_measured = jev_usd + gpt_usd + emb_usd
    # Operational ceiling: 2× measured-scale total, floor at snapshot Jev estimate.
    ceiling = max(total_measured * 2.0, float(snapshot_eval.get("effective_cash_if_prepaid_credits_usd") or 0) * 3.0, 5.0)
    ceiling = round(ceiling, 2)

    return {
        "ok": True,
        "basis": "phase5_usage_scaled_x5_plus_pricing_snapshot",
        "measured_scale": measured,
        "estimated_usd": {
            "jev_openrouter": round(jev_usd, 4),
            "gpt_nano_openrouter": round(gpt_usd, 4),
            "embedding_openrouter": round(emb_usd, 4),
            "total": round(total_measured, 4),
        },
        "pricing_snapshot_jev_openrouter_eval": snapshot_eval,
        "spend_ceiling_usd": ceiling,
        "schedule": {
            "order": [
                "prepare_dataset",
                "run_candidates",
                "run_embeddings",
                "run_random_baseline",
                "run_jev",
                "run_gpt",
                "assemble_seal",
            ],
            "max_concurrency": 16,
            "note": "Operational guard only; does not change K, models, or sample.",
        },
    }


def check_credentials_and_providers(*, probe: bool) -> dict[str, Any]:
    loaded = load_dotenv_if_present()
    keys = {
        "OPENROUTER_API_KEY": bool(os.environ.get("OPENROUTER_API_KEY", "").strip()),
        "OPENAI_API_KEY": bool(os.environ.get("OPENAI_API_KEY", "").strip()),
        "TYPESAFE_API_KEY": bool(os.environ.get("TYPESAFE_API_KEY", "").strip()),
    }
    errors: list[str] = []
    if not keys["OPENROUTER_API_KEY"]:
        errors.append("OPENROUTER_API_KEY missing (required for Jev/GPT/embeddings)")

    probe_result: dict[str, Any] | None = None
    if probe and keys["OPENROUTER_API_KEY"]:
        from src.jev_providers import probe_openrouter

        probe_result = probe_openrouter(
            api_key=os.environ["OPENROUTER_API_KEY"].strip()
        )
        observed = (probe_result or {}).get("response_model") or (
            probe_result or {}
        ).get("model")
        # jev_providers validated fields
        pinned_ok = (probe_result or {}).get("response_model_pinned_ok")
        if not (probe_result or {}).get("ok"):
            errors.append(
                f"OpenRouter Jev probe failed: {(probe_result or {}).get('error')}"
            )
        elif pinned_ok is False:
            errors.append(
                f"Jev underlying model not pinned to {PINNED_JEV_PREFIX}: {observed!r}"
            )
        elif observed and not str(observed).startswith("typesafe/jev-1.13"):
            errors.append(f"unexpected Jev model id: {observed!r}")

    return {
        "ok": not errors,
        "dotenv_keys_loaded": loaded,
        "api_keys_present": keys,
        "probe_ran": bool(probe_result is not None),
        "jev_probe": (
            {
                "ok": (probe_result or {}).get("ok"),
                "response_model": (probe_result or {}).get("response_model")
                or (probe_result or {}).get("model"),
                "response_model_pinned_ok": (probe_result or {}).get(
                    "response_model_pinned_ok"
                ),
                "error": (probe_result or {}).get("error"),
                "expected_prefix": PINNED_JEV_PREFIX,
                "development_observed": OBSERVED_JEV_DEV,
            }
            if probe_result is not None
            else None
        ),
        "errors": errors,
    }


def artifact_layout(*, run_id: str, experiment_commit: str) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "experiment_commit": experiment_commit,
        "phase7_root": "results/phase7",
        "preflight": "results/phase7/preflight.json",
        "execution_log": "results/phase7/execution.log.jsonl",
        "run_record": "results/phase7/run.json",
        "completed_artifacts": "results/phase7/artifacts/",
        "failed_attempts": "results/phase7/failures/",
        "final_audit": "results/phase7/audit.json",
        "development_protection": (
            "Evaluation writers must only touch evaluation qualified IDs; "
            "development paths under data/ and results/ must not be overwritten."
        ),
        "evaluation_data": {
            "bugs": "data/bugs/<Project>_<id>/",
            "patches": "data/patches/<Project>_<id>/",
            "tests": "data/tests/<Project>_<id>/",
            "candidates": "data/candidates/<Project>_<id>.json",
            "rankings": "results/rankings/<Project>_<id>.json",
        },
    }


def load_preflight(*, path: Path | None = None) -> dict[str, Any] | None:
    target = path or PREFLIGHT_JSON
    if not target.is_file():
        return None
    return read_json(target)


def assert_evaluation_run_ready(*, path: Path | None = None) -> dict[str, Any]:
    """Refuse evaluation runners unless freeze + passing preflight match."""
    lock = assert_evaluation_allowed()
    doc = load_preflight(path=path)
    if doc is None:
        raise PreflightError(
            "evaluation blocked: missing results/phase7/preflight.json "
            "(run scripts/run_evaluation_preflight.py)"
        )
    if not doc.get("ok"):
        raise PreflightError(
            "evaluation blocked: preflight did not pass; see "
            "results/phase7/preflight.json"
        )
    if doc.get("experiment_commit") != lock.get("commit_sha"):
        raise PreflightError(
            "evaluation blocked: preflight experiment_commit "
            f"{doc.get('experiment_commit')!r} != freeze_lock "
            f"{lock.get('commit_sha')!r}"
        )
    if doc.get("tag") != REQUIRED_TAG:
        raise PreflightError(
            f"evaluation blocked: preflight tag {doc.get('tag')!r} "
            f"!= {REQUIRED_TAG!r}"
        )
    return doc


def run_preflight(*, probe: bool = True) -> dict[str, Any]:
    PHASE7_DIR.mkdir(parents=True, exist_ok=True)
    generated_at = _utcnow()
    run_id = f"eval-v1-{generated_at.replace(':', '').replace('-', '')}"

    freeze = check_freeze()
    tag = REQUIRED_TAG
    hashes = check_frozen_hashes(tag=tag) if freeze.get("ok") else {
        "ok": False,
        "frozen": [],
        "documentation": [],
        "errors": ["skipped: freeze check failed"],
    }
    manifest = check_manifest_and_config()
    namespace = check_evaluation_namespace_empty(
        list(manifest.get("evaluation_bug_ids") or [])
    )
    spend = estimate_spend()
    providers = check_credentials_and_providers(probe=probe)

    checks = {
        "freeze": freeze,
        "frozen_hashes": hashes,
        "manifest_config": manifest,
        "evaluation_namespace": namespace,
        "spend": spend,
        "providers": providers,
    }
    ok = all(c.get("ok") for c in checks.values())
    experiment_commit = freeze.get("commit_sha")
    layout = artifact_layout(
        run_id=run_id, experiment_commit=str(experiment_commit or "")
    )

    report: dict[str, Any] = {
        "schema_version": "jev-phase7-preflight-v1",
        "generated_at": generated_at,
        "ok": ok,
        "run_id": run_id,
        "tag": tag,
        "experiment_commit": experiment_commit,
        "evaluation_queued": int(manifest.get("evaluation_count") or 0),
        "spend_ceiling_usd": spend.get("spend_ceiling_usd"),
        "checks": checks,
        "artifact_layout": layout,
        "open_items": [
            {
                "id": "A-001",
                "note": (
                    "Jsoup-70 ConnectTest OpenRouter WAF on file://etc/passwd; "
                    "must resolve or formally deviate before relying on eval Jev "
                    "completeness if evaluation hits the same pattern."
                ),
            }
        ],
    }

    # Write run record + human summary only when structuring artifacts; always
    # write machine preflight so failures are inspectable (no eval bug outputs).
    atomic_write_json(PREFLIGHT_JSON, report)
    atomic_write_json(
        RUN_JSON,
        {
            "schema_version": "jev-phase7-run-v1",
            "run_id": run_id,
            "created_at": generated_at,
            "ok": ok,
            "tag": tag,
            "experiment_commit": experiment_commit,
            "spend_ceiling_usd": spend.get("spend_ceiling_usd"),
            "execution_log": str(EXECUTION_LOG.relative_to(WORKSPACE)),
            "preflight": str(PREFLIGHT_JSON.relative_to(WORKSPACE)),
            "evaluation_bug_count": report["evaluation_queued"],
        },
    )
    _write_preflight_md(report)
    append_execution_log(
        {
            "event": "preflight",
            "run_id": run_id,
            "ok": ok,
            "experiment_commit": experiment_commit,
            "evaluation_queued": report["evaluation_queued"],
            "spend_ceiling_usd": spend.get("spend_ceiling_usd"),
        }
    )
    return report


def _write_preflight_md(report: dict[str, Any]) -> None:
    checks = report["checks"]
    lines = [
        "# Phase 7 evaluation preflight (P7-01)",
        "",
        f"Generated: `{report['generated_at']}`",
        "",
        f"**Overall: `{'PASS' if report['ok'] else 'FAIL'}`**",
        "",
        f"- Run ID: `{report['run_id']}`",
        f"- Freeze tag: `{report['tag']}`",
        f"- `experiment_commit`: `{report['experiment_commit']}`",
        f"- Evaluation IDs queued: **{report['evaluation_queued']}**",
        f"- Spend ceiling (operational): **${report['spend_ceiling_usd']}**",
        "",
        "## Checks",
        "",
    ]
    for name, block in checks.items():
        status = "ok" if block.get("ok") else "FAIL"
        lines.append(f"- {name}: **{status}**")
        for err in block.get("errors") or []:
            lines.append(f"  - {err}")
    lines.extend(
        [
            "",
            "## Artifact layout",
            "",
            f"- Execution log: `{report['artifact_layout']['execution_log']}`",
            f"- Failures: `{report['artifact_layout']['failed_attempts']}`",
            f"- Final audit: `{report['artifact_layout']['final_audit']}`",
            "",
            "Development outputs must not be overwritten; evaluation uses the "
            "125 evaluation qualified IDs only.",
            "",
            "Machine record: `results/phase7/preflight.json`",
            "",
        ]
    )
    PREFLIGHT_MD.parent.mkdir(parents=True, exist_ok=True)
    PREFLIGHT_MD.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run Phase 7 evaluation preflight (P7-01)."
    )
    parser.add_argument(
        "--no-probe",
        action="store_true",
        help="Skip live OpenRouter Jev probe (credentials presence still checked).",
    )
    args = parser.parse_args(argv)
    report = run_preflight(probe=not args.no_probe)
    status = "PASS" if report["ok"] else "FAIL"
    print(
        f"evaluation preflight: {status} "
        f"queued={report['evaluation_queued']} "
        f"run_id={report['run_id']} "
        f"commit={report['experiment_commit']}"
    )
    print(f"wrote: {PREFLIGHT_JSON.relative_to(WORKSPACE)}")
    print(f"wrote: {PREFLIGHT_MD.relative_to(WORKSPACE)}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
