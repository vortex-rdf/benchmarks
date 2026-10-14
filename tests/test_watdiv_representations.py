from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from benchmark_core.cli import main
from WatDiv.representations import (
    REPRESENTATION_TYPES,
    build,
    classify_failure,
    declaration,
    inspect,
    output_directory,
    _command_for,
    VORTEX_CONFIGURATIONS,
)


class WatDivRepresentationTests(unittest.TestCase):
    def test_declarations_cover_both_datasets_and_all_representations(self):
        for dataset in ("watdiv-10m", "watdiv-100m"):
            for representation in REPRESENTATION_TYPES:
                item = declaration(dataset, representation)
                self.assertEqual(item["benchmark"], "watdiv")
                self.assertEqual(item["source_format"], "ntriples")
                self.assertEqual(item["representation"], representation)

    def test_unsupported_dataset_and_representation_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported WatDiv dataset"):
            declaration("watdiv-1m", "hdt")
        with self.assertRaisesRegex(ValueError, "Unsupported WatDiv representation"):
            declaration("watdiv-10m", "sqlite")

    def test_output_paths_are_dataset_owned(self):
        root = Path("/tmp/watdiv-test-output")
        self.assertEqual(
            output_directory("watdiv-10m", "hdt", root),
            root.resolve() / "watdiv-10m" / "hdt",
        )

    def test_command_construction_uses_verified_builder_contracts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            command, environment, cwd = _command_for(
                "vortex-by-reference",
                source=root / "source.nt",
                output=root / "dataset.vortex",
                source_receipt=root / "rdf.json",
                receipt=root / "receipt.json",
                inventory=root / "inventory.json",
                rdf2hdt=root / "rdf2hdt",
                hdt_index_python=root / "python",
                vortex_cli=root / "vortex-rdf-cli",
                vortex_repository=root,
                source_triple_count=1,
            )
        self.assertEqual(command[1:3], ["serialize", "-i"])
        self.assertIn("--indexes", command)
        self.assertIn("secondary-by-reference", command)
        self.assertEqual(environment["RUST_LOG"], "vortex_rdf_cli=debug,vortex_rdf_core=debug")
        self.assertEqual(cwd, root)

    def test_inspect_reports_missing_source_without_building(self):
        value = inspect("watdiv-10m", "hdt", "/tmp/watdiv-test-output")
        self.assertTrue(value["source_exists"])
        self.assertFalse(value["output_exists"])

    def test_public_cli_dispatches_representation_inspect(self):
        with patch("builtins.print") as printer:
            self.assertEqual(
                main([
                    "watdiv",
                    "representation",
                    "inspect",
                    "--dataset",
                    "watdiv-10m",
                    "--representation",
                    "hdt",
                    "--output-root",
                    "/tmp/watdiv-test-output",
                ]),
                0,
            )
        self.assertTrue(printer.called)

    def test_missing_source_and_dependency_fail_before_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(FileNotFoundError):
                build(
                    dataset="watdiv-10m",
                    representation="hdt",
                    output_root=root / "generated",
                    source_path=root / "missing.nt",
                )

    def test_atomic_build_refuses_existing_and_force_promotes_temp_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.nt"
            source.write_text("<a> <b> <c> .\n", encoding="utf-8")
            output_root = root / "generated"
            final = output_root / "watdiv-10m" / "vortex"
            final.mkdir(parents=True)
            (final / "dataset.vortex").write_bytes(b"existing")
            (final / "vortex-receipt.json").write_text(
                json.dumps({"invalid": True}), encoding="utf-8"
            )
            cli = root / "vortex"
            cli.write_text(
                "#!/bin/sh\nset -eu\nwhile [ $# -gt 0 ]; do\n"
                "  if [ \"$1\" = \"-o\" ]; then output=$2; shift 2; else shift; fi\n"
                "done\nprintf 'new' > \"$output\"\n",
                encoding="utf-8",
            )
            cli.chmod(0o755)
            with self.assertRaises(FileExistsError):
                build(
                    dataset="watdiv-10m", representation="vortex-by-reference", output_root=output_root,
                    source_path=source, vortex_cli=cli, vortex_repository=Path("/users/u0182905/vortex-rdf"),
                )
            self.assertEqual((final / "dataset.vortex").read_bytes(), b"existing")

    def test_failed_build_cleans_temporary_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.nt"
            source.write_text("<a> <b> <c> .\n", encoding="utf-8")
            cli = root / "vortex"
            cli.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            cli.chmod(0o755)
            with patch("WatDiv.representations.run_build_command", side_effect=RuntimeError("failed")):
                with self.assertRaisesRegex(RuntimeError, "failed"):
                    build(
                        dataset="watdiv-10m", representation="vortex-by-reference", output_root=root / "generated",
                        source_path=source, vortex_cli=cli, vortex_repository=Path("/users/u0182905/vortex-rdf"),
                    )
            self.assertEqual(list((root / "generated").glob(".*")), [])

    def test_failure_classification_does_not_call_exit_oom(self):
        self.assertEqual(classify_failure(FileNotFoundError()), "missing_dependency")
        self.assertEqual(classify_failure(RuntimeError("exit 137"), returncode=137), "build_failed")
        self.assertEqual(classify_failure(RuntimeError("confirmed_oom")), "confirmed_oom")

    def test_synthetic_vortex_build_creates_receipt_and_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.nt"
            source.write_text("<a> <b> <c> .\n", encoding="utf-8")
            cli = root / "vortex-rdf-cli"
            cli.write_text(
                "#!/bin/sh\nset -eu\nwhile [ $# -gt 0 ]; do\n  if [ \"$1\" = \"-o\" ]; then output=$2; shift 2; else shift; fi\ndone\nprintf 'vortex' > \"$output\"\n",
                encoding="utf-8",
            )
            cli.chmod(0o755)
            value = build(
                dataset="watdiv-10m", representation="vortex-by-reference", output_root=root / "generated",
                source_path=source, vortex_cli=cli, vortex_repository=Path("/users/u0182905/vortex-rdf"),
                log_dir=root / "logs",
            )
            self.assertEqual(value["status"], "ok")
            self.assertTrue(Path(value["receipt_path"]).is_file())
            self.assertGreater(value["output_size_bytes"], 0)
            self.assertEqual(json.loads(Path(value["receipt_path"]).read_text())["representation"],
                             "vortex-rdf/dictionary-secondary-by-reference")


    def test_vortex_variants_are_explicit_and_default_layout_is_out_of_scope(self):
        self.assertEqual(
            set(VORTEX_CONFIGURATIONS),
            {"vortex-by-reference", "vortex-by-copy"},
        )
        self.assertNotIn("vortex", REPRESENTATION_TYPES)
        with self.assertRaisesRegex(ValueError, "Unsupported WatDiv representation"):
            declaration("watdiv-10m", "vortex")

    def test_vortex_variants_have_distinct_paths_commands_and_receipts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            common = dict(
                source=root / "source.nt",
                output=root / "dataset.vortex",
                source_receipt=root / "rdf.json",
                receipt=root / "receipt.json",
                inventory=root / "inventory.json",
                rdf2hdt=root / "rdf2hdt",
                hdt_index_python=root / "python",
                vortex_cli=root / "vortex-rdf-cli",
                vortex_repository=root,
                source_triple_count=1,
            )
            reference_command, _, _ = _command_for("vortex-by-reference", **common)
            copy_command, _, _ = _command_for("vortex-by-copy", **common)
        self.assertEqual(reference_command[-4:], ["--layout", "dictionary", "--indexes", "secondary-by-reference"])
        self.assertEqual(copy_command[-4:], ["--layout", "dictionary", "--indexes", "secondary-by-copy"])
        self.assertNotEqual(reference_command, copy_command)
        self.assertEqual(
            output_directory("watdiv-10m", "vortex-by-reference", "/tmp/watdiv-variants").name,
            "vortex",
        )
        self.assertEqual(
            output_directory("watdiv-10m", "vortex-by-copy", "/tmp/watdiv-variants").name,
            "vortex-by-copy",
        )
        self.assertEqual(
            VORTEX_CONFIGURATIONS["vortex-by-reference"]["receipt_representation"],
            "vortex-rdf/dictionary-secondary-by-reference",
        )
        self.assertEqual(
            VORTEX_CONFIGURATIONS["vortex-by-copy"]["receipt_representation"],
            "vortex-rdf/dictionary-secondary-by-copy",
        )


if __name__ == "__main__":
    unittest.main()
