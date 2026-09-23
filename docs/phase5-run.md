# Phase 5 development runners (P5-09)

Pre-freeze commands for the **25 development** bugs only. Evaluation requires
`--allow-evaluation` (post Phase-6 freeze).

## Baselines (already complete)

```bash
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 \
  python scripts/run_baselines.py --split development
```

Also: `scripts/run_random_baseline.py`, `scripts/run_embeddings.py`,
`scripts/run_candidates.py`.

## Jev shortlist scoring

```bash
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace --env-file .env \
  jev-ci:phase1 \
  python -u scripts/run_jev.py --split development \
    --max-concurrency 16
```

Optional: `--max-rpm`, `--spend-ceiling-usd`, `--only Cli-30`.

## GPT shortlist scoring

Primary (required for the five systems):

```bash
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace --env-file .env \
  jev-ci:phase1 \
  python -u scripts/run_gpt.py --split development \
    --model primary --max-concurrency 6 --max-rpm 24
```

All comparison models: `--model all`.

## Assemble rankings

```bash
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 \
  python -m src.assemble_rankings --only-primary-gpt
```

## Audit + cache-only proof

```bash
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 \
  python scripts/audit_phase5.py
```

Writes `results/audit-phase5.json`. Cache-only assembly proof clears API keys
in-process and reassembles from `cache/` + decision files.

## Known OpenRouter WAF issue

OpenRouter’s Cloudflare edge **HTTP 403**s Jev System One requests whose
model-visible state contains the literal substring `file://etc/passwd`
(case-insensitive). In the development set this appears only in
**Jsoup-70 / `org.jsoup.integration.ConnectTest`**. GPT chat completions accept
the same string. Do **not** truncate or rewrite Phase-3 representations to
bypass the WAF.

**Accepted for Phase 6 (2026-09-22):** continue with 24/25 complete Jev rankings;
document the gap in the development baseline. Resolve before evaluation freeze
if TypeSafe or an OpenRouter allowlist becomes available.
