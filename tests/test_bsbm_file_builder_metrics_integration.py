from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SPEC = importlib.util.spec_from_file_location(
    "bsbm_builds", ROOT / "run_bsbm_10k_representation_builds_v1.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class FileBuilderMetricsIntegrationTests(unittest.TestCase):
    def test_success_publishes_build_metrics_and_size(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "artifact.bin"
            receipt = root / "receipt.json"
            command = [
                sys.executable,
                "-c",
                "from pathlib import Path; Path('artifact.bin').write_bytes(b'abc')",
            ]

            def receipt_writer():
                MODULE.atomic_json(receipt, {"producer": {"tool": "test"}})

            result = MODULE.run_stage(
                "test/default", command, root / "build.log", [output],
                receipt, False, cwd=root, after=receipt_writer,
            )
            stored = json.loads(receipt.read_text(encoding="utf-8"))
        self.assertEqual(result["build_metrics"]["status"], "ok")
        self.assertEqual(result["representation_size"]["logical_bytes"], 3)
        self.assertEqual(stored["producer"]["build_metrics"]["status"], "ok")
        self.assertEqual(stored["producer"]["representation_size"]["logical_bytes"], 3)
        self.assertNotIn("serialization_timing", stored["producer"])

    def test_failure_preserves_metrics_without_claiming_oom(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "build.log"
            with self.assertRaisesRegex(RuntimeError, "failed"):
                MODULE.run_stage(
                    "test/default",
                    [sys.executable, "-c", "raise SystemExit(7)"],
                    log, [root / "artifact.bin"], root / "receipt.json",
                    False, cwd=root,
                )
            failure = json.loads(
                log.with_suffix(".failure.json").read_text(encoding="utf-8")
            )
        self.assertEqual(failure["build_metrics"]["returncode"], 7)
        self.assertFalse(failure["confirmed_oom"])


if __name__ == "__main__":
    unittest.main()
