from pathlib import Path
import unittest

from benchmark_core.systems import resources
from benchmark_core.systems.fuseki import FUSEKI_IMAGE, Fuseki
from benchmark_core.systems.oxigraph import OXIGRAPH_IMAGE, Oxigraph
from benchmark_core.systems.qlever import QLever
from benchmark_core.systems.registry import get_system, system_ids
from benchmark_core.systems.virtuoso import Virtuoso


class SystemTests(unittest.TestCase):
    def test_registry_ids_and_endpoints(self):
        self.assertEqual(system_ids(), ["comunica/hdt", "fluree/default", "fuseki/memory", "fuseki/tdb2",
                                        "millenniumdb/default", "oxigraph/memory", "oxigraph/rocksdb",
                                        "qendpoint/hdt", "qlever/default", "virtuoso/default"])
        self.assertEqual(get_system("fluree/default").endpoint, "http://localhost:8090/v1/fluree/query/bench")
        self.assertEqual(get_system("millenniumdb/default").endpoint, "http://localhost:1234/sparql")
        self.assertEqual(get_system("qendpoint/hdt").endpoint, "http://localhost:1234/api/endpoint/sparql")
        self.assertEqual(get_system("fuseki/memory").endpoint, "http://localhost:3030/ds/sparql")
        self.assertEqual(get_system("oxigraph/rocksdb").endpoint, "http://localhost:7878/query")
        self.assertEqual(get_system("qlever/default").endpoint, "http://localhost:7001")
        self.assertEqual(get_system("virtuoso/default").endpoint, "http://localhost:8890/sparql")
        with self.assertRaises(ValueError):
            get_system("nope/none")

    def test_rdflib_family_ids(self):
        vortex = get_system("vortex-rdf/dictionary-secondary-by-reference-memory-no-pushdown")
        self.assertEqual((vortex.engine, vortex.in_memory, vortex.pushdown), ("vortex", True, False))
        plain = get_system("vortex-rdf/dictionary-secondary-by-copy")
        self.assertEqual((plain.engine, plain.in_memory, plain.pushdown), ("vortex", False, True))
        self.assertEqual(get_system("pycottas/default").engine, "cottas")
        official = get_system("pycottas/endpoint")
        self.assertEqual((official.engine, official.router), ("cottas", "pycottas-endpoint"))
        self.assertTrue(official.image.startswith("vortex-rdf-bench/pycottas-endpoint:0.5.3-vrl-"))
        self.assertEqual(official._arguments(Path("/x/dataset.cottas"))[-2:], ["--router", "pycottas-endpoint"])
        self.assertNotIn("--router", get_system("pycottas/default")._arguments(Path("/x/dataset.cottas")))
        self.assertEqual(get_system("hdt-rdflib/optimized-in-memory").engine, "hdt")
        self.assertEqual(get_system("rdflib/default").endpoint, "http://localhost:7880/sparql")

    def test_new_systems_commands_and_flags(self):
        from benchmark_core.http_runner.protocol import RAW_QUERY_SYSTEMS
        fluree, mdb, qep = get_system("fluree/default"), get_system("millenniumdb/default"), get_system("qendpoint/hdt")
        self.assertEqual((fluree.persistent, mdb.persistent, qep.persistent), (True, True, True))
        self.assertIn("millenniumdb/default", RAW_QUERY_SYSTEMS)
        self.assertNotIn("fluree/default", RAW_QUERY_SYSTEMS)
        mdb.query_timeout_s = 10.0
        command = mdb._server_command()
        self.assertEqual(command[:2], ["mdb", "server"])
        self.assertEqual(command[command.index("--timeout") + 1], "11")      # client timeout + 1 s
        self.assertEqual(command[-1], ".")
        fluree.query_timeout_s = qep.query_timeout_s = 10.0
        self.assertEqual(fluree.server_environment()["FLUREE_QUERY_TIMEOUT_MS"], "11000")
        self.assertEqual(int(fluree.server_environment()["FLUREE_CACHE_MAX_MB"]), int(resources.SYSTEM_MEMORY_GIB * 1024 * 0.35))
        self.assertEqual(qep.server_timeout_s(), 11)
        for system in (fluree, mdb, qep):
            self.assertTrue(system.image.startswith("vortex-rdf-bench/"))
            self.assertTrue(system.docker_context.joinpath("Dockerfile").is_file())

    def test_persistence_flags(self):
        persistent = {s for s in system_ids() if get_system(s).persistent}
        self.assertEqual(persistent, {"fluree/default", "fuseki/tdb2", "millenniumdb/default", "oxigraph/rocksdb",
                                      "qendpoint/hdt", "qlever/default", "virtuoso/default"})

    def test_pinned_images(self):
        self.assertEqual(OXIGRAPH_IMAGE, "vortex-rdf-bench/oxigraph:0.5.9")
        self.assertEqual(FUSEKI_IMAGE, "vortex-rdf-bench/fuseki:v6.2.0")
        self.assertEqual(QLever.image, "vortex-rdf-bench/qlever:v0.6.0")
        self.assertEqual(Virtuoso.image, "vortex-rdf-bench/virtuoso:v7.2.17")

    def test_qlever_commands_use_campaign_tuning(self):
        qlever = QLever()
        index = qlever._index_command("dataset.nt")
        self.assertEqual(index[0], "-c")
        self.assertIn("--kg-input-file /source/dataset.nt --file-format nt", index[1])
        server = qlever._server_command()[1]
        self.assertIn("--memory-max-size 42G --cache-max-size 8G -j 1", server)

    def test_fuseki_heaps_and_resource_provenance(self):
        self.assertEqual(resources.FUSEKI_HEAPS["memory"], ("4g", "54g"))
        self.assertEqual(resources.FUSEKI_HEAPS["tdb2"], ("4g", "16g"))
        profile = resources.provenance()
        self.assertEqual(profile["docker_memory"], "58g")
        self.assertEqual(profile["virtuoso"]["loader_cores"], 6)

    def test_oxigraph_backend_validation(self):
        with self.assertRaises(ValueError):
            Oxigraph("sqlite")
        with self.assertRaises(ValueError):
            Fuseki("hdt")


