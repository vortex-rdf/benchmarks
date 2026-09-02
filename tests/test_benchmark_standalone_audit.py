import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "standalone_audit", ROOT / "audit_benchmark_standalone_v1.py"
)
AUDIT = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(AUDIT)

class StandaloneAuditTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "BSBM"
        self.root.mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def audit(self, include_vendored=False):
        return AUDIT.audit(self.root, include_vendored=include_vendored)

    def test_optional_krown_documentation_is_not_a_dependency(self):
        (self.root / "README.md").write_text(
            "KROWN integration is optional. This benchmark does not invoke KROWN.\n",
            encoding="utf-8",
        )
        self.assertTrue(self.audit()["summary"]["static_standalone_candidate"])

    def test_operational_krown_import_is_an_error(self):
        (self.root / "run.py").write_text("import KROWN\n", encoding="utf-8")
        findings = self.audit()["findings"]
        self.assertEqual([item["kind"] for item in findings], ["krown-dependency"])

    def test_vendored_tree_is_excluded_by_default(self):
        path = self.root / "data/tools/tool/node_modules/pkg"
        path.mkdir(parents=True)
        (path / "README.md").write_text("Use /home/user/bin.\n", encoding="utf-8")
        default = self.audit()
        complete = self.audit(include_vendored=True)
        self.assertEqual(default["findings"], [])
        self.assertGreater(default["summary"]["skipped_vendored_file_count"], 0)
        self.assertEqual(complete["findings"][0]["kind"], "absolute-path")

    def test_json_absolute_paths_are_precisely_reported(self):
        (self.root / "manifest.json").write_text(
            json.dumps({"source": {"path": "/users/example/data.nt"}}),
            encoding="utf-8",
        )
        finding = self.audit()["findings"][0]
        self.assertEqual(finding["kind"], "nonportable-provenance-path")
        self.assertEqual(finding["location"], "$.source.path")

    def test_relative_json_paths_are_portable(self):
        (self.root / "manifest.json").write_text(
            json.dumps({"source": {"path": "data.nt"}}), encoding="utf-8"
        )
        self.assertTrue(self.audit()["summary"]["static_standalone_candidate"])

    def test_output_order_is_deterministic(self):
        (self.root / "z.json").write_text(json.dumps({"path": "/tmp/z"}), encoding="utf-8")
        (self.root / "a.json").write_text(json.dumps({"path": "/tmp/a"}), encoding="utf-8")
        first = self.audit()
        second = self.audit()
        self.assertEqual(first, second)
        self.assertEqual([item["path"] for item in first["findings"]], ["a.json", "z.json"])

if __name__ == "__main__":
    unittest.main()
