# Deterministic bug selection (Phase 2)

Sampling and development/evaluation split. Implemented by `select_bugs()` in `src/select_bugs.py`. Active-ID loading is documented in [active-bugs.md](active-bugs.md).

## Identifier convention

| Form | Example | Where used |
| --- | --- | --- |
| Bare Defects4J bug id | `7` | Per-project active lists and per-project `selected_ids` |
| Project-qualified id | `Cli-7` | Combined `development_bug_ids` / `evaluation_bug_ids` |

Always treat bare IDs as **strings**. Never coerce to integers for sorting or sampling.

## Algorithm

Exactly as in `overall.md`:

```python
rng = random.Random(20260922)  # once
for project in ["Cli", "Lang", "Math", "Jsoup", "JacksonDatabind"]:
    selected = rng.sample(sorted(active_bug_ids), 30)  # string sorted(); keep sample order
    development = selected[:5]   # positions 1–5
    evaluation = selected[5:]    # positions 6–30
```

Rules:

- One RNG instance; do not reseed between projects.
- `sorted(active_bug_ids)` is lexicographic on strings (`"10"` before `"2"`).
- Do **not** sort the 30 sampled IDs afterward; sample order defines the split.
- Selection is a pure function of the five active-ID lists and the seed. It must not depend on filesystem order, timezone, hash randomization, or existing manifest files.

## Counts

| Scope | Development | Evaluation | Selected |
| --- | ---: | ---: | ---: |
| Per project | 5 | 25 | 30 |
| Overall | 25 | 125 | 150 |

All 150 project-qualified IDs must be unique (`Lang-1` ≠ `Math-1`).

## Command

Preview the live selection inside the Phase 1 container (does not write a manifest):

```bash
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" \
  -w /workspace \
  jev-ci:phase1 \
  python src/select_bugs.py sample
```

JSON form:

```bash
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" \
  -w /workspace \
  jev-ci:phase1 \
  python src/select_bugs.py sample --json
```
