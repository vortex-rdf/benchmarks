import json,tempfile,unittest
from pathlib import Path
from benchmark_core.representation import create_receipt,create_inventory,load_receipt
class RepresentationTests(unittest.TestCase):
 def test_receipt_and_inventory_verify_files_and_identity(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d); source=r/'data.nt'; source.write_text('<a> <b> <c> .\n'); a=r/'source.json'
   value=create_receipt(receipt_path=a,benchmark='bsbm',dataset='tiny',source_format='ntriples',source_path=source,representation='rdf/source',files=['data.nt'],producer={'tool':'test'},created_at_utc='2026-08-25T00:00:00Z')
   self.assertEqual(load_receipt(a),value)
   inventory=create_inventory(inventory_path=r/'inventory.json',benchmark='bsbm',dataset='tiny',receipt_paths=['source.json'])
   self.assertEqual(inventory['source']['sha256'],value['source']['sha256'])
   source.write_text('changed')
   with self.assertRaisesRegex(ValueError,'differs'):load_receipt(a)
 def test_inventory_rejects_mixed_source_identity(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d); source=r/'data.nt'; source.write_text('a');
   for n,rep in [('a','rdf/source'),('b','hdt/default')]:create_receipt(receipt_path=r/f'{n}.json',benchmark='bsbm',dataset='tiny',source_format='ntriples',source_path=source,representation=rep,files=['data.nt'],producer={},created_at_utc='2026-08-25T00:00:00Z')
   v=json.loads((r/'b.json').read_text());v['source']['sha256']='0'*64;(r/'b.json').write_text(json.dumps(v))
   with self.assertRaisesRegex(ValueError,'source RDF identity'):create_inventory(inventory_path=r/'i.json',benchmark='bsbm',dataset='tiny',receipt_paths=['a.json','b.json'])
if __name__=='__main__':unittest.main()
