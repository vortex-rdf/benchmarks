import json
import tempfile
import unittest
from pathlib import Path

from benchmark_core.http_runner.report import format_report


class ReportTests(unittest.TestCase):
    def test_report_summarizes_systems_and_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            system = run / "toy-system"
            system.mkdir()
            records = [{"phase": "measured", "status": "ok", "elapsed_ns": ms * 10**6, "bsbm_template_id": "1"}
                       for ms in (1, 2, 3)]
            records.append({"phase": "measured", "status": "timeout", "elapsed_ns": 10**10, "bsbm_template_id": "5"})
            records.append({"phase": "warmup", "status": "ok", "elapsed_ns": 5, "bsbm_template_id": "1"})
            (system / "results.jsonl").write_text("\n".join(json.dumps(r) for r in records) + "\n")
            (system / "results.summary.json").write_text(json.dumps(
                {"load": {"start_to_ready_s": 1.5},
                 "phase_memory_metrics": {"phases": {"measured": {"peak_anon_bytes": 2 * 2**30, "peak_file_bytes": 2**30}}}}))
            failed = run / "broken"
            failed.mkdir()
            (failed / "failed.json").write_text(json.dumps({"phase": "start", "error": "boom"}))
            text = format_report(run)
        self.assertIn("toy-system", text)
        self.assertRegex(text, r"toy-system\s+3\s+1\s+0\s+0\s+2\.00\s+2\.00")
        self.assertIn("FAILED broken: start boom", text)


if __name__ == "__main__":
    unittest.main()
