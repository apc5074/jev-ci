# Jev provider decision (Phase 5 / P5-01)

Decision date: **2026-09-22** (updated after TypeSafe direct proved unavailable).

Implementation: [`src/jev_providers.py`](../src/jev_providers.py),
CLI [`scripts/verify_jev_providers.py`](../scripts/verify_jev_providers.py).

## Selected route

| Field | Value |
| --- | --- |
| Provider | **OpenRouter** |
| Endpoint | `POST https://openrouter.ai/api/v1/systemone` |
| Request model | **`typesafe/jev-1.13`** |
| Observed model (probe) | **`typesafe/jev-1.13-20260917`** |
| Auth | `Authorization: Bearer $OPENROUTER_API_KEY` |
| Noul | `answers.<id>.type == "noul"` and `noul ∈ [0,1]`; usage has `input_tokens` / `output_tokens` (+ `cost`) |

**Why not TypeSafe direct:** preferred on cost (no 5.5% fee) but account access /
waitlist blocked. Documented as `unavailable_preferred` in
`results/jev_provider_decision.json`.

**Cloudflare `typesafe/jev`:** still rejected for evaluation until on-account Jev
price and an immutable pin are verified. Do **not** claim free inference from
free AI Gateway features.

## Live probe (passed)

```bash
docker run --rm --platform linux/amd64 \
  --env-file .env \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 \
  python scripts/verify_jev_providers.py
```

Result (development-only synthetic state; not benchmark data):

- `ready_for_scoring=True`
- `noul` returned in `[0,1]` with usage accounting
- Artifact: `results/openrouter_jev_probe.json`

## Cost note

List inference matches TypeSafe ($0.042/MTok in, output free). OpenRouter
**standard credit purchases add 5.5%**, so prepaid cash is slightly higher than
direct TypeSafe would have been.

## Alias policy

Never use `jev-latest`, `jev-preview`, or `~typesafe/jev-latest` for evaluation.
Request `typesafe/jev-1.13` and record `response.model` each run for provenance.
