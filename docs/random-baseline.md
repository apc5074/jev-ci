# Random baseline (Phase 5 / P5-03)

1,000 independent full-suite test-class permutations per bug.
Implementation: [`src/random_baseline.py`](../src/random_baseline.py).

## Seed and index convention (ready for Phase 6 preregistration)

| Split | Index | Seed |
| --- | --- | --- |
| **Evaluation** | Zero-based position in locked `manifest["evaluation_bug_ids"]` | `1337 + evaluation_bug_index` |
| **Development** | Zero-based position in locked `manifest["development_bug_ids"]` | `1001337 + development_bug_index` |

**Index basis:** `zero-based` (first bug in the list is index `0`).

Evaluation seeds therefore occupy `[1337, 1461]` for the 125 evaluation bugs.
Development seeds occupy `[1001337, 1001361]` and never overlap evaluation.

Do not change the evaluation formula `1337 + evaluation_bug_index`. The
development base exists only so Phase 5 can exercise the same generator without
colliding with final evaluation seeds.

## Generator contract

```python
rng = random.Random(seed)
for _ in range(1000):
    perm = list(inventory["test_classes"])  # inventory order, not labels
    rng.shuffle(perm)
    # perm is one full-suite ranking
```

- One continuous `random.Random(seed)` across all 1,000 shuffles.
- Base order is `inventory.json` → `test_classes` (model-visible).
- Positive labels / `labels.json` are never read.
- Phase 8 averages metrics over all 1,000 rankings; it does not pick a lucky
  permutation.

## Artifacts

| Path | Contents |
| --- | --- |
| `results/random/<project>_<bug>.json` | Seed contract + permutation fingerprint |
| `results/random_baseline_summary.json` | Batch run summary |

Contracts **do not** store all 1,000 full lists (N can exceed 400). They store:

- `seed`, `bug_index`, `index_basis`, `seed_rule`
- `test_class_ids_sha256`, `inventory_sha256`
- `permutations_sha256` (digest of the regenerated 1,000 perms)
- `first_permutation` / `last_permutation` for spot checks

Regenerate anytime:

```python
from src.random_baseline import (
    generate_permutations,
    load_contract,
    load_inventory_test_classes,
    regenerate_from_contract,
)

contract = load_contract("Cli-30")
classes = load_inventory_test_classes("Cli-30")
perms = regenerate_from_contract(contract, test_classes=classes)
# or: generate_permutations(classes, seed=contract["seed"])
```

## Commands

```bash
# One development bug
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace jev-ci:phase1 \
  python src/random_baseline.py Cli-30 --split development

# All 25 development bugs
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace jev-ci:phase1 \
  python scripts/run_random_baseline.py --split development

# Verify regeneration matches stored fingerprints
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/workspace" -w /workspace jev-ci:phase1 \
  python scripts/run_random_baseline.py --split development --verify
```

Evaluation generation requires `--allow-evaluation` and is reserved until the
Phase 6 design freeze.
