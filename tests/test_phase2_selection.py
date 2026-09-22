"""Phase 2 selection and manifest integrity tests (stdlib unittest).

Run inside the Phase 1 container from the repository root:

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import random
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.select_bugs import (
    DEVELOPMENT_PER_PROJECT,
    EVALUATION_PER_PROJECT,
    PROJECT_ORDER,
    SAMPLE_SIZE,
    SELECTION_SEED,
    ActiveBugCatalog,
    ActiveIdError,
    ManifestCorruptionError,
    ManifestDriftError,
    ProjectActiveIds,
    build_manifest,
    check_manifest_upstream_drift,
    content_hash,
    create_manifest_file,
    qualify_bug_id,
    select_bugs,
    select_bugs_raw,
    serialize_manifest,
    validate_active_ids,
    verify_manifest_file,
    verify_manifest_integrity,
    write_manifest_atomic,
)


def synthetic_active_ids(prefix: str, count: int = 35) -> list[str]:
    """Build string IDs where lexicographic order differs from numeric order."""
    # Include multi-digit values so sorted(... ) != sorted(..., key=int).
    ids = [str(i) for i in range(1, count + 1)]
    # Ensure "10" sorts before "2" lexicographically when both present.
    assert "10" in ids and "2" in ids
    random.Random(hash(prefix) & 0xFFFFFFFF).shuffle(ids)
    return ids


def synthetic_active_lists() -> dict[str, list[str]]:
    return {project: synthetic_active_ids(project) for project in PROJECT_ORDER}


def synthetic_catalog(active_lists: dict[str, list[str]]) -> ActiveBugCatalog:
    projects = []
    for project in PROJECT_ORDER:
        bug_ids = tuple(validate_active_ids(project, active_lists[project]))
        projects.append(
            ProjectActiveIds(
                project=project,
                bug_ids=bug_ids,
                content_sha256=content_hash(bug_ids),
                source_command=f"defects4j bids -p {project}",
            )
        )
    return ActiveBugCatalog(
        defects4j_version="3.0.1",
        defects4j_commit="6d54320e0db5a357f9ab38a8e4d2e5aead7e1c09",
        d4j_home="/opt/defects4j",
        projects=tuple(projects),
        metadata_source="test",
    )


def synthetic_environment() -> dict:
    return {
        "python_version": "3.12.14",
        "java_version": "11.0.32.1",
        "os": "Ubuntu 22.04.5 LTS",
        "architecture": "x86_64",
        "timezone": "America/Los_Angeles",
        "defects4j_version": "3.0.1",
        "defects4j_commit": "6d54320e0db5a357f9ab38a8e4d2e5aead7e1c09",
        "checked_at": "2026-09-22T00:00:00+00:00",
    }


class TestDeterministicSampling(unittest.TestCase):
    def test_matches_independent_random_sample_algorithm(self) -> None:
        active = synthetic_active_lists()
        result = select_bugs(active)

        rng = random.Random(SELECTION_SEED)
        expected_qualified: list[str] = []
        for project in PROJECT_ORDER:
            selected = rng.sample(sorted(active[project]), SAMPLE_SIZE)
            self.assertEqual(list(result.projects[PROJECT_ORDER.index(project)].selected_ids), selected)
            self.assertEqual(selected[:DEVELOPMENT_PER_PROJECT], list(
                result.projects[PROJECT_ORDER.index(project)].development_ids
            ))
            expected_qualified.extend(qualify_bug_id(project, bug_id) for bug_id in selected)

        self.assertEqual(list(result.all_qualified_ids), expected_qualified)
        self.assertEqual(len(result.development_bug_ids), 25)
        self.assertEqual(len(result.evaluation_bug_ids), 125)

    def test_continuous_rng_differs_from_reseed_each_project(self) -> None:
        active = synthetic_active_lists()
        continuous = select_bugs(active)

        reseeded: list[str] = []
        for project in PROJECT_ORDER:
            selected = random.Random(SELECTION_SEED).sample(sorted(active[project]), SAMPLE_SIZE)
            reseeded.extend(qualify_bug_id(project, bug_id) for bug_id in selected)

        self.assertNotEqual(list(continuous.all_qualified_ids), reseeded)

    def test_lexicographic_string_sort_not_numeric(self) -> None:
        ids = [str(i) for i in range(1, 40)]
        string_sorted = sorted(ids)
        numeric_sorted = [str(i) for i in sorted(map(int, ids))]
        self.assertNotEqual(string_sorted, numeric_sorted)

        active = {project: list(ids) for project in PROJECT_ORDER}
        result = select_bugs(active)

        rng = random.Random(SELECTION_SEED)
        for entry in result.projects:
            expected = rng.sample(string_sorted, SAMPLE_SIZE)
            self.assertEqual(list(entry.selected_ids), expected)

        # A numeric-sorted population with the same seed yields a different first draw.
        numeric_first = random.Random(SELECTION_SEED).sample(numeric_sorted, SAMPLE_SIZE)
        self.assertNotEqual(list(result.projects[0].selected_ids), numeric_first)

    def test_shuffled_input_order_stable(self) -> None:
        active = synthetic_active_lists()
        shuffled = {p: list(reversed(ids)) for p, ids in active.items()}
        a = select_bugs(active)
        b = select_bugs(shuffled)
        self.assertEqual(a.all_qualified_ids, b.all_qualified_ids)
        self.assertEqual(a.development_bug_ids, b.development_bug_ids)

    def test_first_five_are_development(self) -> None:
        result = select_bugs(synthetic_active_lists())
        for entry in result.projects:
            self.assertEqual(entry.development_ids, entry.selected_ids[:5])
            self.assertEqual(entry.evaluation_ids, entry.selected_ids[5:])
            self.assertEqual(len(entry.development_ids), DEVELOPMENT_PER_PROJECT)
            self.assertEqual(len(entry.evaluation_ids), EVALUATION_PER_PROJECT)


class TestManifestIntegrity(unittest.TestCase):
    def _valid_manifest(self) -> dict:
        active = synthetic_active_lists()
        catalog = synthetic_catalog(active)
        selection = select_bugs(active)
        return build_manifest(
            catalog,
            selection,
            environment=synthetic_environment(),
            created_at="2026-09-22T00:00:00+00:00",
            git_commit="deadbeef",
        )

    def test_valid_manifest_passes(self) -> None:
        verify_manifest_integrity(self._valid_manifest())

    def test_too_few_active_bugs(self) -> None:
        with self.assertRaises(ActiveIdError):
            validate_active_ids("Cli", [str(i) for i in range(1, 20)])

    def test_duplicate_active_ids(self) -> None:
        with self.assertRaises(ActiveIdError):
            validate_active_ids("Cli", ["1", "2", "1"] + [str(i) for i in range(3, 35)])

    def test_wrong_project_membership(self) -> None:
        manifest = self._valid_manifest()
        # Inject an id that is not in the recorded active set.
        manifest["projects"]["Cli"]["selected_ids"][0] = "99999"
        manifest["projects"]["Cli"]["development_ids"][0] = "99999"
        manifest["projects"]["Cli"]["selected_qualified_ids"][0] = "Cli-99999"
        manifest["projects"]["Cli"]["development_qualified_ids"][0] = "Cli-99999"
        with self.assertRaises(ManifestCorruptionError) as ctx:
            verify_manifest_integrity(manifest)
        self.assertIn("projects.Cli", str(ctx.exception))

    def test_mismatched_combined_lists(self) -> None:
        manifest = self._valid_manifest()
        manifest["development_bug_ids"] = list(reversed(manifest["development_bug_ids"]))
        with self.assertRaises(ManifestCorruptionError) as ctx:
            verify_manifest_integrity(manifest)
        self.assertIn("development_bug_ids", str(ctx.exception))

    def test_changed_seed(self) -> None:
        manifest = self._valid_manifest()
        manifest["selection_seed"] = 1
        with self.assertRaises(ManifestCorruptionError) as ctx:
            verify_manifest_integrity(manifest)
        self.assertIn("selection_seed", str(ctx.exception))

    def test_wrong_split_positions(self) -> None:
        manifest = self._valid_manifest()
        sel = manifest["projects"]["Lang"]["selected_ids"]
        sel[0], sel[5] = sel[5], sel[0]
        with self.assertRaises(ManifestCorruptionError) as ctx:
            verify_manifest_integrity(manifest)
        self.assertIn("projects.Lang.development_ids", str(ctx.exception))

    def test_changed_active_set_snapshot_hash(self) -> None:
        manifest = self._valid_manifest()
        manifest["projects"]["Math"]["active_content_sha256"] = "0" * 64
        with self.assertRaises(ManifestCorruptionError) as ctx:
            verify_manifest_integrity(manifest)
        self.assertIn("active_content_sha256", str(ctx.exception))

    def test_upstream_commit_drift(self) -> None:
        manifest = self._valid_manifest()
        manifest["defects4j_commit"] = "0" * 40
        fake_catalog = synthetic_catalog(synthetic_active_lists())
        with mock.patch(
            "src.select_bugs.load_active_bug_catalog",
            return_value=fake_catalog,
        ):
            with self.assertRaises(ManifestDriftError) as ctx:
                check_manifest_upstream_drift(manifest, check_assumptions=False)
        self.assertIn("defects4j_commit", str(ctx.exception))

    def test_upstream_active_set_drift(self) -> None:
        manifest = self._valid_manifest()
        drifted_lists = synthetic_active_lists()
        # Change Cli active set while keeping count >= 30.
        drifted_lists["Cli"] = [str(i) for i in range(100, 140)]
        drifted_catalog = synthetic_catalog(drifted_lists)
        with mock.patch(
            "src.select_bugs.load_active_bug_catalog",
            return_value=drifted_catalog,
        ):
            with self.assertRaises(ManifestDriftError) as ctx:
                check_manifest_upstream_drift(manifest, check_assumptions=False)
        self.assertIn("projects.Cli", str(ctx.exception))


class TestOneTimeCreate(unittest.TestCase):
    def test_atomic_write_and_reread_stable(self) -> None:
        active = synthetic_active_lists()
        catalog = synthetic_catalog(active)
        selection = select_bugs(active)
        manifest = build_manifest(
            catalog,
            selection,
            environment=synthetic_environment(),
            created_at="2026-09-22T00:00:00+00:00",
            git_commit="abc123",
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.json"
            write_manifest_atomic(path, manifest)
            raw1 = path.read_bytes()
            write_manifest_atomic(path, manifest)
            raw2 = path.read_bytes()
            self.assertEqual(raw1, raw2)
            self.assertEqual(raw1.decode("utf-8"), serialize_manifest(manifest))
            self.assertFalse(path.with_name("manifest.json.tmp").exists())

    def test_failed_write_does_not_leave_truncated_manifest(self) -> None:
        active = synthetic_active_lists()
        catalog = synthetic_catalog(active)
        selection = select_bugs(active)
        manifest = build_manifest(
            catalog,
            selection,
            environment=synthetic_environment(),
            created_at="2026-09-22T00:00:00+00:00",
            git_commit=None,
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.json"
            path.write_text("KEEP-ME\n", encoding="utf-8")
            with mock.patch("pathlib.Path.replace", side_effect=OSError("boom")):
                with self.assertRaises(OSError):
                    write_manifest_atomic(path, manifest)
            self.assertEqual(path.read_text(encoding="utf-8"), "KEEP-ME\n")
            self.assertFalse(path.with_name("manifest.json.tmp").exists())

    def test_create_does_not_rewrite_existing(self) -> None:
        active = synthetic_active_lists()
        catalog = synthetic_catalog(active)
        selection = select_bugs(active)
        manifest = build_manifest(
            catalog,
            selection,
            environment=synthetic_environment(),
            created_at="2026-09-22T12:00:00+00:00",
            git_commit="lockme",
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.json"
            write_manifest_atomic(path, manifest)
            before = path.read_bytes()
            created_at = json.loads(before)["created_at"]

            with mock.patch(
                "src.select_bugs.check_manifest_upstream_drift",
                return_value=None,
            ):
                loaded, created = create_manifest_file(
                    path,
                    check_assumptions=False,
                )
            after = path.read_bytes()
            self.assertFalse(created)
            self.assertEqual(before, after)
            self.assertEqual(loaded["created_at"], created_at)

    def test_verify_preserves_bytes(self) -> None:
        active = synthetic_active_lists()
        catalog = synthetic_catalog(active)
        selection = select_bugs(active)
        manifest = build_manifest(
            catalog,
            selection,
            environment=synthetic_environment(),
            created_at="2026-09-22T12:00:00+00:00",
            git_commit="lockme",
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.json"
            write_manifest_atomic(path, manifest)
            before = path.read_bytes()
            with mock.patch(
                "src.select_bugs.check_manifest_upstream_drift",
                return_value=None,
            ):
                verify_manifest_file(path, check_upstream_drift=True, check_assumptions=False)
            self.assertEqual(path.read_bytes(), before)


class TestSelectBugsRawLexSort(unittest.TestCase):
    def test_population_uses_string_sorted(self) -> None:
        ids = [str(i) for i in range(1, 40)]
        active = {project: ids for project in PROJECT_ORDER}
        # Only first project consumption compared against a fresh RNG on string-sorted pop.
        result = select_bugs_raw(active, seed=SELECTION_SEED)
        expected_first = random.Random(SELECTION_SEED).sample(sorted(ids), SAMPLE_SIZE)
        self.assertEqual(list(result.projects[0].selected_ids), expected_first)


if __name__ == "__main__":
    unittest.main()
