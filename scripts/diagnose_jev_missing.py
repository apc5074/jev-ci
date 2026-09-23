#!/usr/bin/env python3
"""Diagnose missing Jev evaluation scores."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.candidates import load_candidates
from src.embeddings import load_patch_representation_text, load_test_representation_texts
from src.example_contract import ExampleId, WORKSPACE, read_json
from src.jev_ranker import JEV_PROMPT_VERSION, build_jev_question, load_selected_route
from src.semantic_cache import (
    build_jev_state,
    cache_path_for,
    load_score_cache,
    semantic_cache_key,
)


def main() -> int:
    audit = read_json(WORKSPACE / "results" / "phase7" / "jev_audit.json")
    route = load_selected_route()
    question = build_jev_question()
    rows = []
    for ex_row in audit["examples"]:
        if ex_row.get("ok"):
            continue
        ex = ExampleId.parse(ex_row["qualified_id"])
        ids = load_candidates(ex)["candidate_ids"]
        patch = load_patch_representation_text(ex)
        pairs = dict(load_test_representation_texts(ex))
        for tc in ids:
            state = build_jev_state(code_change=patch, candidate_test=pairs[tc])
            key = semantic_cache_key(
                provider=route.provider,
                model_id=route.request_model,
                prompt_version=JEV_PROMPT_VERSION,
                state=state,
                question=question,
            )
            if load_score_cache(key, kind="jev") is not None:
                continue
            fail_path = cache_path_for(kind="failure", cache_key=key)
            fail = read_json(fail_path) if fail_path.is_file() else {}
            text = pairs[tc]
            rows.append(
                {
                    "qualified_id": ex.qualified,
                    "test_class": tc,
                    "has_file_passwd": "file://etc/passwd" in text.lower(),
                    "failure_keys": sorted(fail.keys())[:20],
                    "error": fail.get("error")
                    or fail.get("message")
                    or fail.get("detail")
                    or fail.get("http_status")
                    or fail.get("status"),
                    "body_excerpt": str(fail)[:500],
                }
            )
    out = WORKSPACE / "results" / "phase7" / "jev_missing_diagnosis.json"
    out.write_text(json.dumps({"count": len(rows), "missing": rows}, indent=2) + "\n")
    print(f"missing_pairs={len(rows)} wrote={out}")
    for r in rows:
        print(
            f"{r['qualified_id']} {r['test_class']} "
            f"passwd={r['has_file_passwd']} err={r['error']!r}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
