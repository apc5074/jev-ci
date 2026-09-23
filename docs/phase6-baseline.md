# Phase 6 development baseline (P6-01)

Generated: `2026-09-23T03:22:37+00:00`

Development-only diagnostic table. **Not** the headline evaluation results.

## Traceability

- Git: `6f8a3bc` (main, dirty)
- Jev prompt: `jev-would_detect_regression-v1` (revision count `0`)
- GPT prompt: `gpt-would_detect_regression-v1`
- Jev model: `typesafe/jev-1.13`
- Machine record: `results/phase6/development_baseline.json`

## Accepted gaps

- **Jsoup-70** / `org.jsoup.integration.ConnectTest` (Jev): OpenRouter Cloudflare WAF HTTP 403 on substring file://etc/passwd; accepted 2026-09-22 to continue Phase 6 (see docs/phase5-handoff.md).

## Summary

- Bugs ok: **25/25** (accepted gaps: 1)
- BM25 candidate recall@K: **100%**
- Mean BM25 first-trigger rank: 6.0

## Review table

| Bug | N | K | Patch trunc | BM25 FT | Emb FT | Jev FT | GPT FT | Cand recall | Systems |
| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | --- | --- |
| Cli-30 | 23 | 23 | N | 3 | 2 | 1 | 1 | Y | `YYYYY` |
| Cli-15 | 48 | 48 | N | 28 | 7 | 1 | 3 | Y | `YYYYY` |
| Cli-39 | 26 | 26 | N | 1 | 1 | 1 | 1 | Y | `YYYYY` |
| Cli-1 | 16 | 16 | N | 14 | 15 | 3 | 4 | Y | `YYYYY` |
| Cli-7 | 44 | 44 | N | 13 | 2 | 1 | 6 | Y | `YYYYY` |
| Lang-9 | 111 | 111 | N | 2 | 1 | 1 | 1 | Y | `YYYYY` |
| Lang-27 | 92 | 92 | N | 7 | 1 | 1 | 1 | Y | `YYYYY` |
| Lang-3 | 113 | 113 | N | 1 | 1 | 1 | 1 | Y | `YYYYY` |
| Lang-15 | 104 | 104 | N | 1 | 1 | 1 | 1 | Y | `YYYYY` |
| Lang-35 | 85 | 85 | N | 8 | 1 | 1 | 1 | Y | `YYYYY` |
| Math-25 | 306 | 200 | N | 1 | 1 | 1 | 1 | Y | `YYYYY` |
| Math-7 | 362 | 200 | N | 1 | 1 | 3 | 6 | Y | `YYYYY` |
| Math-87 | 184 | 184 | N | 2 | 2 | 1 | 1 | Y | `YYYYY` |
| Math-27 | 301 | 200 | N | 1 | 1 | 1 | 1 | Y | `YYYYY` |
| Math-100 | 135 | 135 | N | 2 | 1 | 2 | 1 | Y | `YYYYY` |
| Jsoup-2 | 12 | 12 | N | 1 | 1 | 1 | 1 | Y | `YYYYY` |
| Jsoup-51 | 26 | 26 | N | 5 | 12 | 3 | 1 | Y | `YYYYY` |
| Jsoup-29 | 23 | 23 | N | 10 | 1 | 1 | 1 | Y | `YYYYY` |
| Jsoup-70 | 34 | 34 | N | 2 | 1 | — | 2 | Y | `YYYGY` |
| Jsoup-4 | 16 | 16 | N | 5 | 1 | 1 | 2 | Y | `YYYYY` |
| JacksonDatabind-56 | 303 | 200 | N | 1 | 22 | 1 | 1 | Y | `YYYYY` |
| JacksonDatabind-95 | 349 | 200 | N | 1 | 1 | 9 | 14 | Y | `YYYYY` |
| JacksonDatabind-12 | 238 | 200 | N | 3 | 1 | 1 | 6 | Y | `YYYYY` |
| JacksonDatabind-105 | 432 | 200 | N | 21 | 6 | 1 | 2 | Y | `YYYYY` |
| JacksonDatabind-28 | 279 | 200 | N | 16 | 14 | 6 | 3 | Y | `YYYYY` |

Systems column order: Random, BM25, Embedding, Jev, GPT-Nano (`Y` present, `N` missing, `G` accepted gap).

FT = first-trigger rank (1-based). Lower is better for diagnosis only.

