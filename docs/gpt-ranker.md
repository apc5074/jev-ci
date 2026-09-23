# GPT comparison clients (Phase 5 / P5-06)

Implementation: [`src/gpt_ranker.py`](../src/gpt_ranker.py).

## Models

| Key | Canonical / cache `model_id` | Ranking name | Role |
| --- | --- | --- | --- |
| `gpt-5.4-nano` | `gpt-5.4-nano-2026-03-17` | **GPT-Nano** | **Primary** (overall.md §20); `reasoning.effort=none` |
| `gpt-4.1-nano` | `gpt-4.1-nano-2025-04-14` | GPT-4.1-Nano | Additional cheap nano comparator |
| `gpt-4o-mini` | `gpt-4o-mini-2024-07-18` | GPT-4o-mini | Additional small generative comparator |
| `gpt-luna` | `gpt-5.6-luna` | GPT-Luna | Additional nano-tier (`reasoning.effort=none`); not `~openai/gpt-luna-latest` |

Registry artifact: `results/gpt_comparison_models.json`.

OpenRouter request slugs (when `OPENAI_API_KEY` is absent):

| Key | OpenRouter model |
| --- | --- |
| `gpt-5.4-nano` | `openai/gpt-5.4-nano` (dated snapshot id not published on OpenRouter; record `response.model`) |
| `gpt-4.1-nano` | `openai/gpt-4.1-nano-2025-04-14` |
| `gpt-4o-mini` | `openai/gpt-4o-mini-2024-07-18` |
| `gpt-luna` | `openai/gpt-5.6-luna` |

The Phase-6 headline table still centers on **GPT-Nano**; the other two are
extra development comparisons for preregistration review.

## Shared contract (all models)

- Same Phase 3 `code_change` / `candidate_test` strings as Jev (byte-for-byte).
- Same rubric instructions/criteria as Jev (`build_gpt_question()`).
- Structured output only: `{"probability": <number in [0,1]>}`.
- No chain-of-thought requested or stored.
- Reject malformed / out-of-range probabilities (never coerce / never default 0.5).
- Cache key includes provider + canonical model id + prompt version + state + question.

Prompt version: `gpt-would_detect_regression-v1`.

## Commands

```bash
# Primary model, one shortlist candidate + capture
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace --env-file .env \
  jev-ci:phase1 \
  python src/gpt_ranker.py Cli-30 --capture

# All three comparison models on one candidate
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace --env-file .env \
  jev-ci:phase1 \
  python src/gpt_ranker.py Cli-30 --model all --capture

# Full shortlist for every comparison model
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace --env-file .env \
  jev-ci:phase1 \
  python src/gpt_ranker.py Cli-30 --model all --shortlist --capture
```
