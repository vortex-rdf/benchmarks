import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from benchmark_core.atomic_io import write_json_atomic, write_jsonl_atomic
from benchmark_core.hashing import sha256_text
from benchmark_core.manifest import load_manifest, validate_manifest
from benchmark_core.result import load_results, validate_result


class CoreTests(unittest.TestCase):
    def manifest(self):
        query = "SELECT * WHERE { ?s ?p ?o }"
        return {
            "schema_version": 1, "workload": "smoke", "dataset": "test",
            "queries": [{"query_id": "q1", "query": query,
                         "query_sha256": sha256_text(query)}],
        }

    def result(self):
        return {
            "schema_version": 1, "experiment_id": "smoke", "system": "fake",
            "dataset": "test", "workload": "smoke", "query_id": "q1",
            "phase": "measured", "run": 0, "order": 0, "status": "ok",
            "elapsed_ns": 1, "result_count": 0,
        }

    def test_manifest_accepts_exact_query(self):
        self.assertEqual(validate_manifest(self.manifest())["queries"][0]["query_id"], "q1")

    def test_manifest_rejects_duplicate_ids(self):
        value = self.manifest(); value["queries"].append(dict(value["queries"][0]))
        with self.assertRaisesRegex(ValueError, "Duplicate query_id"):
            validate_manifest(value)

    def test_manifest_rejects_non_finite_metadata(self):
        value = self.manifest(); value["metadata"] = float("nan")
        with self.assertRaisesRegex(ValueError, "valid JSON"):
            validate_manifest(value)

    def test_result_contract(self):
        self.assertEqual(validate_result(self.result())["status"], "ok")

    def test_atomic_files_and_loaders(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.json"; results = root / "results.jsonl"
            write_json_atomic(manifest, self.manifest())
            write_jsonl_atomic(results, [self.result()])
            self.assertEqual(len(load_manifest(manifest)["queries"]), 1)
            self.assertEqual(len(load_results(results)), 1)

    def test_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); manifest = root / "manifest.json"
            write_json_atomic(manifest, self.manifest())
            command = [sys.executable, "-m", "benchmark_core.cli"]
            described = subprocess.run(command + ["describe"], check=True,
                                       capture_output=True, text=True)
            self.assertEqual(json.loads(described.stdout)["tool"], "vortex-rdf-bench")
            validated = subprocess.run(command + ["manifest", "validate", str(manifest)],
                                       check=True, capture_output=True, text=True)
            self.assertEqual(json.loads(validated.stdout)["queries"], 1)


if __name__ == "__main__":
    unittest.main()
