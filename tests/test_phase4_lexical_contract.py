"""Phase 4 P4-01: lexical query/document contract."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.ranking import (
    LEXICAL_INPUT_CONTRACT_VERSION,
    QUERY_DIFF_SOURCE,
    LexicalInputError,
    build_document_from_source_entry,
    build_lexical_inputs,
    build_query_from_patch_artifacts,
    compose_document_text,
    compute_lexical_input_hashes,
)

_REPO = Path(__file__).resolve().parents[1]
_DATA = _REPO / "data"
_MANIFEST_PATH = _DATA / "manifest.json"


def _load_manifest() -> dict:
    with _MANIFEST_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


class ComposeDocumentTests(unittest.TestCase):
    def test_available_source_joins_fqcn_and_body(self) -> None:
        text = compose_document_text(
            test_class="org.foo.BarTest",
            source_text="package org.foo;\nclass BarTest {}\n",
        )
        self.assertEqual(
            text,
            "org.foo.BarTest\npackage org.foo;\nclass BarTest {}\n",
        )

    def test_missing_source_is_fqcn_only(self) -> None:
        self.assertEqual(
            compose_document_text(test_class="org.foo.MissingTest", source_text=None),
            "org.foo.MissingTest",
        )


class DocumentFromEntryTests(unittest.TestCase):
    def test_missing_flag_skips_disk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            checkout = Path(tmp)
            doc = build_document_from_source_entry(
                {
                    "test_class": "a.ATest",
                    "source_file": "src/a/ATest.java",
                    "source_missing": True,
                },
                checkout_fixed=checkout,
            )
            self.assertTrue(doc.source_missing)
            self.assertEqual(doc.text, "a.ATest")
            self.assertIsNone(doc.source_file)

    def test_available_reads_full_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            checkout = Path(tmp)
            rel = "src/test/java/a/ATest.java"
            path = checkout / rel
            path.parent.mkdir(parents=True)
            body = "package a;\npublic class ATest {\n  // long body\n}\n"
            path.write_text(body, encoding="utf-8")
            doc = build_document_from_source_entry(
                {
                    "test_class": "a.ATest",
                    "source_file": rel,
                    "source_missing": False,
                },
                checkout_fixed=checkout,
            )
            self.assertFalse(doc.source_missing)
            self.assertEqual(doc.text, f"a.ATest\n{body}")
            self.assertNotIn("TEST CLASS:", doc.text)
            self.assertNotIn("[SOURCE MISSING]", doc.text)

    def test_claimed_available_but_absent_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            checkout = Path(tmp)
            with self.assertRaises(LexicalInputError) as ctx:
                build_document_from_source_entry(
                    {
                        "test_class": "a.ATest",
                        "source_file": "missing/ATest.java",
                        "source_missing": False,
                    },
                    checkout_fixed=checkout,
                )
            self.assertIn("refusing compact-representation fallback", str(ctx.exception))


class QueryBuilderTests(unittest.TestCase):
    def test_uses_model_visible_representation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rep = root / "representation.txt"
            content = (
                "MODIFIED FILES:\nsrc/Foo.java\n\n"
                "MODIFIED CLASSES:\nFoo\n\n"
                "PROPOSED CODE CHANGE:\n\n--- a\n+++ b\n"
            )
            rep.write_text(content, encoding="utf-8")
            query = build_query_from_patch_artifacts(
                representation_path=rep,
                patch_meta={
                    "modified_files": ["src/Foo.java"],
                    "modified_classes": ["Foo"],
                    "patch_truncated": False,
                },
            )
            self.assertEqual(query.diff_source, QUERY_DIFF_SOURCE)
            self.assertEqual(query.text, content)
            self.assertEqual(query.modified_files, ("src/Foo.java",))
            self.assertNotIn("positive_classes", query.text)
            self.assertNotIn("trigger_methods", query.text)


class HashTests(unittest.TestCase):
    def test_hashes_stable_and_versioned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inv = root / "inventory.json"
            inv.write_text('{"test_classes":["a.A"]}\n', encoding="utf-8")
            rep = root / "representation.txt"
            rep.write_text("MODIFIED FILES:\nx\n", encoding="utf-8")
            query = build_query_from_patch_artifacts(representation_path=rep)
            docs = [
                build_document_from_source_entry(
                    {
                        "test_class": "a.A",
                        "source_file": None,
                        "source_missing": True,
                    },
                    checkout_fixed=root,
                )
            ]
            h1 = compute_lexical_input_hashes(
                test_classes=["a.A"],
                query=query,
                documents=docs,
                inventory_path=inv,
                representation_path=rep,
            )
            h2 = compute_lexical_input_hashes(
                test_classes=["a.A"],
                query=query,
                documents=docs,
                inventory_path=inv,
                representation_path=rep,
            )
            self.assertEqual(h1, h2)
            self.assertEqual(
                h1["lexical_input_contract_version"],
                LEXICAL_INPUT_CONTRACT_VERSION,
            )
            self.assertEqual(h1["query_diff_source"], QUERY_DIFF_SOURCE)
            self.assertEqual(h1["num_documents"], 1)


@unittest.skipUnless(
    (_DATA / "bugs" / "Cli_30" / "example.json").is_file()
    and (_DATA / "bugs" / "Cli_30" / "checkouts" / "fixed").is_dir()
    and _MANIFEST_PATH.is_file(),
    "Cli-30 complete example + fixed checkout + manifest required",
)
class LiveCli30LexicalTests(unittest.TestCase):
    def test_one_document_per_inventory_class(self) -> None:
        from src.example_contract import read_json

        manifest = _load_manifest()
        inputs = build_lexical_inputs(
            "Cli-30",
            data_root=_DATA,
            manifest=manifest,
        )
        inventory = read_json(_DATA / "tests" / "Cli_30" / "inventory.json")
        classes = inventory["test_classes"]
        self.assertEqual(len(inputs.documents), len(classes))
        self.assertEqual([d.test_class for d in inputs.documents], classes)
        self.assertEqual(inputs.query.diff_source, QUERY_DIFF_SOURCE)
        self.assertTrue(inputs.query.text.startswith("MODIFIED FILES:"))

        for doc, entry in zip(inputs.documents, inventory["source_map"]):
            if entry["source_missing"]:
                self.assertEqual(doc.text, doc.test_class)
            else:
                self.assertTrue(doc.text.startswith(doc.test_class + "\n"))
                self.assertGreater(len(doc.text), len(doc.test_class) + 1)
                self.assertFalse(doc.text.startswith("TEST CLASS:"))

        joined_docs = "\n".join(d.text for d in inputs.documents)
        self.assertNotIn("positive_classes", joined_docs)
        self.assertNotIn("trigger_methods", joined_docs)
        self.assertNotIn("\nPRIVATE\n", joined_docs)

        # Long-source class must include more than the compact windowed excerpt:
        # ApplicationTest is 288 lines in inventory — full file is in the document.
        app = next(
            d
            for d in inputs.documents
            if d.test_class == "org.apache.commons.cli.ApplicationTest"
        )
        self.assertIn("package org.apache.commons.cli", app.text)
        self.assertGreater(app.text.count("\n"), 240)


@unittest.skipUnless(
    _MANIFEST_PATH.is_file()
    and (_DATA / "bugs" / "Cli_30" / "checkouts" / "fixed").is_dir(),
    "development artifacts + checkouts required",
)
class LiveDevelopmentCorpusShapeTests(unittest.TestCase):
    """Acceptance: every development bug yields one doc per tests.all class."""

    def test_all_development_bugs(self) -> None:
        from src.example_contract import read_json

        manifest = _load_manifest()
        ids = manifest["development_bug_ids"]
        self.assertEqual(len(ids), 25)
        for qid in ids:
            slug = qid.replace("-", "_", 1)
            checkout = _DATA / "bugs" / slug / "checkouts" / "fixed"
            if not checkout.is_dir():
                self.skipTest(f"fixed checkout missing for {qid}")
            inputs = build_lexical_inputs(
                qid,
                data_root=_DATA,
                manifest=manifest,
            )
            inventory = read_json(_DATA / "tests" / slug / "inventory.json")
            self.assertEqual(
                [d.test_class for d in inputs.documents],
                inventory["test_classes"],
                msg=qid,
            )
            self.assertEqual(
                inputs.input_hashes["lexical_input_contract_version"],
                LEXICAL_INPUT_CONTRACT_VERSION,
            )
            self.assertEqual(inputs.query.diff_source, QUERY_DIFF_SOURCE)


if __name__ == "__main__":
    unittest.main()
