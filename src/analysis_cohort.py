"""Headline analysis cohort: exclude A-001 Jev WAF gaps from *all* methods.

Twelve Jsoup evaluation bugs could not receive a complete Jev ranking (OpenRouter
WAF on ``ConnectTest`` / ``UrlConnectTest``). Rather than imputing worst-case
ranks for Jev only, headline metrics/statistics/figures drop those twelve bugs
for **every** method so denominators stay paired.

Raw Phase 7 artifacts still cover all 125 evaluation bugs. Phase 8 headline
outputs use this filtered cohort (n=113).
"""

from __future__ import annotations

from typing import Iterable, Sequence

from src.export_predictions import ACCEPTED_JEV_GAPS

# Same IDs as the accepted Phase 7 Jev availability gaps.
EXCLUDED_A001_EVAL_BUGS: frozenset[str] = frozenset(ACCEPTED_JEV_GAPS.keys())

FULL_EVAL_BUGS = 125
HEADLINE_EVAL_BUGS = FULL_EVAL_BUGS - len(EXCLUDED_A001_EVAL_BUGS)  # 113
HEADLINE_METRICS_ROWS = HEADLINE_EVAL_BUGS * 5  # 565
METHODS_PER_BUG = 5

COHORT_POLICY = "exclude_a001_jev_waf_gaps_from_all_methods"
COHORT_POLICY_NOTE = (
    "12 Jsoup evaluation bugs with accepted Jev A-001 WAF gaps are excluded "
    "from headline metrics for every method (paired denom=113). Listed in README."
)


def is_excluded_a001(qualified_id: str) -> bool:
    return str(qualified_id) in EXCLUDED_A001_EVAL_BUGS


def filter_headline_ids(ids: Iterable[str]) -> list[str]:
    """Stable project/bug order, A-001 gaps removed."""
    kept = [qid for qid in ids if not is_excluded_a001(qid)]
    return sorted(kept, key=lambda x: (x.split("-")[0], int(x.split("-")[1])))


def excluded_a001_sorted() -> list[str]:
    return sorted(
        EXCLUDED_A001_EVAL_BUGS,
        key=lambda x: (x.split("-")[0], int(x.split("-")[1])),
    )


def cohort_metadata() -> dict[str, object]:
    return {
        "policy": COHORT_POLICY,
        "note": COHORT_POLICY_NOTE,
        "full_evaluation_bugs": FULL_EVAL_BUGS,
        "headline_evaluation_bugs": HEADLINE_EVAL_BUGS,
        "excluded_count": len(EXCLUDED_A001_EVAL_BUGS),
        "excluded_qualified_ids": excluded_a001_sorted(),
        "excluded_reason": "A-001 OpenRouter WAF blocked complete Jev shortlist scoring",
    }


def require_headline_size(ids: Sequence[str], *, context: str) -> None:
    if len(ids) != HEADLINE_EVAL_BUGS:
        raise ValueError(
            f"{context}: expected {HEADLINE_EVAL_BUGS} headline bugs, got {len(ids)}"
        )
    if any(is_excluded_a001(qid) for qid in ids):
        raise ValueError(f"{context}: headline cohort still contains an A-001 gap ID")
