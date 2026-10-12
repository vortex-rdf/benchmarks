"""MillenniumDB (``mdb import`` builds a database directory, ``mdb server`` answers SPARQL), upstream image.

The server takes the query as the raw POST body (``Content-Type: application/sparql-query``); the HTTP client
and ``ready`` therefore use ``raw_query`` for this system.
"""
from __future__ import annotations

import math
import time
from pathlib import Path
from typing import Any

import requests

from benchmark_core.http_runner.protocol import RAW_QUERY_SYSTEMS  # noqa: F401  (read by the HTTP client)
from benchmark_core.systems import docker, resources
from benchmark_core.systems.base import ServerHandle, ServerSystem

MDB_VERSION = "1.0.0"
MDB_IMAGE = f"vortex-rdf-bench/millenniumdb:{MDB_VERSION}"


class MillenniumDB(ServerSystem):
    docker_context = Path(__file__).resolve().parents[2] / "docker" / "millenniumdb"
    system_id = "millenniumdb/default"
    container = "vortex-rdf-bench-millenniumdb"
    image = MDB_IMAGE
    persistent = True
    port = 1234
    query_path = "/sparql"

    def __init__(self):
        self.query_timeout_s: float | None = None

    def build(self, *, source: Path, store: Path, timeout_s: float = 10800.0) -> dict[str, Any]:
        self.ensure_image()
        source, store = Path(source).resolve(), Path(store).resolve()
        if store.exists() and any(store.iterdir()):
            raise FileExistsError(f"database directory is not empty: {store} (refusing to overwrite)")
        store.mkdir(parents=True, exist_ok=True)
        store.chmod(0o777)
        # N-Triples is Turtle: the Sparqloscope setup imports from stdin with --format ttl. The positional form
        # (`mdb import <file> <db>`) is the older documented one and is tried if the first fails.
        src = f"/source/{source.name}"
        script = (f"(mdb import /data/db --format ttl --buffer-strings {resources.MDB_STRING_BUFFERS} < {src}) "
                  f"|| (rm -rf /data/db && mdb import {src} /data/db)")
        try:
            result = self.measured_one_shot(
                f"{self.container}-import", self.image, ["bash", "-c", script],
                volumes=[f"{source.parent}:/source:ro", f"{store}:/data"], timeout_s=timeout_s, workdir="/data")
        finally:
            docker.make_user_writable(store, self.image)
        if result.get("exit_code") != 0:
            raise RuntimeError(f"mdb import failed: {result.get('error') or result.get('logs')}")
        result["representation_size_bytes"] = sum(p.stat().st_size for p in store.rglob("*") if p.is_file())
        return {"build": result}

    def _server_command(self) -> list[str]:
        timeout = math.ceil(self.query_timeout_s) + 1 if self.query_timeout_s else 60
        return ["mdb", "server", "--timeout", str(timeout), "--threads", str(resources.MDB_THREADS),
                "--versioned-buffer", resources.MDB_VERSIONED_BUFFER,
                "--private-buffer", resources.MDB_PRIVATE_BUFFER,
                "--strings-static", resources.MDB_STRING_BUFFERS, "--strings-dynamic", resources.MDB_STRING_BUFFERS, "."]

    def start(self, *, source: Path | None, store: Path | None) -> ServerHandle:
        self.ensure_image()
        if store is None:
            raise ValueError("millenniumdb/default needs the directory its import created")
        started = time.monotonic()
        docker.run_detached(self.container, self.image, self._server_command(), ports={self.port: self.port},
                            volumes=[f"{Path(store).resolve()}:/data"], workdir="/data/db")
        docker.wait_until(self.ready, timeout_s=self.ready_timeout_s,
                          alive=lambda: docker.is_running(self.container), what="millenniumdb")
        return ServerHandle(self.system_id, self.container, self.endpoint, time.monotonic() - started,
                            extra={"server_query_timeout_s": self._server_command()[3]})

    def ready(self) -> bool:
        response = requests.post(self.endpoint, data=b"ASK {}", timeout=30,
                                 headers={"Content-Type": "application/sparql-query",
                                          "Accept": "application/sparql-results+json"})
        response.raise_for_status()
        response.json()
        return True

    def idle_probe(self) -> None:
        self.ready()