if __name__ == "__main__":
    unittest.main()


class VortexLayoutIdTests(unittest.TestCase):
    def test_layout_index_and_mode_ids(self):
        from benchmark_core.systems.rdflib_endpoint import RdflibEndpoint, matches
        for layout in ("dictionary", "default"):
            for index in ("no-index", "secondary-by-reference", "secondary-by-copy"):
                for memory in ("", "-memory"):
                    system = RdflibEndpoint(f"vortex-rdf/{layout}-{index}{memory}")
                    self.assertEqual((system.engine, system.in_memory, system.pushdown), ("vortex", bool(memory), True))
        self.assertFalse(RdflibEndpoint("vortex-rdf/dictionary-no-index-no-pushdown").pushdown)
        self.assertFalse(matches("vortex-rdf/default-no-index-no-pushdown"))
        self.assertFalse(matches("vortex-rdf/typed-object-no-index"))


class SettleTest(unittest.TestCase):
    def test_settle_returns_at_once_when_the_container_died(self):
        import time
        from unittest import mock
        from benchmark_core.systems import docker

        system = get_system("fluree/default")
        with mock.patch.object(docker, "is_running", return_value=False):
            started = time.monotonic()
            self.assertFalse(system.settle(timeout_s=60))
            self.assertLess(time.monotonic() - started, 1.0)


class FlureeImportCheckTest(unittest.TestCase):
    def test_incomplete_import_is_rejected(self):
        from benchmark_core.systems.fluree import check_import

        self.assertEqual(check_import("Imported 35.2M flakes in 90s across 12 commits", 35_159_904), 35_200_000)
        self.assertEqual(check_import("Imported 0.3M flakes in 1s", 301_000), 300_000)
        with self.assertRaises(RuntimeError):
            check_import("Imported 31.8M flakes in 55.41s across 6 commits", 232_541_923)
        with self.assertRaises(RuntimeError):
            check_import("no summary", 10)
