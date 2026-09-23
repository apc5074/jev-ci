"""Phase 4 P4-02: shared code tokenizer behavior and provenance."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.ranking import (
    tokenize_document,
    tokenize_query,
)
from src.representations import compact_source_lines
from src.tokenize import (
    TOKENIZER_CONFIG,
    TOKENIZER_VERSION,
    tokenize,
    tokenizer_config_sha256,
    tokenizer_provenance,
)


class OutlineExampleTests(unittest.TestCase):
    def test_parse_http_response_v2(self) -> None:
        self.assertEqual(
            tokenize("parseHTTPResponse_v2"),
            ["parse", "http", "response", "v2"],
        )


class JavaIdentifierTests(unittest.TestCase):
    def test_package_and_class(self) -> None:
        self.assertEqual(
            tokenize("org.apache.commons.cli.DefaultParser"),
            ["org", "apache", "commons", "cli", "default", "parser"],
        )

    def test_method_camel_case(self) -> None:
        self.assertEqual(
            tokenize("testGetOptionGroup"),
            ["test", "get", "option", "group"],
        )

    def test_nested_style_dollar_separator(self) -> None:
        # '$' is non-alnum → separator (FQCN nested form).
        self.assertEqual(
            tokenize("org.foo.Outer$Inner"),
            ["org", "foo", "outer", "inner"],
        )


class BoundaryBehaviorTests(unittest.TestCase):
    def test_digits_stay_with_letters(self) -> None:
        self.assertEqual(tokenize("test123Name"), ["test123", "name"])
        self.assertEqual(tokenize("v2API"), ["v2", "api"])

    def test_repeated_underscores(self) -> None:
        self.assertEqual(tokenize("foo__bar"), ["foo", "bar"])
        self.assertEqual(tokenize("get_http_response"), ["get", "http", "response"])

    def test_acronyms(self) -> None:
        self.assertEqual(tokenize("HTTPResponse"), ["http", "response"])
        self.assertEqual(tokenize("XMLHttpRequest"), ["xml", "http", "request"])
        self.assertEqual(tokenize("IOException"), ["io", "exception"])
        self.assertEqual(tokenize("HTMLParser"), ["html", "parser"])

    def test_unicode_as_separator(self) -> None:
        self.assertEqual(tokenize("café"), ["caf"])
        self.assertEqual(tokenize("naive"), ["naive"])

    def test_empty_and_singletons(self) -> None:
        self.assertEqual(tokenize(""), [])
        self.assertEqual(tokenize("   "), [])
        self.assertEqual(tokenize("a"), [])
        self.assertEqual(tokenize("I"), [])
        # Keywords / stopwords of length ≥ 2 preserved (no removal, no stem).
        self.assertEqual(tokenize("a if for the class"), ["if", "for", "the", "class"])

    def test_deterministic(self) -> None:
        sample = "parseHTTPResponse_v2 org.apache.commons.cli.DefaultParser"
        self.assertEqual(tokenize(sample), tokenize(sample))


class ProvenanceTests(unittest.TestCase):
    def test_config_hash_stable(self) -> None:
        self.assertEqual(tokenizer_config_sha256(), tokenizer_config_sha256())
        self.assertEqual(len(tokenizer_config_sha256()), 64)
        self.assertEqual(TOKENIZER_CONFIG["version"], TOKENIZER_VERSION)
        self.assertFalse(TOKENIZER_CONFIG["stem"])
        self.assertFalse(TOKENIZER_CONFIG["remove_english_stopwords"])
        self.assertFalse(TOKENIZER_CONFIG["remove_java_keywords"])

    def test_provenance_fields(self) -> None:
        prov = tokenizer_provenance()
        self.assertEqual(prov["tokenizer_version"], TOKENIZER_VERSION)
        self.assertEqual(prov["tokenizer_config_sha256"], tokenizer_config_sha256())


class SharedModuleTests(unittest.TestCase):
    def test_phase3_and_phase4_same_function(self) -> None:
        import src.ranking as ranking
        import src.representations as representations
        import src.tokenize as tok

        self.assertIs(ranking.tokenize, tok.tokenize)
        self.assertIs(representations.tokenize, tok.tokenize)
        sample = "parseHTTPResponse_v2"
        self.assertEqual(tokenize_query(sample), tokenize(sample))
        self.assertEqual(tokenize_document(sample), tokenize(sample))

    def test_window_selection_uses_same_tokens(self) -> None:
        # Phase 3 compaction path tokenizes with the shared function.
        lines = [f"line {i} parseHTTPResponse_v2" for i in range(10)]
        _out, meta = compact_source_lines(
            lines, query_tokens=tokenize("parseHTTPResponse_v2")
        )
        self.assertEqual(meta["mode"], "full")


class RankingHashIncludesTokenizerTests(unittest.TestCase):
    def test_input_hashes_embed_tokenizer(self) -> None:
        from src.ranking import (
            build_document_from_source_entry,
            build_query_from_patch_artifacts,
            compute_lexical_input_hashes,
        )

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
            hashes = compute_lexical_input_hashes(
                test_classes=["a.A"],
                query=query,
                documents=docs,
                inventory_path=inv,
                representation_path=rep,
            )
            self.assertEqual(hashes["tokenizer_version"], TOKENIZER_VERSION)
            self.assertEqual(
                hashes["tokenizer_config_sha256"],
                tokenizer_config_sha256(),
            )


if __name__ == "__main__":
    unittest.main()
