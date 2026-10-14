from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmark_core.build_metrics import (
    BUILD_SCHEMA,
    SIZE_SCHEMA,
    measure_representation_size,
    run_build_command,
)


class BuildMetricsTests(unittest.TestCase):
    def test_size_uses_logical_and_allocated_file_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "representation"
            root.mkdir()
            first = root / "a.bin"
            second = root / "nested/b.bin"
            second.parent.mkdir()
            first.write_bytes(b"abc")
            second.write_bytes(b"12345")
            expected_allocated = (
                first.stat().st_blocks + second.stat().st_blocks
            ) * 512
            result = measure_representation_size([root])
        self.assertEqual(result["schema"], SIZE_SCHEMA)
        self.assertEqual(result["boundary"], "adapter-declared-paths")
        self.assertEqual(result["logical_bytes"], 8)
        self.assertEqual(result["allocated_bytes"], expected_allocated)
        self.assertEqual(result["file_count"], 2)
        self.assertEqual(result["directory_count"], 2)

    def test_size_rejects_duplicate_or_missing_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "unique"):
                measure_representation_size([root, root])
            with self.assertRaises(FileNotFoundError):
                measure_representation_size([root / "missing"])

    def test_build_command_reports_time_and_process_tree_memory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = run_build_command(
                [sys.executable, "-c", "x=bytearray(8*1024*1024); print(len(x))"],
                cwd=root,
                log_path=root / "builder.log",
                interval_s=0.001,
            )
            log = (root / "builder.log").read_text(encoding="utf-8")
        self.assertEqual(result["schema"], BUILD_SCHEMA)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["returncode"], 0)
        self.assertGreater(result["elapsed_ns"], 0)
        self.assertEqual(result["memory"]["scope"], "builder-cgroup-v2")
        self.assertGreater(result["memory"]["sample_count"], 0)
        self.assertGreater(result["memory"]["peak_rss_bytes"], 0)
        self.assertGreaterEqual(result["memory"]["cgroup_lifetime_peak_bytes"], 8 * 1024 * 1024)
        self.assertIsNotNone(result["memory"]["peak_process_tree_rss_bytes"])
        self.assertEqual(result["memory"]["sample_errors"], 0)
        self.assertIn("8388608", log)

    def test_build_command_without_cgroup_keeps_process_tree_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            result = run_build_command(
                [sys.executable, "-c", "x=bytearray(8*1024*1024)"],
                cwd=Path(directory), interval_s=0.001, cgroup=False,
            )
        self.assertEqual(result["memory"]["scope"], "builder-process-tree")
        self.assertNotIn("cgroup_lifetime_peak_bytes", result["memory"])

    def test_failed_builder_returns_failed_metrics(self):
        with tempfile.TemporaryDirectory() as directory:
            result = run_build_command(
                [sys.executable, "-c", "raise SystemExit(7)"],
                cwd=Path(directory),
                interval_s=0.001,
            )
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["returncode"], 7)


if __name__ == "__main__":
    unittest.main()
