import json
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

from benchmark_core.http_runner.normalize import normalize_sparql_json_result
from benchmark_core.http_runner.runner import RunProfile, run_system
from benchmark_core.result import load_results


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    calls = []

    def do_POST(self):  # noqa: N802
        body = self.rfile.read(int(self.headers["Content-Length"]))
        query = parse_qs(body.decode())["query"][0]
        type(self).calls.append(query)
        if "SLOW" in query:
            time.sleep(2.0)
        if query.strip().startswith("ASK"):
            payload, status = json.dumps({"head": {}, "boolean": True}).encode(), 200
        elif "BAD" in query:
            payload, status = b"parse error", 400
        else:
            rows = int(query.rsplit("LIMIT", 1)[1]) if "LIMIT" in query else 1
            doc = {"head": {"vars": ["x"]}, "results": {"bindings": [
                {"x": {"type": "uri", "value": f"http://e/{i}"}} for i in range(rows)]}}
            payload, status = json.dumps(doc).encode(), 200
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/sparql-results+json" if status == 200 else "text/plain")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, *args):
        pass


def _manifest(queries, preexpanded=True):
    records = []
    for index, (template, text, phase) in enumerate(queries):
        record = {"query_id": f"q{index:03d}", "query": f"SELECT ?x WHERE {{ ?x ?p ?o }} # {text}",
                  "bsbm_template_id": template}
        if preexpanded:
            record.update({"stream_phase": phase, "stream_position": index})
        records.append(record)
    return {"dataset": "toy", "workload": "toy-w", "queries": records}


class HttpRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.endpoint = f"http://127.0.0.1:{cls.server.server_address[1]}/sparql"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def run_toy(self, queries, **profile):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        out = Path(directory.name) / "run.jsonl"
        calls = []
        summary = run_system(manifest=_manifest(queries), system="toy/http", experiment_id="e", endpoint=self.endpoint,
                             container=None, output=out, profile=RunProfile(**{"timeout_s": 5.0, **profile}),
                             after_timeout=lambda: calls.append(1), progress=lambda line: None)
        return load_results(out), summary, calls, out

    def test_ok_records_reconcile_and_fingerprint_matches_normalizer(self):
        records, summary, _, out = self.run_toy([("1", "LIMIT 3", "warmup"), ("1", "LIMIT 2", "measured")])
        self.assertEqual([r["status"] for r in records], ["ok", "ok"])
        self.assertEqual([r["result_count"] for r in records], [3, 2])
        for record in records:
            self.assertTrue(record["timing_reconciled"])
            self.assertEqual(record["measurement_boundary"], "harness-request-to-complete-result-v2")
            self.assertGreater(record["elapsed_ns"], 0)
        doc = {"head": {"vars": ["x"]}, "results": {"bindings": [
            {"x": {"type": "uri", "value": f"http://e/{i}"}} for i in range(2)]}}
        expected = normalize_sparql_json_result(doc, records[1]["query_id"] and "SELECT ?x WHERE { ?x ?p ?o }")
        self.assertEqual(records[1]["result_fingerprint"], expected["result_fingerprint"])
        self.assertEqual(summary["status_counts"], {"ok": 2})
        self.assertTrue(out.with_name("run.summary.json").exists())

    def test_floor_probes_before_and_after_are_summarized_not_recorded(self):
        _Handler.calls.clear()
        records, summary, _, _ = self.run_toy([("1", "LIMIT 2", "warmup"), ("1", "LIMIT 2", "measured")], floor_probes=5)
        self.assertEqual(len(records), 2)                                   # probes are not result records
        self.assertEqual(sum(q.strip().startswith("ASK") for q in _Handler.calls), 10)
        floor = summary["transport_floor"]
        for part in ("before", "after"):
            self.assertEqual((floor[part]["ok"], floor[part]["errors"]), (5, 0))
            self.assertGreater(floor[part]["median_ns"], 0)
            self.assertLessEqual(floor[part]["min_ns"], floor[part]["median_ns"])
        records, summary, *_ = self.run_toy([("1", "LIMIT 2", "measured")])
        self.assertIsNone(summary["transport_floor"])                       # off by default

    def test_count_only_mode_has_no_fingerprint(self):
        records, *_ = self.run_toy([("1", "LIMIT 4", "measured")], correctness_mode="count-only")
        self.assertEqual(records[0]["result_count"], 4)
        self.assertIsNone(records[0]["result_fingerprint"])
        self.assertEqual(records[0]["comparison_mode"], "count-only")

    def test_timeout_restarts_client_calls_hook_and_quarantines_template(self):
        queries = [("5", "SLOW a", "measured"), ("5", "SLOW b", "measured"), ("5", "SLOW c", "measured"),
                   ("5", "SLOW d", "measured"), ("2", "LIMIT 1", "measured")]
        records, summary, hook_calls, _ = self.run_toy(queries, timeout_s=0.3, quarantine_threshold=3)
        self.assertEqual([r["status"] for r in records], ["timeout"] * 3 + ["skipped", "ok"])
        self.assertEqual(records[3]["skip_kind"], "in-run-template-timeout-quarantine")
        self.assertEqual(len(hook_calls), 3)
        self.assertGreaterEqual(summary["worker_restarts"], 2)

    def test_http_error_is_engine_error_and_run_continues(self):
        records, *_ = self.run_toy([("1", "BAD", "measured"), ("1", "LIMIT 1", "measured")])
        self.assertEqual([r["status"] for r in records], ["engine_error", "ok"])
        self.assertIn("HTTP 400", records[0]["error_message"])

    def test_wall_budget_stops_run(self):
        records, summary, *_ = self.run_toy([("1", "SLOW x", "measured")] * 4, timeout_s=0.2,
                                            quarantine_threshold=0, max_wall_s=0.5)
        self.assertLess(len(records), 4)
        self.assertEqual(summary["budget"]["status"], "budget_exhausted")

    def test_stream_positions_must_increase_but_may_have_gaps(self):
        gapped = _manifest([("1", "LIMIT 1", "measured"), ("1", "LIMIT 1", "measured")])
        gapped["queries"][1]["stream_position"] = 5
        with tempfile.TemporaryDirectory() as directory:
            run_system(manifest=gapped, system="toy/http", experiment_id="e", endpoint=self.endpoint, container=None,
                       output=Path(directory) / "r.jsonl", profile=RunProfile(timeout_s=1.0), progress=lambda line: None)
        manifest = _manifest([("1", "LIMIT 1", "measured"), ("1", "LIMIT 1", "measured")])
        manifest["queries"][1]["stream_position"] = 0
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(ValueError):
            run_system(manifest=manifest, system="toy/http", experiment_id="e", endpoint=self.endpoint, container=None,
                       output=Path(directory) / "r.jsonl", profile=RunProfile(timeout_s=1.0), progress=lambda line: None)


if __name__ == "__main__":
    unittest.main()


class FingerprintColumnOrderTests(unittest.TestCase):
    def test_select_fingerprint_ignores_column_order(self):
        from benchmark_core.http_runner.normalize import _fingerprint
        a = {'result_kind': 'select', 'variables': ['x', 'y'], 'ordered': False, 'rows': [[1, 2], [3, 0]]}
        b = {'result_kind': 'select', 'variables': ['y', 'x'], 'ordered': False, 'rows': [[0, 3], [2, 1]]}
        self.assertEqual(_fingerprint(a), _fingerprint(b))
        self.assertNotEqual(_fingerprint(a), _fingerprint({**b, 'rows': [[0, 1], [2, 3]]}))

    def test_empty_result_without_head_vars_matches_spec_response(self):
        query = 'SELECT ?p ?v (COUNT(?x) AS ?n) WHERE { { <a> ?p ?v } UNION { ?x ?p <a> } }'
        spec = normalize_sparql_json_result({'head': {'vars': ['p', 'v', 'n']}, 'results': {'bindings': []}}, query)
        comunica = normalize_sparql_json_result({'head': {}, 'results': {'bindings': []}}, query)
        self.assertEqual(spec['result_fingerprint'], comunica['result_fingerprint'])
