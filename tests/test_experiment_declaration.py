import json
import unittest
from pathlib import Path

from benchmark_core.experiment import (
    load_experiment_declaration,
    validate_experiment_declaration,
)


class ExperimentDeclarationTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1]
        self.smoke_path = root / "BSBM/experiments/explore-1k-smoke.json"
        self.full_path = root / "BSBM/experiments/explore-1k-full.json"

    def test_committed_bsbm_declarations_are_valid_and_distinct(self):
        smoke = load_experiment_declaration(self.smoke_path)
        full = load_experiment_declaration(self.full_path)

        self.assertEqual(len(smoke["bindings"]), 25)        # 13 comparison systems + 12 Vortex configurations
        self.assertEqual(len(smoke["representations"]), 9)  # source, HDT, COTTAS, 6 Vortex layout/index variants
        self.assertEqual(full["bindings"], smoke["bindings"])
        self.assertEqual(full["representations"], smoke["representations"])
        self.assertEqual(smoke["experiment"], "bsbm/explore-1k/explore-smoke")
        self.assertEqual(smoke["workload"], "bsbm-explore-smoke")
        self.assertEqual(full["experiment"], "bsbm/explore-1k/explore-full")
        self.assertEqual(full["workload"], "bsbm-explore-full")
        self.assertNotIn("semantic_baseline", smoke)
        self.assertNotIn("semantic_baseline", full)

    def test_optional_semantic_baseline_is_validated(self):
        value = json.loads(self.smoke_path.read_text(encoding="utf-8"))
        value["semantic_baseline"] = "baselines/smoke.json"
        self.assertEqual(
            validate_experiment_declaration(value)["semantic_baseline"],
            "baselines/smoke.json",
        )
        value["semantic_baseline"] = "../outside.json"
        with self.assertRaisesRegex(ValueError, "semantic_baseline"):
            validate_experiment_declaration(value)

    def test_duplicate_system_is_rejected(self):
        value = json.loads(self.smoke_path.read_text(encoding="utf-8"))
        value["bindings"].append(dict(value["bindings"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate system"):
            validate_experiment_declaration(value)

    def test_undeclared_representation_is_rejected(self):
        value = json.loads(self.smoke_path.read_text(encoding="utf-8"))
        value["bindings"][0]["representation"] = "missing/default"
        with self.assertRaisesRegex(ValueError, "undeclared representation"):
            validate_experiment_declaration(value)


    def test_committed_watdiv_declarations_are_valid(self):
        root = Path(__file__).resolve().parents[1]
        declarations = {
            "watdiv-10m-smoke.json": ("watdiv-10m", "watdiv-stress-100", "watdiv/watdiv-10m/smoke"),
            "watdiv-10m-full.json": ("watdiv-10m", "watdiv-stress-100", "watdiv/watdiv-10m/full"),
            "watdiv-100m-full.json": ("watdiv-100m", "watdiv-stress-1000", "watdiv/watdiv-100m/full"),
        }
        expected_representations = {
            "rdf/source",
            "hdt/default",
            "cottas/default",
            "vortex-rdf/dictionary-secondary-by-reference",
            "vortex-rdf/dictionary-secondary-by-copy",
        }
        for name, (dataset, workload, experiment) in declarations.items():
            value = load_experiment_declaration(root / "WatDiv/experiments" / name)
            self.assertEqual(value["benchmark"], "watdiv")
            self.assertEqual(value["dataset"], dataset)
            self.assertEqual(value["workload"], workload)
            self.assertEqual(value["experiment"], experiment)
            self.assertEqual(set(value["representations"]), expected_representations)
            self.assertEqual(len(value["bindings"]), 14 if "100m" in name else 17)   # 100m: new systems added after its run
            self.assertEqual(value["execution_policy"], {
                "warmup_runs": 0,
                "measured_runs": 1,
                "timeout_s": 10.0,
            })
            self.assertNotIn("semantic_baseline", value)


if __name__ == "__main__":
    unittest.main()
