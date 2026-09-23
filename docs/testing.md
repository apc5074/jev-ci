# Phase 2 tests

Focused determinism and manifest integrity checks live under `tests/`.

## Command

From the repository root, inside the Phase 1 container:

```bash
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" \
  -w /workspace \
  jev-ci:phase1 \
  python -m unittest discover -s tests -v
```

Uses the Python standard library only (`unittest`); no extra pip packages.

## Coverage

| Area | What is checked |
| --- | --- |
| Sampling | Matches `random.Random(20260922)` + continuous RNG; string `sorted`; shuffled input stability; first-five development split |
| Manifest integrity | Too-few / duplicate actives; wrong membership; mismatched combined lists; bad seed; wrong split positions; active-set hash; upstream commit/active drift |
| One-time write | Atomic write stability; failed replace leaves prior file intact and no `.tmp`; `create` does not rewrite; `verify` is byte-preserving |
| Patch truncation (P3-03) | Cap/marker reservation; equal prefix/suffix budgets; fixed→buggy unified-diff markers; no checkout path fragments |
| Test inventory (P3-04) | Unique `tests.all` parsing; `::` trigger→class; consistency hard-fail; inventory must not contain private label fields |
| Source resolution (P3-05) | Direct / nested / fallback / missing / ambiguous; every `tests.all` ID retained; no arbitrary pick on ambiguity |
| Representations (P3-06) | Tokenizer `parseHTTPResponse_v2`; BM25 window top-3 order/dedupe; missing-source convention; 12k cap |
| Prepare dataset (P3-07) | `--split development` only by default; evaluation requires `--allow-evaluation`; `--only` must be in-split |
| Integrity (P3-08) | Envelope leakage vs authentic source; Cli-30 direction sample; optional full audit via `JEV_RUN_FULL_PHASE3_AUDIT=1` |
| Lexical contract (P4-01) | FQCN+full-source documents; missing-source FQCN-only; hard-fail on absent claimed source; query=`representation.txt`; hashes; all 25 development bugs |
| Tokenizer (P4-02) | `parseHTTPResponse_v2`; Java FQCN/method splits; digit/underscore/acronym/Unicode/empty rules; Phase 3/4 same `tokenize`; provenance config hash |
| BM25 suite (P4-03) | Hand-computed toy corpus; score-desc / FQCN-asc ties; empty-query complete zeros; all 25 development rankings are inventory permutations with finite scores |
| Candidates (P4-04) | `K=min(200,N)` exact ranking prefix; reuse vs regenerate; semantic lock; shortlist hash; Phase 5 `load_candidates` |
| Run candidates (P4-05) | `--split development` only by default; evaluation requires `--allow-evaluation`; `--only` must be in-split; summary omits triggers |
| Audit (P4-06) | Ranking permutation + shortlist prefix; finite scores; development recall@K; Phase 5 `load_candidates` / hash contract |
| Jev providers (P5-01) | OpenRouter `typesafe/jev-1.13` selected (TypeSafe unavailable); fee math; Cloudflare rejected; live probe |
| Semantic cache (P5-02) | Canonical SHA-256 keys; atomic jev/gpt/embedding caches; failures isolated; ledger dedupe; cost split |
| Random baseline (P5-03) | Zero-based eval index + `1337+i` seed; disjoint development seeds; 1000 full-suite perms; regeneration fingerprint |
| Embedding baseline (P5-04) | Full-suite cosine on `text-embedding-3-small`; cache-first; fail-closed over-limit; no BM25; FQCN tie-break |
| Jev ranker (P5-05) | One-pair Noul; OpenRouter `typesafe/jev-1.13`; alias reject; cache-first; captured request proof |
| GPT ranker (P5-06) | Primary `gpt-5.4-nano` + `gpt-4.1-nano` + `gpt-4o-mini` + `gpt-luna`; structured probability; no CoT; same state as Jev |
| Scheduler (P5-07) | ≤16 concurrency; 429/5xx retries 1/2/4s; spend ceiling; in-flight cache-key dedupe; no score on failure |
| Assemble rankings (P5-08) | Shared BM25 shortlist; score↓/BM25-rank↑ prefix; unchanged BM25 tail; fail-closed missing scores; Cli-30 Jev+GPT |
| Phase 5 audit (P5-09) | Five-system coverage; shortlist equality; cache-only assembly proof; usage ledger summary; WAF availability flag |
| Development baseline (P6-01) | Dated review table; prompt freeze snapshot; accepted Jsoup-70 Jev WAF gap; 25/25 ok with gap |
| Defect triage (P6-02) | Correction log; ledger summary flat-cost fix; WAF classified availability not code defect |
| Method lock (P6-04) | `experiment.yaml` / `experiment.json`; decisions log; retain prompt v1; cost basis `effective_prepaid_credits_usd` |
| Preregistration (P6-05) | `EXPERIMENT.md` + synced YAML/JSON; prompt file SHA-256s; full ID lists |

Phase 2 tests do not check out Defects4J bugs or inspect triggers. Patch unit tests use fixtures only; live extraction is `python src/extract_patch.py <id>` in the container.
