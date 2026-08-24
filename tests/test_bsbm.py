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

    def test_execution_reuses_common_runner(self):
        self.assertIs(run, shared_run)

if __name__ == '__main__': unittest.main()
