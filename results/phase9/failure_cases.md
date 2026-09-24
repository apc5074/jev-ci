# Mechanically selected failure / gain cases (P9-03)

Headline cohort **n = 113**. Rule: `delta = BM25_first_trigger_rank - Jev_first_trigger_rank; 10 largest deltas (Jev gains) + 10 smallest (Jev losses); tie-break: project name then numeric bug_id (manifest order family)`

Selection is fixed before qualitative review (P9-04). Do not replace cases for narrative convenience.

## Selected IDs (gains then losses)

`JacksonDatabind-62`, `JacksonDatabind-35`, `JacksonDatabind-38`, `JacksonDatabind-49`, `JacksonDatabind-47`, `JacksonDatabind-72`, `JacksonDatabind-15`, `Cli-21`, `Math-13`, `Math-14`, `JacksonDatabind-103`, `Math-104`, `JacksonDatabind-51`, `Lang-6`, `Lang-61`, `Cli-28`, `Lang-26`, `Cli-32`, `JacksonDatabind-100`, `Lang-47`

## Table

| # | ID | Arm | BM25 r | Jev r | Δ (BM25−Jev) | Sign | Trigger∈top200 |
| --- | --- | --- | ---: | ---: | ---: | --- | --- |
| 1 | `JacksonDatabind-62` | top10_jev_gains | 131 | 1 | 130 | jev_gain | yes |
| 2 | `JacksonDatabind-35` | top10_jev_gains | 114 | 3 | 111 | jev_gain | yes |
| 3 | `JacksonDatabind-38` | top10_jev_gains | 93 | 5 | 88 | jev_gain | yes |
| 4 | `JacksonDatabind-49` | top10_jev_gains | 85 | 8 | 77 | jev_gain | yes |
| 5 | `JacksonDatabind-47` | top10_jev_gains | 63 | 1 | 62 | jev_gain | yes |
| 6 | `JacksonDatabind-72` | top10_jev_gains | 50 | 1 | 49 | jev_gain | yes |
| 7 | `JacksonDatabind-15` | top10_jev_gains | 48 | 1 | 47 | jev_gain | yes |
| 8 | `Cli-21` | top10_jev_gains | 49 | 4 | 45 | jev_gain | yes |
| 9 | `Math-13` | top10_jev_gains | 50 | 7 | 43 | jev_gain | yes |
| 10 | `Math-14` | top10_jev_gains | 44 | 5 | 39 | jev_gain | yes |
| 11 | `JacksonDatabind-103` | top10_jev_losses | 7 | 26 | -19 | jev_loss | yes |
| 12 | `Math-104` | top10_jev_losses | 2 | 19 | -17 | jev_loss | yes |
| 13 | `JacksonDatabind-51` | top10_jev_losses | 17 | 25 | -8 | jev_loss | yes |
| 14 | `Lang-6` | top10_jev_losses | 5 | 13 | -8 | jev_loss | yes |
| 15 | `Lang-61` | top10_jev_losses | 1 | 5 | -4 | jev_loss | yes |
| 16 | `Cli-28` | top10_jev_losses | 2 | 4 | -2 | jev_loss | yes |
| 17 | `Lang-26` | top10_jev_losses | 1 | 3 | -2 | jev_loss | yes |
| 18 | `Cli-32` | top10_jev_losses | 1 | 2 | -1 | jev_loss | yes |
| 19 | `JacksonDatabind-100` | top10_jev_losses | 1 | 2 | -1 | jev_loss | yes |
| 20 | `Lang-47` | top10_jev_losses | 1 | 2 | -1 | jev_loss | yes |

## Delta sign census (full cohort)

- Positive (Jev earlier): 65
- Negative (BM25 earlier): 10
- Zero: 38

## Provenance

- JSON: `results/failure_cases.json`
- per_bug_metrics sha256=`645b9ee7beaf99b7d5d169f6988828b2adbaf69b13071d5452f027499c06de40`
- metrics.csv sha256=`4bd4be3cc3f59e8d90b6fb4c847d45995bf6f97697a0a0d6b6dadb2ab9ecb32e`
