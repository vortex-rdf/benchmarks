import json
import unittest
from pathlib import Path

from DBBench.schedule import expand_tp3, load_invalid_ids, records_sha256


def _query(group, file_name, index, size=None):
    path = f"{group}/dbpedia/{size + '/' if size else ''}{file_name}"
    return {"query_id": f"{path}::q{index:04d}", "source_top_group": group, "source_file_name": file_name,
            "source_size_group": size, "source_query_index": index, "query": f"SELECT * WHERE {{ ?s ?p {index} }}",
            "comparison_mode": "unordered_multiset_fingerprint"}


BASE = {"dataset": "dbpedia", "workload": "w", "queries": [
    _query("JOINS", "joinSS_A_big.txt", 0, "big"), _query("JOINS", "joinSS_A_small.txt", 0, "small"),
    _query("TP", "spoSPARQL.txt", 0), _query("TP", "VVoSPARQL.txt", 0), _query("TP", "VVoSPARQL.txt", 1),
]}


class ScheduleTests(unittest.TestCase):
    def test_phases_order_and_counts(self):
        out = expand_tp3(BASE, set(), tp_passes=2)
        records = out["queries"]
        self.assertEqual([r["stream_position"] for r in records], list(range(len(records))))
        self.assertEqual(len(records), 3 + 2 * 3 + 2)
        self.assertEqual([r["stream_phase"] for r in records[:3]], ["warmup"] * 3)
        self.assertEqual([r["source_query_id"] for r in records[:3]],
                         ["TP/dbpedia/VVoSPARQL.txt::q0000", "TP/dbpedia/VVoSPARQL.txt::q0001", "TP/dbpedia/spoSPARQL.txt::q0000"])
        self.assertEqual({r["set_repetition"] for r in records[3:9]}, {1, 2})
        self.assertEqual([r["set_repetition"] for r in records[-2:]], [1, 1])
        self.assertTrue(records[-1]["query_id"].startswith("measured-joins/"))
        self.assertTrue(all(r["comparison_mode"] == "count-only" for r in records))
        self.assertEqual(out["warmup_query_count"], 3)
        self.assertEqual(out["measured_query_count"], len(records) - 3)

    def test_invalid_queries_are_excluded_and_unknown_ids_rejected(self):
        out = expand_tp3(BASE, {"TP/dbpedia/VVoSPARQL.txt::q0001"}, tp_passes=1)
        self.assertNotIn("TP/dbpedia/VVoSPARQL.txt::q0001", {r["source_query_id"] for r in out["queries"]})
        with self.assertRaises(ValueError):
            expand_tp3(BASE, {"nope"})

    def test_identity_is_stable(self):
        self.assertEqual(records_sha256(expand_tp3(BASE, set())), records_sha256(expand_tp3(BASE, set())))

    def test_committed_inventory_and_checksum_file(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(len(load_invalid_ids(root / "DBBench/invalid-queries.json")), 20)
        checks = json.loads((root / "DBBench/checksums.json").read_text())
        self.assertEqual(checks["tp3-schedule"]["queries"], 15683)


if __name__ == "__main__":
    unittest.main()
