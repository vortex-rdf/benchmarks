import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

from benchmark_core.http_runner.worker import HttpQueryWorker, QueryTimeoutError

ROOT = Path(__file__).resolve().parents[1]
DATA = "".join(f"<http://ex/s{i}> <http://ex/p> <http://ex/o{i % 3}> .\n" for i in range(30))


class InProcessWorkerTests(unittest.TestCase):
    """The runner's worker driving benchmark_core.http_runner.inproc on the host (plain rdflib engine)."""

    def _worker(self, store: Path, timeout_s: float = 30.0, deadline_s: float | None = None) -> HttpQueryWorker:
        config = {"engine": "rdflib", "store": str(store), "deadline_s": deadline_s,
                  "server_dir": str(ROOT / "docker" / "rdflib-endpoint")}
        command = [sys.executable, "-m", "benchmark_core.http_runner.inproc", json.dumps(config)]
        return HttpQueryWorker(endpoint="inproc://test", container=None, system="rdflib/default",
                               timeout_s=timeout_s, command=command)

    def test_ready_open_times_and_select_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "data.nt"
            store.write_text(DATA)
            worker = self._worker(store)
            worker.open()
            try:
                ready = worker.ready_messages[0]
                self.assertEqual(ready["worker"], "inproc")
                self.assertGreaterEqual(ready["open_s"], 0)
                self.assertGreaterEqual(ready["import_s"], 0)
                outcome = worker.execute("SELECT ?s WHERE { ?s <http://ex/p> <http://ex/o1> }")
                self.assertEqual(outcome.result_count, 10)
                self.assertTrue(outcome.result_fingerprint)
                self.assertIn("engine_execute_and_consume", outcome.metadata["worker_stages_ns"])
                self.assertEqual(worker.execute("ASK { ?s ?p <http://ex/o2> }").result_count, 1)
            finally:
                worker.close()

    def test_watchdog_ends_a_worker_past_its_deadline(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "data.nt"
            store.write_text(DATA)
            worker = self._worker(store, timeout_s=0.3, deadline_s=0.5)
            worker.open()
            process = worker._process
            slow = "SELECT * WHERE { ?a ?b ?c . ?d ?e ?f . ?g ?h ?i . ?j ?k ?l }"   # 30^4 rows
            with self.assertRaises(QueryTimeoutError):
                worker.execute(slow)
            time.sleep(1.0)
            self.assertIsNotNone(process.poll())     # stopped by the runner or by its own watchdog
            self.assertTrue(worker.prepare_for_attempt())
            try:
                self.assertEqual(worker.execute("ASK { ?s ?p ?o }").result_count, 1)
            finally:
                worker.close()


class WatchdogTests(unittest.TestCase):
    def test_worker_exits_124_at_its_deadline_when_nobody_kills_it(self):
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "data.nt"
            store.write_text(DATA)
            config = {"engine": "rdflib", "store": str(store), "deadline_s": 0.5,
                      "server_dir": str(ROOT / "docker" / "rdflib-endpoint")}
            query = {"kind": "query", "request_id": 0, "result_type": "select", "mode": "count",
                     "query": "SELECT * WHERE { ?a ?b ?c . ?d ?e ?f . ?g ?h ?i . ?j ?k ?l }"}
            process = subprocess.run([sys.executable, "-m", "benchmark_core.http_runner.inproc", json.dumps(config)],
                                     input=json.dumps(query) + "\n", capture_output=True, text=True, timeout=60,
                                     cwd=ROOT)
            self.assertEqual(process.returncode, 124)


if __name__ == "__main__":
    unittest.main()
