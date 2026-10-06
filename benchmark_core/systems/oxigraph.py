"""Oxigraph server (``oxigraph serve``), in-memory or RocksDB-backed.

Same commands and image as the paper campaigns: the in-memory store is filled by one HTTP upload
of the N-Triples file; the RocksDB store is built once with the CLI loader (``--non-atomic``)
and then served with ``--location``.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import requests

from benchmark_core.systems import docker
from benchmark_core.systems.base import ServerHandle, ServerSystem

OXIGRAPH_VERSION = "0.5.9"
OXIGRAPH_IMAGE = f"dtaikg/oxigraph:{OXIGRAPH_VERSION}"


class Oxigraph(ServerSystem):
    port = 7878
    query_path = "/query"

    def __init__(self, backend: str, *, port: int = 7878):
        if backend not in {"memory", "rocksdb"}:
            raise ValueError("backend must be 'memory' or 'rocksdb'")
        self.backend = backend
        self.system_id = f"oxigraph/{backend}"
        self.container = f"vortex-rdf-bench-oxigraph-{backend}"
        self.image = OXIGRAPH_IMAGE
        self.persistent = backend == "rocksdb"
        self.port = port
        self._user = f"{os.getuid()}:{os.getgid()}"

    # -- persistent store ----------------------------------------------------------------
    def build(self, *, source: Path, store: Path, timeout_s: float = 10800.0) -> dict[str, Any]:
        if not self.persistent:
            raise NotImplementedError("the in-memory backend has no store to build")
        source = Path(source).resolve()
        store = Path(store).resolve()
        if store.exists() and any(store.iterdir()):
            raise FileExistsError(f"store directory is not empty: {store} (refusing to overwrite)")
        store.mkdir(parents=True, exist_ok=True)
        result = self.measured_one_shot(
            f"{self.container}-build", self.image,
            ["load", "--location", "/store", "--file", f"/data/{source.name}", "--format", "nt", "--non-atomic"],
            volumes=[f"{source.parent}:/data:ro", f"{store}:/store"], timeout_s=timeout_s, user=self._user)
        if result.get("exit_code") != 0:
            raise RuntimeError(f"oxigraph load failed: {result.get('error') or result.get('logs')}")
        return {"build": result}

    # -- serving -------------------------------------------------------------------------
    def start(self, *, source: Path | None, store: Path | None) -> ServerHandle:
        volumes: list[str] = []
        command = ["serve", "--bind", f"0.0.0.0:{self.port}"]
        if self.backend == "rocksdb":
            if store is None:
                raise ValueError("oxigraph/rocksdb needs a built store directory")
            volumes.append(f"{Path(store).resolve()}:/store")
            command += ["--location", "/store"]
        elif source is None:
            raise ValueError("oxigraph/memory needs the N-Triples source to load")
        started = time.monotonic()
        docker.run_detached(self.container, self.image, command, ports={self.port: self.port},
                            volumes=volumes, user=self._user if self.backend == "rocksdb" else None)
        load_s = None
        if self.backend == "memory":
            docker.wait_until(lambda: requests.get(f"http://localhost:{self.port}/", timeout=5).status_code < 500,
                              timeout_s=120, alive=lambda: docker.is_running(self.container), what="oxigraph")
            load_started = time.monotonic()
            with Path(source).open("rb") as stream:
                response = requests.post(f"http://localhost:{self.port}/store?default", data=stream,
                                         headers={"Content-Type": "application/n-triples"}, timeout=(30, 10800))
            response.raise_for_status()
            load_s = time.monotonic() - load_started
        docker.wait_until(self.ready, timeout_s=self.ready_timeout_s,
                          alive=lambda: docker.is_running(self.container), what="oxigraph")
        return ServerHandle(self.system_id, self.container, self.endpoint, time.monotonic() - started, load_s)
