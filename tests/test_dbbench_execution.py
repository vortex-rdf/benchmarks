from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest

from DBBench.execution import run


class DBBenchExecutionTests(unittest.TestCase):
    def fixture(self, root):
        dataset = root / 'data.ttl'
        dataset.write_text(
            '@prefix ex: <http://example/> . '
            'ex:a ex:p ex:b . ex:c ex:p ex:b .\n', encoding='utf-8'
        )
        queries = [
            {'query_id': 'unordered', 'query': 'SELECT ?s WHERE { ?s <http://example/p> <http://example/b> }', 'query_result_type': 'SELECT', 'comparison_mode': 'unordered_fingerprint'},
            {'query_id': 'ordered', 'query': 'SELECT ?s WHERE { ?s <http://example/p> <http://example/b> } ORDER BY DESC(?s)', 'query_result_type': 'SELECT', 'comparison_mode': 'ordered_fingerprint'},
            {'query_id': 'ask', 'query': 'ASK { <http://example/a> <http://example/p> <http://example/b> }', 'query_result_type': 'ASK', 'comparison_mode': 'boolean'},
            {'query_id': 'construct', 'query': 'CONSTRUCT { ?s <http://example/q> ?o } WHERE { ?s <http://example/p> ?o }', 'query_result_type': 'CONSTRUCT', 'comparison_mode': 'graph_fingerprint'},
            {'query_id': 'empty', 'query': 'SELECT ?s WHERE { ?s <http://example/missing> ?o }', 'query_result_type': 'SELECT', 'comparison_mode': 'unordered_fingerprint'},
            {'query_id': 'bad', 'query': 'SELECT WHERE {', 'query_result_type': 'SELECT', 'comparison_mode': 'unordered_fingerprint'},
        ]
        manifest = root / 'manifest.json'
        manifest.write_text(json.dumps({
            'schema_version': 1, 'workload': 'tiny', 'dataset': 'tiny',
            'query_count': len(queries), 'queries': queries,
        }), encoding='utf-8')
        return dataset, manifest

    def test_execution_order_fingerprints_and_cli_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); dataset, manifest = self.fixture(root)
            output = root / 'results.jsonl'
            records = run(
                manifest_path=manifest, dataset_path=dataset, output=output,
                experiment_id='test', warmup_runs=1, measured_runs=2,
            )
            self.assertEqual(len(records), 18)
            self.assertEqual(
                [(r['phase'], r['run']) for r in records[:3]],
                [('warmup', 0), ('measured', 0), ('measured', 1)],
            )
            measured = {r['query_id']: r for r in records if r['phase'] == 'measured' and r['run'] == 0}
            self.assertEqual(measured['unordered']['result_count'], 2)
            self.assertEqual(measured['ask']['result_count'], 1)
            self.assertEqual(measured['construct']['result_count'], 2)
            self.assertEqual(measured['empty']['result_count'], 0)
            self.assertEqual(measured['bad']['status'], 'engine_error')
            self.assertNotEqual(measured['ordered']['result_fingerprint'], measured['unordered']['result_fingerprint'])
            self.assertIn('version', measured['ask']['engine'])
            completed = subprocess.run(
                [sys.executable, '-m', 'benchmark_core.cli',
                 'results', 'validate', str(output)],
                capture_output=True, text=True, check=True,
            )
            self.assertEqual(json.loads(completed.stdout)['records'], 18)

    def test_resume_rejects_incompatible_and_duplicate_records(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); dataset, manifest = self.fixture(root)
            output = root / 'results.jsonl'
            records = run(
                manifest_path=manifest, dataset_path=dataset, output=output,
                experiment_id='test', warmup_runs=0, measured_runs=1,
            )
            self.assertEqual(run(
                manifest_path=manifest, dataset_path=dataset, output=output,
                experiment_id='test', warmup_runs=0, measured_runs=1,
                resume=True,
            ), records)
            with self.assertRaisesRegex(ValueError, 'incompatible resume'):
                run(
                    manifest_path=manifest, dataset_path=dataset,
                    output=output, experiment_id='other', warmup_runs=0,
                    measured_runs=1, resume=True,
                )
            with output.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(records[0]) + '\n')
            with self.assertRaisesRegex(ValueError, 'duplicate resume key'):
                run(
                    manifest_path=manifest, dataset_path=dataset,
                    output=output, experiment_id='test', warmup_runs=0,
                    measured_runs=1, resume=True,
                )


if __name__ == '__main__':
    unittest.main()
