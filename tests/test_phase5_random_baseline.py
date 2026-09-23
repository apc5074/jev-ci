"""P5-03: seeded Random baseline — permutations, seeds, reproducibility."""

from __future__ import annotations

import json
import random
import tempfile
import unittest
from pathlib import Path

from src.example_contract import ExampleId, load_manifest
from src.random_baseline import (
    DEVELOPMENT_SEED_BASE,
    EVALUATION_SEED_BASE,
    INDEX_BASIS,
    NUM_PERMUTATIONS,
    RandomBaselineError,
    bug_index_for,
    build_contract,
    evaluation_example_ids,
    generate_and_save,
    generate_permutations,
    load_inventory_test_classes,
    permutations_fingerprint,
    regenerate_from_contract,
    resolve_bug_seed,
    seed_for_index,
    test_class_ids_sha256,
    verify_permutation,
)

_REPO = Path(__file__).resolve().parents[1]
_DATA = _REPO / "data"
_MANIFEST_PATH = _DATA / "manifest.json"
_HAS_DEV_INVENTORY = (_DATA / "tests" / "Cli_30" / "inventory.json").is_file()


def _load_manifest() -> dict:
    with _MANIFEST_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


class IndexAndSeedConventionTests(unittest.TestCase):
    def test_index_basis_is_zero_based(self) -> None:
        self.assertEqual(INDEX_BASIS, "zero-based")

    def test_evaluation_seed_matches_overall_formula(self) -> None:
        self.assertEqual(seed_for_index(split="evaluation", bug_index=0), 1337)
        self.assertEqual(seed_for_index(split="evaluation", bug_index=7), 1344)
        self.assertEqual(
            seed_for_index(split="evaluation", bug_index=124),
            EVALUATION_SEED_BASE + 124,
        )

    def test_development_seeds_disjoint_from_evaluation(self) -> None:
        eval_seeds = {
            seed_for_index(split="evaluation", bug_index=i) for i in range(125)
        }
        dev_seeds = {
            seed_for_index(split="development", bug_index=i) for i in range(25)
        }
        self.assertTrue(eval_seeds.isdisjoint(dev_seeds))
        self.assertEqual(min(dev_seeds), DEVELOPMENT_SEED_BASE)
        self.assertEqual(max(eval_seeds), EVALUATION_SEED_BASE + 124)

    def test_manifest_evaluation_index_order(self) -> None:
        manifest = _load_manifest()
        ids = evaluation_example_ids(manifest)
        self.assertEqual(len(ids), 125)
        first = ids[0]
        self.assertEqual(bug_index_for(first, split="evaluation", manifest=manifest), 0)
        seed = resolve_bug_seed(first, split="evaluation", manifest=manifest)
        self.assertEqual(seed.seed, EVALUATION_SEED_BASE)
        self.assertEqual(seed.bug_index, 0)
        self.assertEqual(seed.index_basis, "zero-based")

        tenth = ids[9]
        self.assertEqual(bug_index_for(tenth, split="evaluation", manifest=manifest), 9)
        self.assertEqual(
            resolve_bug_seed(tenth, split="evaluation", manifest=manifest).seed,
            EVALUATION_SEED_BASE + 9,
        )

    def test_manifest_development_index_order(self) -> None:
        manifest = _load_manifest()
        from src.example_contract import development_example_ids

        ids = development_example_ids(manifest)
        self.assertEqual(len(ids), 25)
        first = ids[0]
        self.assertEqual(
            resolve_bug_seed(first, split="development", manifest=manifest).seed,
            DEVELOPMENT_SEED_BASE,
        )


class PermutationGeneratorTests(unittest.TestCase):
    def test_each_permutation_is_full_suite(self) -> None:
        classes = ["c.C", "a.A", "b.B", "d.D"]
        perms = generate_permutations(classes, seed=42, count=50)
        self.assertEqual(len(perms), 50)
        for perm in perms:
            verify_permutation(perm, test_classes=classes)

    def test_repeated_runs_identical(self) -> None:
        classes = [f"t.T{i}" for i in range(12)]
        a = generate_permutations(classes, seed=1337, count=100)
        b = generate_permutations(classes, seed=1337, count=100)
        self.assertEqual(a, b)
        self.assertEqual(permutations_fingerprint(a), permutations_fingerprint(b))

    def test_matches_hand_rolled_continuous_shuffle(self) -> None:
        classes = ["x.X", "y.Y", "z.Z"]
        seed = 9001
        expected: list[list[str]] = []
        rng = random.Random(seed)
        for _ in range(20):
            perm = classes.copy()
            rng.shuffle(perm)
            expected.append(perm)
        got = generate_permutations(classes, seed=seed, count=20)
        self.assertEqual(got, expected)

    def test_different_seeds_diverge(self) -> None:
        classes = [f"t.T{i}" for i in range(20)]
        a = generate_permutations(classes, seed=1, count=5)
        b = generate_permutations(classes, seed=2, count=5)
        self.assertNotEqual(a, b)

    def test_rejects_duplicates(self) -> None:
        with self.assertRaises(RandomBaselineError):
            generate_permutations(["a.A", "a.A"], seed=1, count=1)


