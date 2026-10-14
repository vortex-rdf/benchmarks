import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from BSBM.manifest import prepare
from BSBM.execution import run
from benchmark_core.rdf_execution import run as shared_run

class BsbmTests(unittest.TestCase):
    def test_prepare_is_deterministic_and_uses_common_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); queries = root / 'queries'; queries.mkdir()
            (queries / '02.rq').write_text('ASK { ?s ?p ?o }', encoding='utf-8')
            (queries / '01.sparql').write_text('SELECT * WHERE { ?s ?p ?o }', encoding='utf-8')
            output = root / 'manifest.json'
            manifest = prepare(query_root=queries, output=output,
                               workload='bsbm-smoke', dataset='tiny')
            self.assertEqual([q['query_id'] for q in manifest['queries']],
                             ['01.sparql', '02.rq'])
            self.assertEqual(json.loads(output.read_text()), manifest)

    def test_official_stream_preserves_identity_and_selects_measured_templates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); stream = root / 'explore.csv'; dataset = root / 'dataset.nt'
            dataset.write_text('<a> <b> <c> .\n', encoding='utf-8')
            rows = [('1', 'query', 'ASK { ?s ?p ?o }'),
                    ('2', 'query', 'SELECT * WHERE { ?s ?p ?o }'),
                    ('2', 'query', 'SELECT * WHERE { ?s ?p ?o }'),
                    ('1', 'query', 'ASK { ?s ?p ?o }')]
            with stream.open('w', encoding='utf-8', newline='') as handle:
                writer = csv.writer(handle); writer.writerow(['id', 'kind', 'content']); writer.writerows(rows)
            digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
            receipt = root / 'receipt.json'
            receipt.write_text(json.dumps({'schema': 'bsbm-generation-receipt-v1',
                'benchmark': 'BSBM', 'use_case': 'Explore', 'specification': '3.1',
                'product_count': 1, 'forward_chaining': True,
                'query_stream': {'record_count': 4, 'warmup_records': 1,
                    'measured_records': 3, 'size_bytes': stream.stat().st_size,
                    'sha256': digest(stream)},
                'dataset': {'size_bytes': dataset.stat().st_size, 'sha256': digest(dataset)},
                'generator': {'commit': 'test'}}), encoding='utf-8')
            manifest = prepare(query_stream=stream, generation_receipt=receipt,
                dataset_path=dataset, selection='smoke', output=root/'manifest.json',
                workload='bsbm-explore-smoke', dataset='bsbm-1')
            self.assertEqual([q['bsbm_template_id'] for q in manifest['queries']], ['2', '1'])
            self.assertEqual([q['stream_position'] for q in manifest['queries']], [1, 3])
            self.assertEqual(len({q['query_id'] for q in manifest['queries']}), 2)
            full = prepare(query_stream=stream, generation_receipt=receipt,
                dataset_path=dataset, selection='full', output=root/'full.json',
                workload='bsbm-explore-full', dataset='bsbm-1')
            self.assertEqual([q['stream_phase'] for q in full['queries']],
                             ['warmup', 'measured', 'measured', 'measured'])

    def test_official_stream_rejects_update_and_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); stream = root/'stream.csv'; dataset = root/'dataset.nt'
            stream.write_text('id,kind,content\n1,update,DELETE WHERE { ?s ?p ?o }\n')
            dataset.write_text('<a> <b> <c> .\n')
            receipt = root/'receipt.json'; receipt.write_text(json.dumps({
                'schema': 'bsbm-generation-receipt-v1', 'benchmark': 'BSBM', 'use_case': 'Explore',
                'query_stream': {'record_count': 1, 'warmup_records': 0, 'measured_records': 1,
                    'size_bytes': stream.stat().st_size,
                    'sha256': hashlib.sha256(stream.read_bytes()).hexdigest()},
                'dataset': {'size_bytes': dataset.stat().st_size,
                    'sha256': hashlib.sha256(dataset.read_bytes()).hexdigest()}}))
            with self.assertRaisesRegex(ValueError, 'not a query'):
                prepare(query_stream=stream, generation_receipt=receipt, dataset_path=dataset,
                    output=root/'out.json', workload='w', dataset='d')
            stream.write_text('id,kind,content\n1,query,ASK { ?s ?p ?o }\n')
            with self.assertRaisesRegex(ValueError, 'SHA-256'):
                prepare(query_stream=stream, generation_receipt=receipt, dataset_path=dataset,
                    output=root/'out.json', workload='w', dataset='d')

    def test_execution_reuses_common_runner(self):
        self.assertIs(run, shared_run)

if __name__ == '__main__': unittest.main()
