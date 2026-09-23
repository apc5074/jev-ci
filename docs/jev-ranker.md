# Jev one-pair decision client (Phase 5 / P5-05)

Implementation: [`src/jev_ranker.py`](../src/jev_ranker.py).

## Semantic contract

Exactly **one** patch/test-class pair per request:

```json
{
  "model": "typesafe/jev-1.13",
  "state": {
    "code_change": "<Phase 3 patch representation.txt>",
    "candidate_test": "<Phase 3 test representation.txt>"
  },
  "questions": {
    "would_detect_regression": {
      "type": "noul",
      "instructions": "<overall.md §18>",
      "criteria": { "true": "...", "false": "..." }
    }
  }
}
```

Score:

```text
jev_score = answer.noul   # finite, in [0, 1]; no threshold; no substitute fields
```

Prompt version: `jev-would_detect_regression-v1` ([`src/semantic_cache.py`](../src/semantic_cache.py)).

## Provider

Locked by P5-01 ([jev-provider-decision.md](jev-provider-decision.md)):

| Field | Value |
| --- | --- |
| Provider | OpenRouter |
| Request model | `typesafe/jev-1.13` |
| Endpoint | `POST /api/v1/systemone` |
| Observed snapshot | recorded per response (e.g. `typesafe/jev-1.13-20260917`) |

Forbidden for evaluation: `jev-latest`, `jev-preview`, `~typesafe/jev-latest`.
TypeSafe direct remains an adapter when `TYPESAFE_API_KEY` exists.

Auth is runtime-only (`OPENROUTER_API_KEY` / `TYPESAFE_API_KEY`). Errors/logs redact
bearer tokens.

## Cache

Key includes provider, model, prompt version, state, and question. Hits under
`cache/jev/<sha256>.json` skip the network. Failures go to `cache/failures/` and
are never treated as scores.

## Captured request proof

A development call with `--capture` writes
`results/jev_captured_request.json`: wire body (one pair only), score, usage,
and checks that private label fields / pipeline bug-status tokens are absent
from the envelope.

## Commands

```bash
# One shortlist candidate + capture proof
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace --env-file .env \
  jev-ci:phase1 \
  python src/jev_ranker.py Cli-30 --capture

# Full BM25 shortlist for one development bug (sequential; concurrency in P5-07)
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace --env-file .env \
  jev-ci:phase1 \
  python src/jev_ranker.py Cli-30 --shortlist --capture
```
