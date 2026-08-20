from pathlib import Path
import json
import tempfile
import unittest

from DBBench.execution import run


class DBBenchExecutionTests(unittest.TestCase):
    def test_rdflib_execution_and_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = root / 'data.ttl'
            dataset.write_text('@prefix ex: <http://example/> . ex:a ex:p ex:b .\n', encoding='utf-8')
            queries = [
                {'query_id': 'select', 'query': 'SELECT ?s WHERE { ?s <http://example/p> <http://example/b> }', 'query_result_type': 'SELECT', 'comparison_mode': 'unordered_fingerprint'},
                {'query_id': 'ask', 'query': 'ASK { <http://example/a> <http://example/p> <http://example/b> }', 'query_result_type': 'ASK', 'comparison_mode': 'boolean'},
                {'query_id': 'construct', 'query': 'CONSTRUCT { ?s <http://example/q> ?o } WHERE { ?s <http://example/p> ?o }', 'query_result_type': 'CONSTRUCT', 'comparison_mode': 'graph_fingerprint'},
                {'query_id': 'bad', 'query': 'SELECT WHERE {', 'query_result_type': 'SELECT', 'comparison_mode': 'unordered_fingerprint'},
            ]
            manifest = root / 'manifest.json'
            manifest.write_text(json.dumps({'schema_version': 1, 'workload': 'tiny', 'dataset': 'tiny', 'query_count': len(queries), 'queries': queries}), encoding='utf-8')
            output = root / 'results.jsonl'
            records = run(manifest_path=manifest, dataset_path=dataset, output=output, experiment_id='test', warmup_runs=0, measured_runs=1)
            self.assertEqual(len(records), 4)
            self.assertEqual([r['status'] for r in records], ['ok', 'ok', 'ok', 'engine_error'])
            self.assertEqual(run(manifest_path=manifest, dataset_path=dataset, output=output, experiment_id='test', warmup_runs=0, measured_runs=1, resume=True), records)


if __name__ == '__main__':
    unittest.main()
