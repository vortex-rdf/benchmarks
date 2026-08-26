import json,tempfile,unittest
from pathlib import Path
from benchmark_core.experiment import load_experiment_declaration,validate_experiment_declaration
class ExperimentDeclarationTests(unittest.TestCase):
 def test_committed_bsbm_declaration_is_valid(self):
  root=Path(__file__).resolve().parents[1]; value=load_experiment_declaration(root/"BSBM/experiments/explore-1k-smoke.json")
  self.assertEqual(len(value["bindings"]),9); self.assertEqual(len(value["representations"]),4)
 def test_duplicate_system_is_rejected(self):
  root=Path(__file__).resolve().parents[1]; value=json.loads((root/"BSBM/experiments/explore-1k-smoke.json").read_text()); value["bindings"].append(dict(value["bindings"][0]))
  with self.assertRaisesRegex(ValueError,"duplicate system"): validate_experiment_declaration(value)
 def test_undeclared_representation_is_rejected(self):
  root=Path(__file__).resolve().parents[1]; value=json.loads((root/"BSBM/experiments/explore-1k-smoke.json").read_text()); value["bindings"][0]["representation"]="missing/default"
  with self.assertRaisesRegex(ValueError,"undeclared representation"): validate_experiment_declaration(value)
if __name__=="__main__": unittest.main()
