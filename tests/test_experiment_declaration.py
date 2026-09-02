import json
import unittest
from pathlib import Path

from benchmark_core.experiment import (
    load_experiment_declaration,
    validate_experiment_declaration,
)


class ExperimentDeclarationTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]
        self.smoke_path = (
            self.root / "BSBM/experiments/explore-1k-smoke.json"
        )
        self.full_path = (
            self.root / "BSBM/experiments/explore-1k-full.json"
        )

    def test_committed_bsbm_declarations_are_valid_and_distinct(self):
        smoke = load_experiment_declaration(self.smoke_path)
        full = load_experiment_declaration(self.full_path)

        self.assertEqual(len(smoke["bindings"]), 10)
        self.assertEqual(len(smoke["representations"]), 5)
        self.assertEqual(full["bindings"], smoke["bindings"])
        self.assertEqual(full["representations"], smoke["representations"])
        self.assertEqual(
            smoke["experiment"],
            "bsbm/explore-1k/explore-smoke",
        )
        self.assertEqual(smoke["workload"], "bsbm-explore-smoke")
        self.assertEqual(
            full["experiment"],
            "bsbm/explore-1k/explore-full",
        )
        self.assertEqual(full["workload"], "bsbm-explore-full")

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


if __name__ == "__main__":
    unittest.main()
