# Phase 7 Jev shortlist scoring (P7-05)

**Overall: `PASS` with accepted availability gaps**

- `experiment_commit`: `edc70bacd23f2fc5f511ef4d97a33376e7b20bf8`
- Provider / model: OpenRouter `typesafe/jev-1.13`
- Prompt: `jev-would_detect_regression-v1`
- Bugs with complete shortlist scores: **113/125**
- Pairs scored: **13402 / 13414**
- Spend ceiling: `$16.23` (operational)

## Accepted availability gaps (A-001 eval extension)

OpenRouter Cloudflare **HTTP 403** WAF on model-visible text containing
`file://etc/passwd`. Do **not** rewrite representations.

| Bug | Blocked class |
| --- | --- |
| Jsoup-33 | `org.jsoup.integration.UrlConnectTest` |
| Jsoup-54 | `org.jsoup.integration.UrlConnectTest` |
| Jsoup-40 | `org.jsoup.integration.UrlConnectTest` |
| Jsoup-47 | `org.jsoup.integration.UrlConnectTest` |
| Jsoup-78 | `org.jsoup.integration.ConnectTest` |
| Jsoup-81 | `org.jsoup.integration.ConnectTest` |
| Jsoup-86 | `org.jsoup.integration.ConnectTest` |
| Jsoup-69 | `org.jsoup.integration.ConnectTest` |
| Jsoup-75 | `org.jsoup.integration.ConnectTest` |
| Jsoup-85 | `org.jsoup.integration.ConnectTest` |
| Jsoup-72 | `org.jsoup.integration.ConnectTest` |
| Jsoup-84 | `org.jsoup.integration.ConnectTest` |

**12 pairs** unavailable. Same root cause as development A-001 (Jsoup-70).

## Transient retries

`Math-89` had 8× OpenRouter **HTTP 520**; retried successfully (cache-complete).

## Commands

```bash
python -u scripts/run_jev.py --split evaluation --allow-evaluation \
  --max-concurrency 16 --spend-ceiling-usd 16.23
python -u scripts/audit_jev.py --split evaluation
python -u scripts/diagnose_jev_missing.py
```

## Assembly note

`fail_closed_on_missing_scores` applies: Jev assembly for the 12 bugs above
must record the gap / deviate formally rather than invent scores.

Machine records:

- `results/jev_scoring_summary-evaluation.json`
- `results/phase7/jev_audit.json`
- `results/phase7/jev_missing_diagnosis.json`
- `results/phase7/run_jev-evaluation.log`
