from pathlib import Path
import unittest

from benchmark_core.architecture_audit import audit_repository


class ArchitectureAuditTests(unittest.TestCase):
    def test_dbbench_and_bsbm_share_the_public_contracts(self):
        root = Path(__file__).resolve().parents[1]
        report = audit_repository(root)
        self.assertEqual(report['schema'], 'rdf-benchmark-architecture-audit-v1')
        self.assertEqual(report['benchmarks'], ['dbbench', 'bsbm'])
        self.assertEqual(report['shared_execution_wrappers'], {
            'dbbench': True,
            'bsbm': True,
        })
        self.assertTrue(report['external_assets_ignored'])
        self.assertTrue(report['atomic_publication'])


if __name__ == '__main__':
    unittest.main()
