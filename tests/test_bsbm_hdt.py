import json
import tempfile
import unittest
from pathlib import Path
from BSBM.hdt import generate, verify
from benchmark_core.representation import create_receipt

class BsbmHdtTests(unittest.TestCase):
    def test_generate_creates_verified_receipt_and_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); source=root/"dataset.nt"; source.write_text("<a> <b> <c> .\n")
            create_receipt(receipt_path=root/"rdf-source-receipt.json", benchmark="bsbm",
                dataset="tiny", source_format="ntriples", source_path=source,
                representation="rdf/source", files=["dataset.nt"], producer={"kind":"test"},
                created_at_utc="2026-08-25T00:00:00Z")
            tool=root/"rdf2hdt"; tool.write_text("#!/bin/sh\nset -eu\n[ \"$1\" = \"convert\" ]\n[ \"$2\" = \"--input\" ]\n[ \"$4\" = \"--output\" ]\ncp -- \"$3\" \"$5\"\n"); tool.chmod(0o755)
            value=generate(source=source, output=root/"dataset.hdt",
                rdf_receipt=root/"rdf-source-receipt.json",
                hdt_receipt=root/"hdt-default-receipt.json", inventory=root/"dataset-inventory.json",
                rdf2hdt=tool, source_triple_count=1)
            self.assertEqual(value, verify(receipt=root/"hdt-default-receipt.json"))
            inventory=json.loads((root/"dataset-inventory.json").read_text())
            self.assertEqual([x["representation"] for x in inventory["representations"]],
                             ["rdf/source", "hdt/default"])
    def test_verify_rejects_non_hdt_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); source=root/"dataset.nt"; source.write_text("x")
            receipt=root/"receipt.json"
            create_receipt(receipt_path=receipt, benchmark="bsbm", dataset="tiny",
                source_format="ntriples", source_path=source, representation="rdf/source",
                files=["dataset.nt"], producer={}, created_at_utc="2026-08-25T00:00:00Z")
            with self.assertRaisesRegex(ValueError, "hdt/default"): verify(receipt=receipt)
if __name__ == "__main__": unittest.main()