class ContractTests(unittest.TestCase):
    def test_build_and_regenerate(self) -> None:
        from src.random_baseline import BugSeed

        classes = ["p.P", "q.Q", "r.R"]
        bug_seed = BugSeed(
            example_id="Toy_1",
            qualified_id="Toy-1",
            split="development",
            bug_index=0,
            index_basis=INDEX_BASIS,
            seed=DEVELOPMENT_SEED_BASE,
            seed_base=DEVELOPMENT_SEED_BASE,
        )
        contract = build_contract(bug_seed=bug_seed, test_classes=classes)
        self.assertEqual(contract["num_permutations"], NUM_PERMUTATIONS)
        self.assertEqual(contract["N"], 3)
        self.assertEqual(contract["test_class_ids_sha256"], test_class_ids_sha256(classes))
        self.assertNotIn("positive_classes", contract)
        self.assertNotIn("trigger_methods", contract)
        regenerated = regenerate_from_contract(contract, test_classes=classes)
        self.assertEqual(len(regenerated), NUM_PERMUTATIONS)
        self.assertEqual(regenerated[0], contract["first_permutation"])
        self.assertEqual(regenerated[-1], contract["last_permutation"])

    def test_stale_inventory_fails_regeneration(self) -> None:
        from src.random_baseline import BugSeed

        classes = ["a.A", "b.B"]
        bug_seed = BugSeed(
            example_id="Toy_1",
            qualified_id="Toy-1",
            split="development",
            bug_index=0,
            index_basis=INDEX_BASIS,
            seed=1,
            seed_base=DEVELOPMENT_SEED_BASE,
        )
        contract = build_contract(bug_seed=bug_seed, test_classes=classes)
        with self.assertRaises(RandomBaselineError):
            regenerate_from_contract(contract, test_classes=["a.A", "b.B", "c.C"])


@unittest.skipUnless(_HAS_DEV_INVENTORY, "development inventories not present")
class DevelopmentInventorySmokeTests(unittest.TestCase):
    def test_cli30_load_and_save_contract(self) -> None:
        # Use repo-local data_root; results go to a temp dir (WORKSPACE is /workspace).
        manifest = _load_manifest()
        ex = ExampleId.parse("Cli-30")
        classes = load_inventory_test_classes(ex, data_root=_DATA)
        self.assertGreaterEqual(len(classes), 2)
        self.assertEqual(len(classes), len(set(classes)))

        with tempfile.TemporaryDirectory() as tmp:
            results = Path(tmp)
            contract, outcome = generate_and_save(
                ex,
                split="development",
                manifest=manifest,
                data_root=_DATA,
                results_root=results,
            )
            self.assertIn(outcome.value, {"written", "reused", "regenerated"})
            self.assertEqual(contract["qualified_id"], "Cli-30")
            self.assertEqual(contract["seed"], DEVELOPMENT_SEED_BASE)  # first dev id
            path = results / "Cli_30.json"
            self.assertTrue(path.is_file())
            # Reuse path
            _, outcome2 = generate_and_save(
                ex,
                split="development",
                manifest=manifest,
                data_root=_DATA,
                results_root=results,
            )
            self.assertEqual(outcome2.value, "reused")
            regenerate_from_contract(contract, test_classes=classes)

    def test_never_requires_labels(self) -> None:
        # Generation only needs inventory; labels may be absent in a stripped tree.
        ex = ExampleId.parse("Cli-30")
        classes = load_inventory_test_classes(ex, data_root=_DATA)
        perms = generate_permutations(classes, seed=DEVELOPMENT_SEED_BASE, count=3)
        for perm in perms:
            verify_permutation(perm, test_classes=classes)


if __name__ == "__main__":
    unittest.main()
