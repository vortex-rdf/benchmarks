"""QLever (index with ``qlever-index``, serve with ``qlever-server``), as in the paper campaigns."""
from __future__ import annotations

import os
import shlex
import time
from pathlib import Path
from typing import Any

from benchmark_core.systems import docker, resources
from benchmark_core.systems.base import ServerHandle, ServerSystem

QLEVER_IMAGE = "vortex-rdf-bench/qlever:v0.6.0"
_RUNTIME_SUFFIXES = (".metrics-log.jsonl", ".resource-usage-log.tsv")


class QLever(ServerSystem):
    docker_context = Path(__file__).resolve().parents[2] / "docker" / "qlever"
    system_id = "qlever/default"
    container = "vortex-rdf-bench-qlever"
    image = QLEVER_IMAGE
    persistent = True
    port = 7001
    query_path = ""

    def __init__(self, *, port: int = 7001):
        self.port = port
        self._environment = {"UID": str(os.getuid()), "GID": str(os.getgid())}

    def _index_command(self, source_name: str) -> list[str]:
        script = ("/qlever/qlever-index --index-basename /data/dataset "
                  f"--kg-input-file {shlex.quote('/source/' + source_name)} --file-format nt")
        return ["-c", script]

    def _server_command(self) -> list[str]:
        script = (f"exec /qlever/qlever-server --index-basename /data/dataset --port {self.port}"
                  f" --memory-max-size {resources.QLEVER_QUERY_MEMORY} --cache-max-size {resources.QLEVER_CACHE_MEMORY}"
                  f" -j {resources.QLEVER_SIMULTANEOUS_QUERIES}")
        return ["-c", script]

    def build(self, *, source: Path, store: Path, timeout_s: float = 10800.0) -> dict[str, Any]:
        self.ensure_image()
        source, store = Path(source).resolve(), Path(store).resolve()
        if store.exists() and any(store.iterdir()):
            raise FileExistsError(f"index directory is not empty: {store} (refusing to overwrite)")
        store.mkdir(parents=True, exist_ok=True)
        store.chmod(0o777)
        result = self.measured_one_shot(
            f"{self.container}-index", self.image, self._index_command(source.name),
            volumes=[f"{source.parent}:/source:ro", f"{store}:/data"], timeout_s=timeout_s,
            environment=self._environment, workdir="/data")
        if result.get("exit_code") != 0:
            raise RuntimeError(f"qlever-index failed: {result.get('error') or result.get('logs')}")
        files = [p for p in store.rglob("*") if p.is_file() and not p.name.endswith(_RUNTIME_SUFFIXES)]
        result["representation_size_bytes"] = sum(p.stat().st_size for p in files)
        return {"build": result}

    def start(self, *, source: Path | None, store: Path | None) -> ServerHandle:
        self.ensure_image()
        if store is None:
            raise ValueError("qlever/default needs a built index directory")
        started = time.monotonic()
        docker.run_detached(self.container, self.image, self._server_command(), ports={self.port: self.port},
                            volumes=[f"{Path(store).resolve()}:/data"], environment=self._environment, workdir="/data")
        docker.wait_until(self.ready, timeout_s=self.ready_timeout_s,
                          alive=lambda: docker.is_running(self.container), what="qlever")
        return ServerHandle(self.system_id, self.container, self.endpoint, time.monotonic() - started)
