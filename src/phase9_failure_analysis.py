"""P9-04: bounded qualitative failure analysis for the mechanical 20-case list."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.example_contract import (
    WORKSPACE,
    atomic_write_json,
    atomic_write_text,
    read_json,
    sha256_file,
)

SCHEMA = "jev-phase9-failure-analysis-v1"
FAILURE_CASES = WORKSPACE / "results" / "failure_cases.json"
OUT_JSON = WORKSPACE / "results" / "failure_analysis.json"
OUT_MD = WORKSPACE / "results" / "phase9" / "failure_analysis.md"

# Canonical category strings (overall.md §41 / phase9 P9-04).
CATEGORIES = (
    "identifier/name match",
    "behavioral semantic match",
    "cross-class relationship",
    "test source provided useful clue",
    "BM25 candidate-generation miss",
    "Jev overvalued superficial similarity",
    "Jev missed indirect dependency",
    "large/truncated patch",
    "large/truncated test",
    "ambiguous test responsibility",
)

# Qualitative review of the fixed P9-03 list only. No new model calls.
# Evidence cites sealed ranks, patch classes, and trigger FQCNs from saved artifacts.
ANALYSIS_ROWS: tuple[dict[str, Any], ...] = (
    {
        "qualified_id": "JacksonDatabind-62",
        "dominant_category": "behavioral semantic match",
        "evidence": (
            "Patch removes CollectionDeserializer array-delegate creator path "
            "(canCreateUsingArrayDelegate). Jev ranks ArrayDelegatorCreatorForCollectionTest "
            "#1 (p=0.70); BM25 ranks it #131. Reranker win: semantic link between array-delegate "
            "creation and the named creator test, not a shortlist miss."
        ),
    },
    {
        "qualified_id": "JacksonDatabind-35",
        "dominant_category": "behavioral semantic match",
        "evidence": (
            "Patch edits AsWrapperTypeDeserializer; trigger WrapperObjectWithObjectIdTest. "
            "Jev places it #3 among typed/wrapper deserialization tests; BM25 #114 behind "
            "generic deserializer/factory names. Behavioral wrapper/type-id match."
        ),
    },
    {
        "qualified_id": "JacksonDatabind-38",
        "dominant_category": "cross-class relationship",
        "evidence": (
            "Patch changes CollectionType/MapType/SimpleType construction; trigger is "
            "interop.DeprecatedTypeHandling1102Test (explicit collection/map type APIs). "
            "Jev #5 after other type/generics tests; BM25 #93 stuck on TestTypeFactory lexical "
            "neighbors. Failure mode avoided: cross-package type-API consumer test."
        ),
    },
    {
        "qualified_id": "JacksonDatabind-49",
        "dominant_category": "behavioral semantic match",
        "evidence": (
            "WritableObjectId change; trigger objectid.AlwaysAsReferenceFirstTest. "
            "Jev packs ObjectId tests in the top ranks (trigger #8); BM25 #85 with "
            "serializer config noise. Object-id / always-as-reference behavior match."
        ),
    },
    {
        "qualified_id": "JacksonDatabind-47",
        "dominant_category": "behavioral semantic match",
        "evidence": (
            "AnnotationIntrospector serialize-typing change; triggers TestJsonSerialize / "
            "TestJsonSerializeAs (broken annotation / specialized-as). Jev #1/#4; BM25 #63. "
            "Reranker maps introspector annotation logic to @JsonSerialize tests."
        ),
    },
    {
        "qualified_id": "JacksonDatabind-72",
        "dominant_category": "identifier/name match",
        "evidence": (
            "InnerClassProperty ↔ creators.InnerClassCreatorTest. Shared InnerClass token; "
            "Jev #1 vs BM25 #50. Dominant signal is the identifier overlap Jev promoted "
            "that BM25 under-weighted in the full suite ordering."
        ),
    },
    {
        "qualified_id": "JacksonDatabind-15",
        "dominant_category": "behavioral semantic match",
        "evidence": (
            "Patch touches StdDelegatingSerializer / converter serializer path; trigger "
            "convert.TestConvertingSerializer at Jev #1 vs BM25 #48 (BM25 preferred "
            "TestBeanConversions). Converting/delegating serializer semantics."
        ),
    },
    {
        "qualified_id": "Cli-21",
        "dominant_category": "test source provided useful clue",
        "evidence": (
            "Removes WriteableCommandLine get/setCurrentOption; trigger BugCLI150Test. "
            "Jev elevates bug.* regression tests (trigger #4) while BM25 #49 prefers "
            "option/Group unit tests. Bug-test source aligns with the current-option API loss."
        ),
    },
    {
        "qualified_id": "Math-13",
        "dominant_category": "cross-class relationship",
        "evidence": (
            "AbstractLeastSquaresOptimizer.squareRoot(DiagonalMatrix) change; trigger "
            "optimization.fitting.PolynomialFitterTest (uses the optimizer). Jev #7 in an "
            "optimizer/fitter cluster; BM25 #50 distracted by EigenDecomposition matrix tests. "
            "Fitter→optimizer dependency, not same-class naming."
        ),
    },
    {
        "qualified_id": "Math-14",
        "dominant_category": "cross-class relationship",
        "evidence": (
            "Weight / AbstractLeastSquaresOptimizer diagonal-weight change; trigger "
            "fitting.PolynomialFitterTest. Jev #5; BM25 #44 again ranks linear-algebra tests "
            "first. Same cross-class fitter→optimizer pattern as Math-13."
        ),
    },
    {
        "qualified_id": "JacksonDatabind-103",
        "dominant_category": "large/truncated patch",
        "evidence": (
            "Multi-file exception/context patch (~14.8k chars, patch_truncated=true). "
            "Trigger exc.BasicExceptionTest. BM25 #7 (exception lexical cues); Jev #26 among "
            "unrelated deser/creator tests. Truncated wide patch harms reranker focus."
        ),
    },
    {
        "qualified_id": "Math-104",
        "dominant_category": "Jev overvalued superficial similarity",
        "evidence": (
            "Gamma.java ↔ special.GammaTest. BM25 #2 via Gamma name tokens; Jev #19 after "
            "ChiSquare/Poisson/inference tests. Reranker preferred neighboring stats "
            "distributions over the matching GammaTest."
        ),
    },
    {
        "qualified_id": "JacksonDatabind-51",
        "dominant_category": "Jev overvalued superficial similarity",
        "evidence": (
            "TypeDeserializerBase change; trigger jsontype.TestCustomTypeIdResolver. "
            "BM25 #17; Jev #25 after polymorphic/generics deser tests. Superficial "
            "type-system theme outranked the custom type-id resolver test."
        ),
    },
    {
        "qualified_id": "Lang-6",
        "dominant_category": "Jev missed indirect dependency",
        "evidence": (
            "CharSequenceTranslator code-point indexing change; trigger "
            "StringUtilsTest::testEscapeSurrogatePairs (StringUtils escape uses the "
            "translator). BM25 #5 includes StringUtilsTest; Jev #13 after direct "
            "translate.* tests. Missed the StringUtils→translator dependency."
        ),
    },
    {
        "qualified_id": "Lang-61",
        "dominant_category": "Jev overvalued superficial similarity",
        "evidence": (
            "StrBuilder ↔ StrBuilderTest (clear name match). BM25 #1; Jev #5 behind "
            "StringUtilsEqualsIndexOfTest and other text utils. Overvalued adjacent "
            "string utilities versus the matching *Test class."
        ),
    },
    {
        "qualified_id": "Cli-28",
        "dominant_category": "Jev overvalued superficial similarity",
        "evidence": (
            "Parser change; trigger ValueTest. BM25 #2; Jev #4 after BugCLI13/BugCLI148. "
            "Bug-regression tests outranked the value-parsing test that BM25 surfaced."
        ),
    },
    {
        "qualified_id": "Lang-26",
        "dominant_category": "Jev overvalued superficial similarity",
        "evidence": (
            "FastDateFormat ↔ FastDateFormatTest. BM25 #1; Jev #3 behind "
            "ExtendedMessageFormatTest / DateFormatUtilsTest. Neighboring date-format "
            "tests displaced the identifier-matched trigger."
        ),
    },
    {
        "qualified_id": "Cli-32",
        "dominant_category": "identifier/name match",
        "evidence": (
            "HelpFormatter ↔ HelpFormatterTest. BM25 #1 via name; Jev #2 after BugCLI162Test. "
            "Small loss: BM25's identifier match beat Jev's bug-test preference by one rank."
        ),
    },
    {
        "qualified_id": "JacksonDatabind-100",
        "dominant_category": "ambiguous test responsibility",
        "evidence": (
            "TreeTraversingParser patched; trigger node.TestConversions (not "
            "TestTreeTraversingParser). Jev #1 ranks TestTreeTraversingParser (class-name "
            "match to the modified file); BM25 #1 ranks TestConversions (actual trigger). "
            "Same-package name match is the wrong positive; responsibility is ambiguous."
        ),
    },
    {
        "qualified_id": "Lang-47",
        "dominant_category": "Jev overvalued superficial similarity",
        "evidence": (
            "StrBuilder ↔ StrBuilderTest. BM25 #1; Jev #2 after StrBuilderAppendInsertTest. "
            "Near-miss: related StrBuilder* test preferred over the labeled trigger class."
        ),
    },
)


class FailureAnalysisError(Exception):
    """Phase 9 failure analysis validation failed."""


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _rel(path: Path, *, workspace: Path) -> str:
    try:
        return str(path.resolve().relative_to(workspace.resolve()))
    except ValueError:
        return str(path)


def _hash_meta(path: Path, *, workspace: Path) -> dict[str, Any]:
    return {
        "path": _rel(path, workspace=workspace),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
    }


def _index_cases(failure_cases: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {c["qualified_id"]: c for c in failure_cases["cases"]}


def validate_analysis_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    selected_ids: Sequence[str],
) -> None:
    ids = [r["qualified_id"] for r in rows]
    if ids != list(selected_ids):
        raise FailureAnalysisError(
            "analysis row order/IDs must match failure_cases selected_ids exactly"
        )
    if len(set(ids)) != 20:
        raise FailureAnalysisError(f"expected 20 distinct IDs, got {len(set(ids))}")
    for row in rows:
        cat = row["dominant_category"]
        if cat not in CATEGORIES:
            raise FailureAnalysisError(f"{row['qualified_id']}: unknown category {cat!r}")
        if not str(row.get("evidence", "")).strip():
            raise FailureAnalysisError(f"{row['qualified_id']}: empty evidence")


def build_failure_analysis(*, workspace: Path | None = None) -> dict[str, Any]:
    root = workspace or WORKSPACE
    fc_path = root / "results" / "failure_cases.json"
    if not fc_path.is_file():
        raise FailureAnalysisError(f"missing {fc_path} (run P9-03 first)")
    failure_cases = read_json(fc_path)
    selected_ids = list(failure_cases["selected_ids"])
    validate_analysis_rows(ANALYSIS_ROWS, selected_ids=selected_ids)
    by_case = _index_cases(failure_cases)

    rows_out: list[dict[str, Any]] = []
    for ann in ANALYSIS_ROWS:
        qid = ann["qualified_id"]
        base = by_case[qid]
        rows_out.append(
            {
                "qualified_id": qid,
                "selection_arm": base["selection_arm"],
                "bm25_first_trigger_rank": base["bm25_first_trigger_rank"],
                "jev_first_trigger_rank": base["jev_first_trigger_rank"],
                "delta_bm25_minus_jev": base["delta_bm25_minus_jev"],
                "delta_sign_label": base["delta_sign_label"],
                "candidate_trigger_in_top200": base["candidate_trigger_in_top200"],
                "dominant_category": ann["dominant_category"],
                "evidence": ann["evidence"],
            }
        )

    category_counts: dict[str, int] = {c: 0 for c in CATEGORIES}
    for row in rows_out:
        category_counts[row["dominant_category"]] += 1

    shortlist_misses = sum(
        1 for row in rows_out if not row["candidate_trigger_in_top200"]
    )
    return {
        "schema_version": SCHEMA,
        "generated_at_utc": _utcnow(),
        "ok": True,
        "n_cases": len(rows_out),
        "categories": list(CATEGORIES),
        "category_counts": {k: v for k, v in category_counts.items() if v},
        "shortlist_miss_cases": shortlist_misses,
        "notes": (
            "Review uses only sealed patch/test/ranking artifacts. "
            "No new model calls. Categories are explanatory; they do not change "
            "metrics, prompts, or shortlist size. All 20 mechanically selected "
            "IDs are covered exactly once."
        ),
        "input_hashes": {
            "failure_cases": _hash_meta(fc_path, workspace=root),
        },
        "selected_ids": selected_ids,
        "cases": rows_out,
    }


def render_failure_analysis_md(doc: Mapping[str, Any]) -> str:
    lines = [
        "# Qualitative failure analysis (P9-04)",
        "",
        f"Mechanically selected **n = {doc['n_cases']}** cases from "
        "`results/failure_cases.json`. Shortlist misses in this set: "
        f"**{doc['shortlist_miss_cases']}** (candidate-generation vs reranker).",
        "",
        doc["notes"],
        "",
        "## Category counts",
        "",
    ]
    for cat, n in sorted(doc["category_counts"].items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"- {cat}: {n}")
    lines.extend(
        [
            "",
            "## Cases",
            "",
            "| ID | Arm | BM25 r | Jev r | Δ | Trig∈200 | Category | Evidence |",
            "| --- | --- | ---: | ---: | ---: | --- | --- | --- |",
        ]
    )
    for c in doc["cases"]:
        lines.append(
            "| `{qid}` | {arm} | {bm25} | {jev} | {delta} | {trig} | {cat} | {ev} |".format(
                qid=c["qualified_id"],
                arm=c["selection_arm"].replace("top10_jev_", ""),
                bm25=c["bm25_first_trigger_rank"],
                jev=c["jev_first_trigger_rank"],
                delta=c["delta_bm25_minus_jev"],
                trig="yes" if c["candidate_trigger_in_top200"] else "no",
                cat=c["dominant_category"],
                ev=c["evidence"].replace("|", "\\|"),
            )
        )
    lines.extend(
        [
            "",
            "## Provenance",
            "",
            f"- JSON: `results/failure_analysis.json`",
            f"- failure_cases sha256=`{doc['input_hashes']['failure_cases']['sha256']}`",
            "",
        ]
    )
    return "\n".join(lines)


def publish_failure_analysis(*, workspace: Path | None = None) -> dict[str, Any]:
    root = workspace or WORKSPACE
    doc = build_failure_analysis(workspace=root)
    out_json = root / "results" / "failure_analysis.json"
    out_md = root / "results" / "phase9" / "failure_analysis.md"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(out_json, doc)
    atomic_write_text(out_md, render_failure_analysis_md(doc))
    return doc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="P9-04: publish bounded qualitative failure analysis"
    )
    parser.add_argument("--workspace", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        doc = publish_failure_analysis(workspace=args.workspace)
    except FailureAnalysisError as exc:
        print(f"FAIL phase9_failure_analysis: {exc}", file=sys.stderr)
        return 1
    print(
        "OK phase9_failure_analysis "
        f"n={doc['n_cases']} categories={len(doc['category_counts'])} "
        f"path=results/failure_analysis.json"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
