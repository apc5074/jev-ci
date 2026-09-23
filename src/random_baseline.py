"""Seeded Random baseline: 1,000 full-suite permutations per bug (Phase 5 / P5-03).

Evaluation seed rule (frozen intent from overall.md §15; index basis chosen here
for Phase 6 preregistration):

    random.Random(1337 + evaluation_bug_index)

where ``evaluation_bug_index`` is the **zero-based** position of the bug in
``manifest["evaluation_bug_ids"]`` (locked Phase 2 order).

Development uses a disjoint seed namespace so it cannot collide with evaluation
seeds ``1337 .. 1337+124``:

    random.Random(1001337 + development_bug_index)

with ``development_bug_index`` zero-based in ``manifest["development_bug_ids"]``.

Generator contract: one continuous ``random.Random(seed)`` instance; for each of
1,000 iterations, copy the inventory ``test_classes`` list and ``shuffle`` it.
Positive labels are never read. Artifacts store the seed contract and a content
fingerprint of the 1,000 permutations; full lists are regenerated on demand.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.example_contract import (
    WORKSPACE,
    ExampleContractError,
    ExampleId,
    PRIVATE_LABEL_FIELDS,
    assert_no_private_fields,
    atomic_write_json,
    development_example_ids,
    example_paths,
    load_manifest,
    read_json,
    require_manifest_membership,
)

# --- Preregistration constants (do not change after Phase 6 freeze) ---

NUM_PERMUTATIONS = 1000

# overall.md §15 — evaluation only.
EVALUATION_SEED_BASE = 1337

# Disjoint development namespace: evaluation seeds occupy
# [1337, 1337 + 124] inclusive for 125 evaluation bugs.
DEVELOPMENT_SEED_BASE = 1_001_337

# Zero-based index into the locked manifest split lists.
INDEX_BASIS = "zero-based"

RANDOM_BASELINE_VERSION = "jev-random-baseline-v1"
GENERATOR_CONTRACT = (
    "continuous_Random_shuffle_inventory_order_x1000"
)

RANDOM_ROOT = WORKSPACE / "results" / "random"
SCHEMA_VERSION = "jev-random-contract-v1"


class RandomBaselineError(Exception):
    """Invalid seed, inventory, or Random contract."""


class SaveOutcome(str, Enum):
    WRITTEN = "written"
    REUSED = "reused"
    REGENERATED = "regenerated"


@dataclass(frozen=True)
class BugSeed:
    """Resolved seed for one bug under the frozen index convention."""

    example_id: str
    qualified_id: str
    split: str
    bug_index: int
    index_basis: str
    seed: int
    seed_base: int


def evaluation_example_ids(
    manifest: Mapping[str, Any] | None = None,
) -> tuple[ExampleId, ...]:
    """Return evaluation ExampleIds from the locked manifest (never resample)."""
    data = manifest if manifest is not None else load_manifest()
    ids = data.get("evaluation_bug_ids")
    if not isinstance(ids, list) or not ids:
        raise ExampleContractError("manifest.evaluation_bug_ids missing or empty")
    development = set(data.get("development_bug_ids") or [])
    out: list[ExampleId] = []
    seen: set[str] = set()
    for raw in ids:
        ex = ExampleId.parse(str(raw))
        if ex.qualified in development:
            raise ExampleContractError(
                f"{ex.qualified} is listed as both development and evaluation"
            )
        if ex.qualified in seen:
            raise ExampleContractError(f"duplicate evaluation id {ex.qualified}")
        seen.add(ex.qualified)
        out.append(ex)
    if len(out) != 125:
        raise ExampleContractError(
            f"expected 125 evaluation ids, found {len(out)}"
        )
    return tuple(out)


def bug_index_for(
    example: ExampleId | str,
    *,
    split: str,
    manifest: Mapping[str, Any] | None = None,
) -> int:
    """Zero-based index of ``example`` in the locked split list."""
    ex = example if isinstance(example, ExampleId) else ExampleId.parse(example)
    data = manifest if manifest is not None else load_manifest()
    if split == "development":
        ids = development_example_ids(data)
    elif split == "evaluation":
        ids = evaluation_example_ids(data)
    else:
        raise RandomBaselineError(f"unknown split: {split!r}")
    for i, other in enumerate(ids):
        if other.qualified == ex.qualified:
            return i
    raise RandomBaselineError(
        f"{ex.qualified} not found in manifest {split}_bug_ids"
    )


def seed_for_index(*, split: str, bug_index: int) -> int:
    """Map split + zero-based index to the preregistered RNG seed."""
    if bug_index < 0:
        raise RandomBaselineError(f"bug_index must be >= 0, got {bug_index}")
    if split == "evaluation":
        return EVALUATION_SEED_BASE + bug_index
    if split == "development":
        return DEVELOPMENT_SEED_BASE + bug_index
    raise RandomBaselineError(f"unknown split: {split!r}")


def resolve_bug_seed(
    example: ExampleId | str,
    *,
    split: str,
    manifest: Mapping[str, Any] | None = None,
) -> BugSeed:
    ex = example if isinstance(example, ExampleId) else ExampleId.parse(example)
    data = manifest if manifest is not None else load_manifest()
    require_manifest_membership(
        ex,
        manifest=data,
        allow_evaluation=(split == "evaluation"),
    )
    index = bug_index_for(ex, split=split, manifest=data)
    base = (
        EVALUATION_SEED_BASE if split == "evaluation" else DEVELOPMENT_SEED_BASE
    )
    return BugSeed(
        example_id=ex.slug,
        qualified_id=ex.qualified,
        split=split,
        bug_index=index,
        index_basis=INDEX_BASIS,
        seed=seed_for_index(split=split, bug_index=index),
        seed_base=base,
    )


def test_class_ids_sha256(test_classes: Sequence[str]) -> str:
    payload = "\n".join(test_classes).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def permutations_fingerprint(permutations: Sequence[Sequence[str]]) -> str:
    """Stable digest of an ordered list of permutations (regeneration check)."""
    hasher = hashlib.sha256()
    for perm in permutations:
        hasher.update("\0".join(perm).encode("utf-8"))
        hasher.update(b"\n")
    return hasher.hexdigest()


def generate_permutations(
    test_classes: Sequence[str],
    *,
    seed: int,
    count: int = NUM_PERMUTATIONS,
) -> list[list[str]]:
    """Return ``count`` independent full-suite permutations.

    Uses one continuous ``random.Random(seed)``. Each iteration copies the
    inventory order then ``shuffle``s. Never consults labels.
    """
    if count < 1:
        raise RandomBaselineError(f"count must be >= 1, got {count}")
    base = list(test_classes)
    if not base:
        raise RandomBaselineError("test_classes is empty")
    if len(base) != len(set(base)):
        raise RandomBaselineError("test_classes contains duplicates")
    rng = random.Random(seed)
    out: list[list[str]] = []
    for _ in range(count):
        perm = base.copy()
        rng.shuffle(perm)
        out.append(perm)
    return out


def load_inventory_test_classes(
    example: ExampleId | str,
    *,
    data_root: Path | None = None,
) -> list[str]:
    """Load model-visible inventory class IDs; reject private label leakage."""
    ex = example if isinstance(example, ExampleId) else ExampleId.parse(example)
    paths = example_paths(ex, data_root=data_root)
    inv_path = paths["test_inventory"]
    if not inv_path.is_file():
        raise RandomBaselineError(f"missing inventory: {inv_path}")
    inventory = read_json(inv_path)
    assert_no_private_fields(inventory, context=f"{ex.qualified} inventory")
    leaked = PRIVATE_LABEL_FIELDS.intersection(inventory.keys())
    if leaked:
        raise RandomBaselineError(
            f"{ex.qualified}: private fields in inventory: {sorted(leaked)}"
        )
    # Never open labels.json for ranking generation.
    test_classes = inventory.get("test_classes")
    if not isinstance(test_classes, list) or not test_classes:
        raise RandomBaselineError(
            f"{ex.qualified}: inventory.test_classes missing or empty"
        )
    if any(not isinstance(c, str) or not c for c in test_classes):
        raise RandomBaselineError(
            f"{ex.qualified}: inventory.test_classes has non-string entries"
        )
    if len(test_classes) != len(set(test_classes)):
        raise RandomBaselineError(
            f"{ex.qualified}: inventory.test_classes has duplicates"
        )
    return list(test_classes)


def verify_permutation(
    permutation: Sequence[str],
    *,
    test_classes: Sequence[str],
) -> None:
    """Each permutation must contain every inventory class exactly once."""
    if len(permutation) != len(test_classes):
        raise RandomBaselineError(
            f"permutation length {len(permutation)} != N={len(test_classes)}"
        )
    if len(permutation) != len(set(permutation)):
        raise RandomBaselineError("permutation contains duplicate class IDs")
    if set(permutation) != set(test_classes):
        missing = sorted(set(test_classes) - set(permutation))
        extra = sorted(set(permutation) - set(test_classes))
        raise RandomBaselineError(
            f"permutation is not a full-suite ordering "
            f"(missing={missing[:5]}, extra={extra[:5]})"
        )


def contract_path(
    example: ExampleId | str,
    *,
    results_root: Path | None = None,
) -> Path:
    ex = example if isinstance(example, ExampleId) else ExampleId.parse(example)
    root = results_root if results_root is not None else RANDOM_ROOT
    return root / f"{ex.slug}.json"


def build_contract(
    *,
    bug_seed: BugSeed,
    test_classes: Sequence[str],
    permutations: Sequence[Sequence[str]] | None = None,
    inventory_sha256: str | None = None,
) -> dict[str, Any]:
    """Build the reproducible Random contract document (no full perm lists)."""
    classes = list(test_classes)
    for i, perm in enumerate(permutations or []):
        verify_permutation(perm, test_classes=classes)
    if permutations is None:
        permutations = generate_permutations(classes, seed=bug_seed.seed)
        for perm in permutations:
            verify_permutation(perm, test_classes=classes)
    else:
        if len(permutations) != NUM_PERMUTATIONS:
            raise RandomBaselineError(
                f"expected {NUM_PERMUTATIONS} permutations, got {len(permutations)}"
            )

    first = list(permutations[0])
    last = list(permutations[-1])
    return {
        "schema_version": SCHEMA_VERSION,
        "random_baseline_version": RANDOM_BASELINE_VERSION,
        "example_id": bug_seed.example_id,
        "qualified_id": bug_seed.qualified_id,
        "split": bug_seed.split,
        "bug_index": bug_seed.bug_index,
        "index_basis": bug_seed.index_basis,
        "seed": bug_seed.seed,
        "seed_base": bug_seed.seed_base,
        "seed_rule": (
            f"{bug_seed.split}: {bug_seed.seed_base} + {bug_seed.split}_bug_index "
            f"({bug_seed.index_basis})"
        ),
        "generator_contract": GENERATOR_CONTRACT,
        "num_permutations": NUM_PERMUTATIONS,
        "N": len(classes),
        "test_class_ids_sha256": test_class_ids_sha256(classes),
        "inventory_sha256": inventory_sha256,
        "permutations_sha256": permutations_fingerprint(permutations),
        "first_permutation": first,
        "last_permutation": last,
        "settings": {
            "evaluation_seed_base": EVALUATION_SEED_BASE,
            "development_seed_base": DEVELOPMENT_SEED_BASE,
            "index_basis": INDEX_BASIS,
            "num_permutations": NUM_PERMUTATIONS,
            "stores_full_permutations": False,
            "regeneration": (
                "generate_permutations(inventory.test_classes, seed=seed, "
                f"count={NUM_PERMUTATIONS})"
            ),
        },
    }


def regenerate_from_contract(
    contract: Mapping[str, Any],
    *,
    test_classes: Sequence[str],
) -> list[list[str]]:
    """Rebuild the 1,000 permutations and verify against the stored fingerprint."""
    seed = contract.get("seed")
    if not isinstance(seed, int):
        raise RandomBaselineError("contract.seed missing or not int")
    expected_n = contract.get("N")
    if expected_n != len(test_classes):
        raise RandomBaselineError(
            f"N mismatch: contract={expected_n}, inventory={len(test_classes)}"
        )
    stored_ids_hash = contract.get("test_class_ids_sha256")
    computed_ids_hash = test_class_ids_sha256(test_classes)
    if stored_ids_hash != computed_ids_hash:
        raise RandomBaselineError(
            "test_class_ids_sha256 mismatch; inventory order/content changed"
        )
    perms = generate_permutations(test_classes, seed=seed)
    for perm in perms:
        verify_permutation(perm, test_classes=test_classes)
    digest = permutations_fingerprint(perms)
    expected = contract.get("permutations_sha256")
    if digest != expected:
        raise RandomBaselineError(
            f"permutations_sha256 mismatch (stored={expected!r}, got={digest!r})"
        )
    if list(perms[0]) != list(contract.get("first_permutation") or []):
        raise RandomBaselineError("first_permutation mismatch after regeneration")
    if list(perms[-1]) != list(contract.get("last_permutation") or []):
        raise RandomBaselineError("last_permutation mismatch after regeneration")
    return perms


def _inventory_file_sha256(
    example: ExampleId,
    *,
    data_root: Path | None = None,
) -> str:
    path = example_paths(example, data_root=data_root)["test_inventory"]
    return hashlib.sha256(path.read_bytes()).hexdigest()


def generate_and_save(
    example: ExampleId | str,
    *,
    split: str,
    manifest: Mapping[str, Any] | None = None,
    data_root: Path | None = None,
    results_root: Path | None = None,
    force: bool = False,
) -> tuple[dict[str, Any], SaveOutcome]:
    """Create or reuse the Random seed contract for one bug."""
    ex = example if isinstance(example, ExampleId) else ExampleId.parse(example)
    data = manifest if manifest is not None else load_manifest()
    bug_seed = resolve_bug_seed(ex, split=split, manifest=data)
    test_classes = load_inventory_test_classes(ex, data_root=data_root)
    inv_hash = _inventory_file_sha256(ex, data_root=data_root)
    contract = build_contract(
        bug_seed=bug_seed,
        test_classes=test_classes,
        inventory_sha256=inv_hash,
    )
    assert_no_private_fields(contract, context=f"random contract {ex.qualified}")

    path = contract_path(ex, results_root=results_root)
    if path.is_file() and not force:
        existing = read_json(path)
        if (
            existing.get("schema_version") == contract["schema_version"]
            and existing.get("seed") == contract["seed"]
            and existing.get("bug_index") == contract["bug_index"]
            and existing.get("permutations_sha256")
            == contract["permutations_sha256"]
            and existing.get("test_class_ids_sha256")
            == contract["test_class_ids_sha256"]
            and existing.get("inventory_sha256") == contract["inventory_sha256"]
        ):
            return existing, SaveOutcome.REUSED
        outcome = SaveOutcome.REGENERATED
    else:
        outcome = SaveOutcome.WRITTEN

    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, contract)
    return contract, outcome


def load_contract(
    example: ExampleId | str,
    *,
    results_root: Path | None = None,
) -> dict[str, Any]:
    path = contract_path(example, results_root=results_root)
    if not path.is_file():
        raise RandomBaselineError(f"missing Random contract: {path}")
    doc = read_json(path)
    assert_no_private_fields(doc, context=f"random contract {path.name}")
    return doc


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate or verify the seeded Random baseline contract for one bug."
        )
    )
    parser.add_argument("example_id", help="Qualified id, e.g. Cli-30")
    parser.add_argument(
        "--split",
        choices=("development", "evaluation"),
        default="development",
    )
    parser.add_argument(
        "--allow-evaluation",
        action="store_true",
        help="Required with --split evaluation (post Phase-6 freeze).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing contract even when hashes match.",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Regenerate permutations from the saved contract and exit.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.split == "evaluation" and not args.allow_evaluation:
        raise SystemExit(
            "--split evaluation requires --allow-evaluation "
            "(reserved until the Phase 6 design freeze)"
        )

    ex = ExampleId.parse(args.example_id)
    if args.verify_only:
        contract = load_contract(ex)
        classes = load_inventory_test_classes(ex)
        regenerate_from_contract(contract, test_classes=classes)
        print(
            json.dumps(
                {
                    "qualified_id": ex.qualified,
                    "verified": True,
                    "seed": contract["seed"],
                    "num_permutations": contract["num_permutations"],
                    "permutations_sha256": contract["permutations_sha256"],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    contract, outcome = generate_and_save(
        ex,
        split=args.split,
        force=args.force,
    )
    print(
        json.dumps(
            {
                "qualified_id": ex.qualified,
                "outcome": outcome.value,
                "seed": contract["seed"],
                "bug_index": contract["bug_index"],
                "N": contract["N"],
                "num_permutations": contract["num_permutations"],
                "permutations_sha256": contract["permutations_sha256"],
                "path": str(contract_path(ex).relative_to(WORKSPACE)),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
