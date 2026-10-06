"""OpenLink Virtuoso Open Source, bulk-loaded with ``ld_dir``/``rdf_loader_run`` as in the paper campaigns."""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import requests

from benchmark_core.systems import docker, resources
from benchmark_core.systems.base import ServerHandle, ServerSystem

VIRTUOSO_VERSION = "7.2.17"
VIRTUOSO_IMAGE = f"kgconstruct/virtuoso:v{VIRTUOSO_VERSION}"
LOAD_GRAPH_IRI = "http://example.com/graph"   # the HTTP client queries this graph (see client.py)
_PASSWORD = "root"
_ISQL = ["isql", "-U", "dba", "-P", _PASSWORD]


class Virtuoso(ServerSystem):
    system_id = "virtuoso/default"
    container = "vortex-rdf-bench-virtuoso"
    image = VIRTUOSO_IMAGE
    persistent = True
    port = 8890
    query_path = "/sparql"

    def _environment(self) -> dict[str, str]:
        buffers, dirty = resources.virtuoso_buffers()
        return {"DBA_PASSWORD": _PASSWORD, "VIRT_SPARQL_ResultSetMaxRows": "10000000",
                "VIRT_SPARQL_MaxQueryExecutionTime": "0", "VIRT_SPARQL_ExecutionTimeout": "0",
                "VIRT_SPARQL_MaxQueryCostEstimationTime": "0", "VIRT_Parameters_MaxVectorSize": "3000000",
                "VIRT_Parameters_NumberOfBuffers": str(buffers), "VIRT_Parameters_MaxDirtyBuffers": str(dirty)}

    def _launch(self, source_dir: Path, store: Path) -> None:
        docker.run_detached(self.container, self.image, ports={8890: 8890, 1111: 1111},
                            environment=self._environment(),
                            volumes=[f"{source_dir.resolve()}:/usr/share/proj", f"{store.resolve()}:/database"])

    def _wait_online(self, timeout_s: float) -> None:
        docker.wait_until(lambda: "Server online at" in docker.logs(self.container, tail=2000), timeout_s=timeout_s,
                          alive=lambda: docker.is_running(self.container), what="virtuoso")
        docker.wait_until(self.ready, timeout_s=timeout_s, alive=lambda: docker.is_running(self.container),
                          what="virtuoso")

    def _isql(self, statement: str, timeout_s: float | None = None) -> str:
        code, output = docker.exec_in(self.container, [*_ISQL, f"exec={statement}"], timeout=timeout_s)
        if code != 0:
            raise RuntimeError(f"isql failed ({statement}): {output[-500:]}")
        return output

    def build(self, *, source: Path, store: Path, timeout_s: float = 10800.0) -> dict[str, Any]:
        source, store = Path(source).resolve(), Path(store).resolve()
        if store.exists() and any(store.iterdir()):
            raise FileExistsError(f"database directory is not empty: {store} (refusing to overwrite)")
        store.mkdir(parents=True, exist_ok=True)
        store.chmod(0o777)
        started = time.perf_counter_ns()
        self._launch(source.parent, store)
        sampler = self.sample_container(self.container)
        try:
            self._wait_online(600)
            self._isql(f"ld_dir('/usr/share/proj','{source.name}','{LOAD_GRAPH_IRI}');")
            outcomes: list[bool] = []

            def loader():
                code, _ = docker.exec_in(self.container, [*_ISQL, "exec=rdf_loader_run();"], timeout=timeout_s)
                outcomes.append(code == 0)

            threads = [threading.Thread(target=loader, daemon=True) for _ in range(resources.VIRTUOSO_LOADER_CORES)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            if len(outcomes) != resources.VIRTUOSO_LOADER_CORES or not all(outcomes):
                raise RuntimeError("one or more Virtuoso loader threads failed")
            # rdf_loader_run() disables checkpoints and the scheduler; re-enable them.
            for statement in ("checkpoint;", "checkpoint_interval(60);", "scheduler_interval(10);"):
                self._isql(statement)
            count = self._graph_count()
            if count <= 0:
                raise RuntimeError("Virtuoso loaded graph is empty")
            self._isql("checkpoint;")
        finally:
            memory = sampler.stop()
            self.stop()
        return {"build": {"elapsed_ns": time.perf_counter_ns() - started, "graph_triples": count, "memory": memory}}

    def _graph_count(self) -> int:
        response = requests.post(self.endpoint, data={"query": "SELECT (COUNT(*) AS ?count) WHERE { GRAPH <"
                                 + LOAD_GRAPH_IRI + "> { ?s ?p ?o } }"},
                                 headers={"Accept": "application/sparql-results+json"}, timeout=3600)
        response.raise_for_status()
        return int(response.json()["results"]["bindings"][0]["count"]["value"])

    def start(self, *, source: Path | None, store: Path | None) -> ServerHandle:
        if store is None:
            raise ValueError("virtuoso/default needs a built database directory")
        started = time.monotonic()
        self._launch(Path(source).parent if source else Path(store), Path(store))
        self._wait_online(self.ready_timeout_s)
        return ServerHandle(self.system_id, self.container, self.endpoint, time.monotonic() - started)

    def stop(self) -> None:
        if docker.is_running(self.container):
            docker.exec_in(self.container, [*_ISQL, "exec=checkpoint;"], timeout=600)
        docker.remove(self.container)
