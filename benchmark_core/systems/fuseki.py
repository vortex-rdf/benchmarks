"""Apache Jena Fuseki (``fuseki-server``), in-memory or TDB2, as in the paper campaigns.

The in-memory dataset is filled by one HTTP upload of the N-Triples file. TDB2 is built as Jena documents it:
``tdb2.tdbloader`` bulk-loads the database, then ``tdb2.tdbstats`` writes ``Data-0001/stats.opt``, the statistics
the TDB2 optimizer uses to order BGP joins. Both tools run from the image's ``fuseki-server.jar``.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import requests

from benchmark_core.systems import docker, resources
from benchmark_core.systems.base import ServerHandle, ServerSystem

FUSEKI_VERSION = "6.2.0"
FUSEKI_IMAGE = f"vortex-rdf-bench/fuseki:v{FUSEKI_VERSION}"
_COMMANDS = {"memory": "--mem --update /ds", "tdb2": "--tdb2 --update --loc /fuseki/databases/DB /ds"}
_DATABASE = "/fuseki/databases/DB"


class Fuseki(ServerSystem):
    docker_context = Path(__file__).resolve().parents[2] / "docker" / "fuseki"
    port = 3030
    query_path = "/ds/sparql"

    def __init__(self, mode: str, *, port: int = 3030):
        if mode not in _COMMANDS:
            raise ValueError("mode must be 'memory' or 'tdb2'")
        self.mode = mode
        self.system_id = f"fuseki/{mode}"
        self.container = f"vortex-rdf-bench-fuseki-{mode}"
        self.image = FUSEKI_IMAGE
        self.persistent = mode == "tdb2"
        self.port = port

    def _launch(self, store: Path | None) -> None:
        initial, maximum = resources.FUSEKI_HEAPS[self.mode]
        volumes = [f"{Path(store).resolve()}:{_DATABASE}"] if store is not None else []
        docker.run_detached(self.container, self.image, _COMMANDS[self.mode].split(),
                            ports={self.port: self.port}, volumes=volumes,
                            environment={"JAVA_OPTIONS": f"-Xms{initial} -Xmx{maximum}"})

    def _ready_query(self) -> bool:
        response = requests.post(f"http://localhost:{self.port}/ds/query", data={"query": "ASK { }"},
                                 headers={"Accept": "application/sparql-results+json"}, timeout=5)
        response.raise_for_status()
        return "boolean" in response.json()

    def ready(self) -> bool:
        return self._ready_query()

    def _upload(self, source: Path) -> float:
        started = time.monotonic()
        with Path(source).open("rb") as stream:
            response = requests.post(f"http://localhost:{self.port}/ds", data=stream,
                                     headers={"Content-Type": "application/n-triples"}, timeout=(30, 10800))
        response.raise_for_status()
        return time.monotonic() - started

    def build(self, *, source: Path, store: Path, timeout_s: float = 10800.0) -> dict[str, Any]:
        self.ensure_image()
        if self.mode != "tdb2":
            raise NotImplementedError("the in-memory dataset has no store to build")
        source, store = Path(source).resolve(), Path(store).resolve()
        if store.exists() and any(store.iterdir()):
            raise FileExistsError(f"database directory is not empty: {store} (refusing to overwrite)")
        store.mkdir(parents=True, exist_ok=True)
        store.chmod(0o777)  # the container user is not the host user
        _, maximum = resources.FUSEKI_HEAPS[self.mode]
        java = f"java -Xmx{maximum} -cp /fuseki/fuseki-server.jar"
        script = (f"{java} tdb2.tdbloader --loc {_DATABASE} /source/{source.name}"
                  f" && {java} tdb2.tdbstats --loc {_DATABASE} > /tmp/stats.opt"
                  f" && mv /tmp/stats.opt {_DATABASE}/Data-0001/stats.opt")
        result = self.measured_one_shot(f"{self.container}-load", self.image, ["-c", script],
                                        volumes=[f"{source.parent}:/source:ro", f"{store}:{_DATABASE}"],
                                        timeout_s=timeout_s, extra=["--entrypoint", "sh"])
        docker.make_user_writable(store, self.image)
        if result.get("exit_code") != 0 or not (store / "Data-0001" / "stats.opt").is_file():
            raise RuntimeError(f"tdb2.tdbloader/tdbstats failed: {result.get('error') or result.get('logs')}")
        result["loader"] = "tdb2.tdbloader (default loader) + tdb2.tdbstats"
        return {"build": result}

    def start(self, *, source: Path | None, store: Path | None) -> ServerHandle:
        self.ensure_image()
        if self.mode == "tdb2" and store is None:
            raise ValueError("fuseki/tdb2 needs a built database directory")
        if self.mode == "memory" and source is None:
            raise ValueError("fuseki/memory needs the N-Triples source to load")
        started = time.monotonic()
        self._launch(store if self.mode == "tdb2" else None)
        docker.wait_until(self.ready, timeout_s=self.ready_timeout_s,
                          alive=lambda: docker.is_running(self.container), what="fuseki")
        load_s = self._upload(Path(source)) if self.mode == "memory" else None
        return ServerHandle(self.system_id, self.container, self.endpoint, time.monotonic() - started, load_s)
