# Phase 9 qualitative failure analysis (P9-04)

**Overall: `PASS`**

Bounded review of the **20 mechanically selected** cases from
[`results/failure_cases.json`](../results/failure_cases.json). No new model calls;
no substitutions; categories are explanatory only.

## Artifacts

| Artifact | Path |
| --- | --- |
| Analysis JSON | [`results/failure_analysis.json`](../results/failure_analysis.json) |
| Table (Markdown) | [`results/phase9/failure_analysis.md`](../results/phase9/failure_analysis.md) |

Each row: ID, BM25/Jev ranks, Δ, shortlist-trigger status, dominant category, brief evidence.

## Category census (this set)

See the JSON `category_counts`. Headline pattern in this sample:

- Gains: mostly **behavioral semantic match**, **cross-class relationship**, **identifier/name match**, plus one **test source** clue.
- Losses: mostly **Jev overvalued superficial similarity**, plus **large/truncated patch**, **Jev missed indirect dependency**, **ambiguous test responsibility**.
- **BM25 candidate-generation miss:** 0 of 20 (all triggers were in the top-200 shortlist).

## Commands

```bash
docker run --rm --platform linux/amd64 --network=none \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 python -u scripts/publish_failure_analysis.py
```

Requires P9-03 `results/failure_cases.json`.
