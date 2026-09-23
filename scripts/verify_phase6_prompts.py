#!/usr/bin/env python3
"""Offline P6-03 prompt/cache verification; reads development artifacts only."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.embeddings import load_patch_representation_text, load_test_representation_texts
from src.example_contract import ExampleId
from src.gpt_ranker import build_gpt_messages, primary_comparison_model
from src.semantic_cache import (
    GPT_PROMPT_VERSION, JEV_PROMPT_VERSION, build_gpt_question, build_jev_question,
    build_jev_state, load_score_cache, semantic_cache_key,
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prompt_documents() -> dict[str, dict]:
    return {
        "prompts/jev/v1.json": {
            "preregistration_version": "v1", "cache_prompt_version": JEV_PROMPT_VERSION,
            "semantic_revision_count": 0, "question": build_jev_question(),
            "state_fields": ["code_change", "candidate_test"],
        },
        "prompts/gpt/v1.json": {
            "preregistration_version": "v1", "cache_prompt_version": GPT_PROMPT_VERSION,
            "question": build_gpt_question(),
            "messages_template": build_gpt_messages(
                code_change="<CODE_CHANGE>", candidate_test="<CANDIDATE_TEST>"),
            "template_note": "Replace placeholders with exact saved strings using build_gpt_messages; do not strip or reformat.",
        },
    }


def inventory() -> dict:
    manifest = json.loads((ROOT / "data/manifest.json").read_text())
    baseline = json.loads((ROOT / "results/phase6/development_baseline.json").read_text())
    ids = manifest["development_bug_ids"]
    if len(ids) != 25 or set(ids) != {b["qualified_id"] for b in baseline["bugs"]}:
        raise ValueError("development manifest/baseline mismatch")
    allowed = {(g["qualified_id"], g["test_class"], g["system"])
               for g in baseline["accepted_gaps"]}
    if allowed != {("Jsoup-70", "org.jsoup.integration.ConnectTest", "Jev")}:
        raise ValueError("unexpected accepted gap list; requires explicit review")
    identity = baseline["frozen_for_baseline"]
    systems = [
        ("Jev", "jev", identity["jev_provider"], identity["jev_model_id"],
         JEV_PROMPT_VERSION, build_jev_question()),
        ("GPT-Nano", "gpt", "openrouter", primary_comparison_model().canonical_model_id,
         GPT_PROMPT_VERSION, build_gpt_question()),
    ]
    rows, missing = [], []
    for qualified in ids:
        ex = ExampleId.parse(qualified)
        candidates_path = ROOT / "data/candidates" / f"{ex.slug}.json"
        candidates = json.loads(candidates_path.read_text())
        if candidates["qualified_id"] != qualified or candidates["split"] != "development":
            raise ValueError("candidate identity/split mismatch")
        classes = candidates["candidate_ids"]
        if len(classes) != candidates["K"] or len(set(classes)) != len(classes):
            raise ValueError("invalid shortlist")
        patch = load_patch_representation_text(ex, data_root=ROOT / "data")
        texts = dict(load_test_representation_texts(ex, data_root=ROOT / "data"))
        row = {"qualified_id": qualified, "K": len(classes),
               "candidate_file_sha256": digest(candidates_path), "systems": {}}
        for name, kind, provider, model, version, question in systems:
            entries = []
            for cls in classes:
                key = semantic_cache_key(provider=provider, model_id=model,
                                         prompt_version=version, question=question,
                                         state=build_jev_state(code_change=patch, candidate_test=texts[cls]))
                entry = load_score_cache(key, kind=kind, cache_root=ROOT / "cache")
                if entry is None:
                    if (qualified, cls, name) not in allowed:
                        raise ValueError(f"unaccepted missing cache: {qualified} / {name} / {cls}")
                    missing.append({"qualified_id": qualified, "test_class": cls,
                                    "system": name, "cache_key": key,
                                    "reason": "A-001: previously accepted OpenRouter WAF HTTP 403"})
                    continue
                if not entry.get("observed_model_id"):
                    raise ValueError(f"missing observed model: {key}")
                path = ROOT / "cache" / kind / f"{key}.json"
                entries.append({"test_class": cls, "cache_key": key, "sha256": digest(path),
                                "observed_model_id": entry["observed_model_id"]})
            row["systems"][name] = {"present": len(entries), "expected": len(classes),
                                    "entries": entries}
        rows.append(row)
    return {"development_bug_count": len(rows), "bugs": rows, "accepted_missing": missing,
            "all_scores_complete": not missing,
            "complete_except_previously_accepted_gaps": True,
            "evaluation_artifacts_read": False}


def main() -> int:
    record = json.loads((ROOT / "results/phase6/prompt_decision.json").read_text())
    for relative, expected in prompt_documents().items():
        path = ROOT / relative
        if json.loads(path.read_text()) != expected:
            raise ValueError(f"frozen prompt differs from runtime: {relative}")
        if record["artifact_sha256"][relative] != digest(path):
            raise ValueError(f"prompt hash mismatch: {relative}")
    for relative, expected_hash in record["evidence_sha256"].items():
        if digest(ROOT / relative) != expected_hash:
            raise ValueError(f"review evidence changed: {relative}")
    actual = inventory()
    saved_path = ROOT / "results/phase6/final_prompt_cache_inventory.json"
    if digest(saved_path) != record["artifact_sha256"][str(saved_path.relative_to(ROOT))]:
        raise ValueError("cache inventory hash mismatch")
    if json.loads(saved_path.read_text()) != actual:
        raise ValueError("cache inventory changed; review required")
    if record["semantic_revision_count"] != 0 or record["decision"] != "retain_original":
        raise ValueError("unexpected prompt decision")
    print(f"P6-03 verified: retained v1, zero revisions; {len(actual['bugs'])} development bugs")
    for name in ("Jev", "GPT-Nano"):
        present = sum(b["systems"][name]["present"] for b in actual["bugs"])
        expected = sum(b["systems"][name]["expected"] for b in actual["bugs"])
        print(f"  {name}: {present}/{expected} exact-input cache references")
    print(f"  Accepted gaps: {len(actual['accepted_missing'])}; evaluation freeze not authorized")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
