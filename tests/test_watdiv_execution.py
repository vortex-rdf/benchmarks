from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from WatDiv.execution import run
from benchmark_core.cli import main
from benchmark_core.rdf_execution import run as shared_run


class WatDivExecutionTests(unittest.TestCase):
    def test_execution_reuses_common_runner(self):
        self.assertIs(run, shared_run)

    def test_public_cli_dispatches_watdiv_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.json"
            dataset = root / "dataset.nt"
            output = root / "results.jsonl"
            manifest.write_text(json.dumps({
                "schema_version": 1,
                "dataset": "tiny",
                "workload": "watdiv-tiny",
                "queries": [{
                    "query_id": "q1",
                    "query": "SELECT * WHERE { ?s ?p ?o }",
                    "query_sha256": "8f7e4f65fc5f30af726fec803eb329e8271d08eb469a30cc7ad904e4b32d6558",
                    "stream": "test.1",
                    "position": 0,
                    "native_query_id": 1,
                }],
            }), encoding="utf-8")
            dataset.write_text("<s> <p> <o> .\n", encoding="utf-8")
            with patch("benchmark_core.cli.run_watdiv", return_value=[{"status": "ok"}]) as runner:
                with patch("builtins.print"):
                    code = main([
                        "watdiv", "run",
                        "--manifest", str(manifest),
                        "--dataset-path", str(dataset),
                        "--output", str(output),
                        "--experiment-id", "watdiv-test",
                        "--warmup-runs", "0",
                        "--measured-runs", "1",
                        "--timeout-s", "10",
                    ])
            self.assertEqual(code, 0)
            runner.assert_called_once_with(
                manifest_path=manifest,
                dataset_path=dataset,
                output=output,
                experiment_id="watdiv-test",
                warmup_runs=0,
                measured_runs=1,
                timeout_s=10.0,
                resume=False,
            )


if __name__ == "__main__":
    unittest.main()
