import unittest

from benchmark_core.systems import resources
from benchmark_core.systems.fuseki import FUSEKI_IMAGE, Fuseki
from benchmark_core.systems.oxigraph import OXIGRAPH_IMAGE, Oxigraph
from benchmark_core.systems.qlever import QLever
from benchmark_core.systems.registry import get_system, system_ids
from benchmark_core.systems.virtuoso import Virtuoso


class SystemTests(unittest.TestCase):
    def test_registry_ids_and_endpoints(self):
        self.assertEqual(system_ids(), ["comunica/hdt", "fuseki/memory", "fuseki/tdb2", "oxigraph/memory",
                                        "oxigraph/rocksdb", "qlever/default", "virtuoso/default"])
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
        self.assertEqual(get_system("hdt-rdflib/optimized-in-memory").engine, "hdt")
        self.assertEqual(get_system("rdflib/default").endpoint, "http://localhost:7880/sparql")

    def test_persistence_flags(self):
        persistent = {s for s in system_ids() if get_system(s).persistent}
        self.assertEqual(persistent, {"fuseki/tdb2", "oxigraph/rocksdb", "qlever/default", "virtuoso/default"})

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
