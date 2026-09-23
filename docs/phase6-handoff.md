# Phase 6 handoff (to Phase 7)

Phase 6 freezes the study design. Phase 7 must execute this configuration on the
**125 evaluation** bugs without changing prompts, K, models, metrics, or
success criteria.

**Freeze tag:** `experiment-v1-frozen`  
**Freeze commit SHA:** `_FILL_AFTER_TAG_`  
**Pre-eval gate:** [`phase6-pre-eval-gate.md`](phase6-pre-eval-gate.md) · `results/phase6/pre_eval_gate.json` (**PASS** 25/25)

After you create the annotated tag, run:

```bash
python scripts/write_freeze_lock.py
```

That writes `results/phase6/freeze_lock.json` **outside** the tagged commit
(self-referential freeze SHA must not live inside the tagged tree). Then fill
the SHA above and in any Phase 7 run records.

## Do not

- Resample `data/manifest.json` or alter development/evaluation membership
- Edit `EXPERIMENT.md` / `experiment.yaml` / prompt files quietly after the tag
- Score evaluation bugs before `freeze_lock.json` unlocks evaluation
- Rewrite representations to bypass A-001 (Jsoup WAF)
- Compute aggregate FDR / method comparisons until Phase 8 (after P7-09 seal)

## Locked inputs

| Choice | Value |
| --- | --- |
| Manifest | `data/manifest.json` (SHA-256 `ec8b1dbc570ea8fa0a160fc5fe1de55d821c91f1452979c544af5094a4582971`) |
| Defects4J | 3.0.1 @ `6d54320e0db5a357f9ab38a8e4d2e5aead7e1c09` |
| Split | 25 development + 125 evaluation; project order Cli → Lang → Math → Jsoup → JacksonDatabind |
| Direction | base `Bf`, proposed `Bb`, `fixed_to_buggy` |
| Systems | Random, BM25, Embedding, Jev, GPT-Nano |
| K | `min(200, N)`; shortlist = BM25 ranking prefix |
| Jev | OpenRouter `typesafe/jev-1.13` (dev observed `…-20260917`); prompt `jev-would_detect_regression-v1`; revision count **0** |
| GPT-Nano | `gpt-5.4-nano-2026-03-17` / OpenRouter `openai/gpt-5.4-nano`; `reasoning.effort=none` |
| Cost criterion basis | `effective_prepaid_credits_usd` ([`results/pricing_snapshot.json`](../results/pricing_snapshot.json), date **2026-09-23**) |
| Primary outcome | FDR@10%; McNemar exact; 10,000 paired bootstrap samples |

### Content hashes (working tree at handoff authoring)

| Path | SHA-256 |
| --- | --- |
| `EXPERIMENT.md` | `ed918407003a9841b4b50a7754723495877d7c089d3c8a510a1d22c72dc47654` |
| `experiment.yaml` | `40bae8e19645645e8e5e98863de9d849fe444b8f77e4651828b113557ed45f2c` |
| `prompts/jev/v1.json` | `2687635cea341f22e88ad848de09be711b6e80fe45f46d93da72e0ca4a477401` |
| `prompts/gpt/v1.json` | `a5e7c1590f560dc6faf1b81fc84bbc4a1cb75d125c370bfa23f2724a6e71fd90` |
| `results/phase6/experiment.json` | `45504fbea563932176eb19eeecc9794478acc9ba8a9f1ec768edcc8308fe5812` |
| `results/pricing_snapshot.json` | `e300d66be9e18925b32bac7c32f09454b1aa82afaeccedd20dfb7ef56f4a0b92` |
| `data/manifest.json` | `ec8b1dbc570ea8fa0a160fc5fe1de55d821c91f1452979c544af5094a4582971` |

Re-hash after your freeze commit if you amend any of these files before tagging.

## Credentials / providers

Inject at runtime (never commit `.env`):

```bash
# Required for evaluation scoring
OPENROUTER_API_KEY=...
# Optional fallbacks
OPENAI_API_KEY=...
TYPESAFE_API_KEY=...   # preferred if direct Jev becomes available
```

Confirm the OpenRouter Jev route still reports the pinned underlying model
(`typesafe/jev-1.13-…`), not a moving alias.

## Container + verify freeze

```bash
docker build --platform linux/amd64 -t jev-ci:phase1 .

# After tagging: clean check from the tag
git checkout experiment-v1-frozen
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace \
  jev-ci:phase1 \
  python -u scripts/run_pre_eval_gate.py

# Unlock evaluation (post-tag; creates freeze_lock.json)
python scripts/write_freeze_lock.py
```

## Evaluation execution order (Phase 7)

Use the **locked evaluation ID list** from `data/manifest.json` /
`results/phase6/experiment.json` (`evaluation_bug_ids`, length 125). Suggested
runner order:

1. `scripts/prepare_dataset.py --split evaluation --allow-evaluation`
2. `scripts/run_candidates.py --split evaluation --allow-evaluation` (BM25 + seal shortlists)
3. `scripts/run_embeddings.py --split evaluation --allow-evaluation`
4. `scripts/run_random_baseline.py --split evaluation --allow-evaluation`
5. `scripts/run_jev.py --split evaluation --allow-evaluation`
6. `scripts/run_gpt.py --split evaluation --model primary --allow-evaluation`
7. Assemble / seal raw rankings (P7-08/P7-09) — **no aggregate FDR yet**

Attach `experiment_commit=<freeze SHA>` to every new evaluation result file.

### Cache roots (reuse exact hits only)

- `cache/jev/`, `cache/gpt/`, `cache/embeddings/`, `cache/failures/`
- Ledger: `results/usage_ledger.jsonl`
- Development rankings/shortlists under `data/candidates/`, `results/rankings/`, `results/semantic/` — do not overwrite from evaluation runs

## Open availability (must settle before eval scoring)

| ID | Bug | Issue |
| --- | --- | --- |
| A-001 | Jsoup-70 / `ConnectTest` | OpenRouter WAF on `file://etc/passwd` (development Jev gap). Resolve, deviate formally, or confirm evaluation representations are unaffected before scoring evaluation Jev. |

## Your freeze commit checklist (P6-07)

Include:

- [ ] `EXPERIMENT.md`, `experiment.yaml`
- [ ] `prompts/jev/v1.json`, `prompts/gpt/v1.json`
- [ ] `src/` (esp. `freeze_guard.py`, `pre_eval_gate.py`, `experiment_config.py`, `example_contract.py`)
- [ ] `scripts/run_pre_eval_gate.py`, `scripts/verify_phase6_prompts.py`, `scripts/write_freeze_lock.py`
- [ ] `tests/test_phase6_*.py`
- [ ] `results/phase6/*` gate + experiment JSON (no `freeze_lock.json` yet)
- [ ] `results/pricing_snapshot.json`
- [ ] `docs/phase6-*.md` (including this handoff)
- [ ] `.env.example`, `.gitignore` (docs/Plans trackable)
- [ ] `data/manifest.json` (already tracked; confirm unchanged)

Exclude:

- [ ] `.env`, API keys, absolute host paths
- [ ] `__pycache__/`, evaluation example/ranking/metric outputs
- [ ] regenerable `data/tests/**/representations/`, checkouts

Then:

```bash
git tag -a experiment-v1-frozen -m "Freeze preregistered jev-ci experiment v1"
git rev-parse experiment-v1-frozen   # record in this handoff
python scripts/write_freeze_lock.py  # unlock evaluation for Phase 7
```
