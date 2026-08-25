import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from BSBM.vortex_rdf import CONFIGURATION, generate, verify
from benchmark_core.representation import create_inventory, create_receipt


class BsbmVortexRdfTests(unittest.TestCase):
    def _source(self, root):
        source=root/"dataset.nt"; source.write_text("<a> <b> <c> .\n", encoding="utf-8")
        receipt=root/"rdf-source-receipt.json"
        create_receipt(receipt_path=receipt, benchmark="bsbm", dataset="tiny",
            source_format="ntriples", source_path=source, representation="rdf/source",
            files=[source.name], producer={"kind":"test"}, created_at_utc="2026-08-25T00:00:00Z")
        return source,receipt

    def test_generate_uses_exact_native_command_and_preserves_inventory(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); source,rdf_receipt=self._source(root)
            old=root/"dataset.hdt"; old.write_bytes(b"hdt")
            old_receipt=root/"hdt-default-receipt.json"
            create_receipt(receipt_path=old_receipt, benchmark="bsbm", dataset="tiny",
                source_format="ntriples", source_path=source, representation="hdt/default",
                files=[old.name], producer={"kind":"test"}, created_at_utc="2026-08-25T00:00:00Z")
            inventory=root/"dataset-inventory.json"
            create_inventory(inventory_path=inventory, benchmark="bsbm", dataset="tiny",
                             receipt_paths=[rdf_receipt.name,old_receipt.name])
            cli=root/"vortex-rdf-cli"; cli.write_bytes(b"binary")
            def fake_run(command, **kwargs):
                class Result: stdout="0a0e51171aa42e79defdcd322bc1a328a93fcd11\n"
                if command[0]=="git": return Result()
                self.assertEqual(command[1:3], ["serialize","--input"])
                self.assertEqual(command[-4:], ["--index-type","simple-dictionary","--storage-layout","native-rdf-store"])
                Path(command[5]).write_bytes(b"vortex")
                return Result()
            with patch("BSBM.vortex_rdf.subprocess.run", side_effect=fake_run):
                value=generate(source=source, output=root/"dataset-bootstrap.vortex",
                    rdf_receipt=rdf_receipt, vortex_receipt=root/"vortex-rdf-bootstrap-receipt.json",
                    inventory=inventory, vortex_cli=cli, vortex_repository=root, source_triple_count=1)
            self.assertEqual(value, verify(receipt=root/"vortex-rdf-bootstrap-receipt.json"))
            stored=json.loads(inventory.read_text())
            self.assertEqual([x["representation"] for x in stored["representations"]],
                ["rdf/source","hdt/default",f"vortex-rdf/{CONFIGURATION}"])

    def test_generate_removes_partial_temporary_artifact(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); source,receipt=self._source(root); cli=root/"cli"; cli.write_bytes(b"x")
            def fail(command, **kwargs):
                class Result: stdout="0a0e51171aa42e79defdcd322bc1a328a93fcd11\n"
                if command[0]=="git": return Result()
                Path(command[5]).write_bytes(b"partial"); raise RuntimeError("failure")
            with patch("BSBM.vortex_rdf.subprocess.run", side_effect=fail):
                with self.assertRaisesRegex(RuntimeError,"failure"):
                    generate(source=source, output=root/"dataset-bootstrap.vortex", rdf_receipt=receipt,
                        vortex_receipt=root/"receipt.json", inventory=root/"inventory.json",
                        vortex_cli=cli, vortex_repository=root, source_triple_count=1)
            self.assertFalse((root/".dataset-bootstrap.tmp.vortex").exists())

    def test_verify_rejects_other_representation(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); _,receipt=self._source(root)
            with self.assertRaisesRegex(ValueError,"vortex-rdf"):
                verify(receipt=receipt)

if __name__ == "__main__": unittest.main()
