import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from BSBM.cottas import generate, verify
from benchmark_core.representation import create_inventory, create_receipt


class _FakePycottas:
    def rdf2cottas(self, source, output, *, index, disk):
        self.arguments = (source, output, index, disk)
        Path(output).write_bytes(Path(source).read_bytes() + b"cottas")

    def verify(self, path):
        return Path(path).is_file()


class BsbmCottasTests(unittest.TestCase):
    def _source_receipt(self, root: Path) -> Path:
        source = root / "dataset.nt"
        source.write_text("<a> <b> <c> .\n", encoding="utf-8")
        receipt = root / "rdf-source-receipt.json"
        create_receipt(receipt_path=receipt, benchmark="bsbm", dataset="tiny",
            source_format="ntriples", source_path=source, representation="rdf/source",
            files=[source.name], producer={"kind": "test"},
            created_at_utc="2026-08-25T00:00:00Z")
        return receipt

    def test_generate_creates_verified_receipt_and_preserves_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rdf_receipt = self._source_receipt(root)
            hdt = root / "dataset.hdt"
            hdt.write_bytes(b"hdt")
            hdt_receipt = root / "hdt-default-receipt.json"
            create_receipt(receipt_path=hdt_receipt, benchmark="bsbm", dataset="tiny",
                source_format="ntriples", source_path=root / "dataset.nt",
                representation="hdt/default", files=[hdt.name], producer={"kind": "test"},
                created_at_utc="2026-08-25T00:00:00Z")
            inventory = root / "dataset-inventory.json"
            create_inventory(inventory_path=inventory, benchmark="bsbm", dataset="tiny",
                receipt_paths=[rdf_receipt.name, hdt_receipt.name])
            fake = _FakePycottas()
            with patch("BSBM.cottas._load_pycottas", return_value=fake):
                value = generate(source=root / "dataset.nt", output=root / "dataset.cottas",
                    rdf_receipt=rdf_receipt, cottas_receipt=root / "cottas-default-receipt.json",
                    inventory=inventory, source_triple_count=1)
            self.assertEqual(value, verify(receipt=root / "cottas-default-receipt.json"))
            self.assertEqual(fake.arguments[2:], ("spo", True))
            stored = json.loads(inventory.read_text(encoding="utf-8"))
            self.assertEqual([item["representation"] for item in stored["representations"]],
                             ["rdf/source", "hdt/default", "cottas/default"])

    def test_verify_rejects_non_cottas_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = self._source_receipt(root)
            with self.assertRaisesRegex(ValueError, "cottas/default"):
                verify(receipt=receipt)

    def test_generate_removes_temporary_file_after_converter_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = self._source_receipt(root)
            class Failing:
                def rdf2cottas(self, source, output, *, index, disk):
                    Path(output).write_bytes(b"partial")
                    raise RuntimeError("failure")
            with patch("BSBM.cottas._load_pycottas", return_value=Failing()):
                with self.assertRaisesRegex(RuntimeError, "failure"):
                    generate(source=root / "dataset.nt", output=root / "dataset.cottas",
                        rdf_receipt=receipt, cottas_receipt=root / "cottas-default-receipt.json",
                        inventory=root / "dataset-inventory.json", source_triple_count=1)
            self.assertFalse((root / ".dataset.tmp.cottas").exists())


if __name__ == "__main__":
    unittest.main()
