import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from WatDiv.manifest import DATASET_DECLARATIONS, compute_catalog_digest, parse_stream, prepare


class WatDivTests(unittest.TestCase):
    def _write_stream(self, root: Path, stream_name: str, ordering: list[int], texts: list[str]) -> None:
        sparql_path = root / f"{stream_name}.sparql"
        desc_path = root / f"{stream_name}.desc"
        sparql_path.write_text("\n".join(texts) + "\n", encoding="utf-8")
        desc_path.write_text("\n".join(str(value) for value in ordering) + "\n", encoding="utf-8")

    def test_prepare_accepts_valid_fixture_and_preserves_native_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workload_root = root / "watdiv-stress-100"
            workload_root.mkdir(parents=True, exist_ok=True)
            for stream_name, ordering in [
                ("warmup", [1, 2, 3, 4, 5, 6]),
                ("test.1", [2, 5, 4, 1, 6, 3]),
                ("test.2", [3, 4, 1, 6, 2, 5]),
                ("test.3", [4, 1, 6, 5, 3, 2]),
                ("test.4", [5, 2, 6, 3, 1, 4]),
                ("test.5", [6, 3, 2, 5, 4, 1]),
            ]:
                query_texts = {
                    1: "SELECT * WHERE { ?s ?p ?o }",
                    2: "SELECT ?s WHERE { ?s ?p ?o }",
                    3: "SELECT ?s ?p WHERE { ?s ?p ?o }",
                    4: "SELECT * WHERE { ?s ?p ?o }",
                    5: "SELECT ?o WHERE { ?s ?p ?o }",
                    6: "SELECT ?s ?p ?o WHERE { ?s ?p ?o }",
                }
                self._write_stream(
                    workload_root,
                    stream_name,
                    ordering,
                    [query_texts[native_id] for native_id in ordering],
                )
            dataset_path = root / "watdiv.10M.nt"
            dataset_path.write_text("<s> <p> <o> .\n", encoding="utf-8")
            manifest = prepare(
                output=root / "manifest.json",
                dataset="watdiv-10m",
                dataset_path=dataset_path,
                workload_root=workload_root,
                expected_count=6,
            )
            self.assertEqual(manifest["query_count"], 36)
            self.assertEqual(manifest["stream_order"], ["warmup", "test.1", "test.2", "test.3", "test.4", "test.5"])
            self.assertEqual(manifest["catalog"]["query_count"], 6)
            self.assertEqual(len(manifest["queries"]), 36)
            self.assertEqual(
                manifest["catalog"]["digest"],
                compute_catalog_digest({
                    1: hashlib.sha256("SELECT * WHERE { ?s ?p ?o }".encode("utf-8")).hexdigest(),
                    2: hashlib.sha256("SELECT ?s WHERE { ?s ?p ?o }".encode("utf-8")).hexdigest(),
                    3: hashlib.sha256("SELECT ?s ?p WHERE { ?s ?p ?o }".encode("utf-8")).hexdigest(),
                    4: hashlib.sha256("SELECT * WHERE { ?s ?p ?o }".encode("utf-8")).hexdigest(),
                    5: hashlib.sha256("SELECT ?o WHERE { ?s ?p ?o }".encode("utf-8")).hexdigest(),
                    6: hashlib.sha256("SELECT ?s ?p ?o WHERE { ?s ?p ?o }".encode("utf-8")).hexdigest(),
                }),
            )
            self.assertEqual(manifest["queries"][0]["phase"], "warmup")
            self.assertEqual(manifest["queries"][-1]["phase"], "measured")
            self.assertIn("native_query_id", manifest["queries"][0])

    def test_parse_stream_rejects_invalid_description_and_sparql(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stream_dir = root / "stream"
            stream_dir.mkdir(parents=True, exist_ok=True)
            sparql = stream_dir / "stream.sparql"
            desc = stream_dir / "stream.desc"

            sparql.write_text("SELECT * WHERE { ?s ?p ?o }\n", encoding="utf-8")
            desc.write_text("1\n\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "blank|description"):
                parse_stream(sparql, desc, expected_count=1)

            desc.write_text("abc\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "integer"):
                parse_stream(sparql, desc, expected_count=1)

            desc.write_text("1\n", encoding="utf-8")
            sparql.write_text("ASK { ?s ?p ?o }\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "SELECT"):
                parse_stream(sparql, desc, expected_count=1)

            sparql.write_text("SELECT * WHERE { ?s ?p ?o \n", encoding="utf-8")
            desc.write_text("1\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "brace|balanced"):
                parse_stream(sparql, desc, expected_count=1)

    def test_parse_stream_hashes_exact_line_bytes_without_terminator(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sparql = root / "stream.sparql"
            desc = root / "stream.desc"
            query = b"  SELECT * WHERE { ?s ?p ?o }  "
            sparql.write_bytes(query + b"\r\n")
            desc.write_text("1\n", encoding="utf-8")

            parsed = parse_stream(sparql, desc, expected_count=1)

            self.assertEqual(parsed[0]["query"].encode("utf-8"), query)
            self.assertEqual(parsed[0]["query_sha256"], hashlib.sha256(query).hexdigest())
            self.assertEqual(compute_catalog_digest({1: parsed[0]["query_sha256"]}), hashlib.sha256(
                f"1\t{parsed[0]['query_sha256']}".encode("ascii")
            ).hexdigest())

    def test_dataset_declarations_are_explicit_and_cli_prepare_works(self):
        self.assertIn("watdiv-10m", DATASET_DECLARATIONS)
        self.assertIn("watdiv-100m", DATASET_DECLARATIONS)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workload = root / "watdiv-stress-100"
            workload.mkdir()
            for stream_name, ordering in [
                ("warmup", [1, 2]),
                ("test.1", [2, 1]),
                ("test.2", [1, 2]),
                ("test.3", [2, 1]),
                ("test.4", [1, 2]),
                ("test.5", [2, 1]),
            ]:
                query_texts = {
                    1: "SELECT * WHERE { ?s ?p ?o }",
                    2: "SELECT ?s WHERE { ?s ?p ?o }",
                }
                self._write_stream(workload, stream_name, ordering, [query_texts[n] for n in ordering])
            dataset_path = root / "watdiv.10M.nt"
            dataset_path.write_text("<s> <p> <o> .\n", encoding="utf-8")
            output = root / "manifest.json"
            manifest = prepare(output=output, dataset="watdiv-10m", dataset_path=dataset_path, workload_root=workload, expected_count=2)
            self.assertEqual(manifest["query_count"], 12)
            self.assertEqual(manifest["catalog"]["query_count"], 2)
            self.assertEqual(manifest["stream_order"][0], "warmup")

            command = [
                sys.executable,
                "-m",
                "benchmark_core.cli",
                "watdiv",
                "prepare",
                "--dataset",
                "watdiv-10m",
                "--output",
                str(root / "cli-manifest.json"),
            ]
            completed = subprocess.run(command, capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[1]))
            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads((root / "cli-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["dataset"], "watdiv-10m")


if __name__ == "__main__":
    unittest.main()
