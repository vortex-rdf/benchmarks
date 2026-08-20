from pathlib import Path
import json
import tempfile
import unittest

from DBBench.manifest import (
    build_inventory, prepare, query_tree_provenance, select_query_records,
)


class DBBenchManifestTests(unittest.TestCase):
    def record(self, query_id='TP/dbpedia/a.txt::q0000'):
        return {
            'query_id': query_id, 'relative_path': 'TP/dbpedia/a.txt',
            'top_group': 'TP', 'dataset': 'dbpedia', 'size_group': None,
            'file_name': 'a.txt', 'query_index_in_file': 0, 'line_no': 1,
            'contains_limit': False,
            'query': 'SELECT ?s WHERE { ?s ?p ?o . }',
        }

    def test_prepare_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); inventory = root / 'inventory.json'
            output = root / 'manifest.json'
            inventory.write_text(json.dumps([self.record()]), encoding='utf-8')
            manifest = prepare(output=output, workload='dbbench',
                               dataset='dbpedia', inventory=inventory)
            self.assertEqual(manifest['query_count'], 1)
            self.assertEqual(manifest['source']['kind'], 'inventory')

    def test_query_tree_ignores_non_txt_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); target = root / 'TP/dbpedia/a.txt'
            target.parent.mkdir(parents=True)
            target.write_text('SELECT ?s WHERE { ?s ?p ?o }\n', encoding='utf-8')
            (root / '.DS_Store').write_text('ignored', encoding='utf-8')
            (target.parent / 'diagnostic.sparql').write_text('SELECT * {}', encoding='utf-8')
            records = build_inventory(root, 'dbpedia', ['TP'], ['small', 'big'])
            self.assertEqual(len(records), 1)
            self.assertEqual(len(query_tree_provenance(root, 'dbpedia', ['TP'], ['small', 'big'])['files']), 1)

    def test_selection_rejects_unknown_and_duplicate_ids(self):
        with self.assertRaisesRegex(ValueError, 'unknown selected'):
            select_query_records([self.record()], ['missing'])
        with self.assertRaisesRegex(ValueError, 'duplicate selected'):
            select_query_records([self.record()], [self.record()['query_id']] * 2)


if __name__ == '__main__':
    unittest.main()
