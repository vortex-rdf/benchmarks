"""Comunica over the HDT file, served by its own SPARQL endpoint (``comunica-sparql-hdt-http``).

The endpoint serves ``dataset.hdt`` read-only (the same single-file mount and ``hdt`` source the
embedded worker used). Comunica enforces the per-query timeout itself, so it is started with the
runner's limit (``-t``); one worker (``-w 1``).
"""
from __future__ import annotations

import math
import time
from pathlib import Path

import requests

from benchmark_core.systems import docker
from benchmark_core.systems.base import ServerHandle, ServerSystem

COMUNICA_VERSION = "5.0.1"
COMUNICA_IMAGE = f"vortex-rdf-bench/comunica-hdt:v{COMUNICA_VERSION}"
DOCKER_CONTEXT = Path(__file__).resolve().parents[2] / "docker" / "comunica-hdt"
PORT = 7881


class ComunicaHdt(ServerSystem):
    system_id = "comunica/hdt"
    container = "vortex-rdf-bench-comunica-hdt"
    image = COMUNICA_IMAGE
    persistent = False
    port = PORT
    query_path = "/sparql"

    def __init__(self):
        self.query_timeout_s: float | None = None

    def start(self, *, source: Path | None, store: Path | None) -> ServerHandle:
        if store is None or Path(store).suffix.lower() != ".hdt":
            raise ValueError("comunica/hdt needs the dataset.hdt artifact")
        artifact = Path(store).resolve()
        if docker.image_digest(self.image) is None:
            import subprocess
            print(f"building {self.image}; this takes a few minutes", flush=True)
            subprocess.run(["docker", "build", "-t", self.image, str(DOCKER_CONTEXT)], check=True)
        timeout = max(1, math.ceil(self.query_timeout_s)) if self.query_timeout_s else 60
        started = time.monotonic()
        docker.run_detached(self.container, self.image,
                            ["hdt@/data/dataset.hdt", "-p", "3000", "-w", "1", "-t", str(timeout)],
                            ports={self.port: 3000}, volumes=[f"{artifact}:/data/dataset.hdt:ro"])
        docker.wait_until(self.ready, timeout_s=self.ready_timeout_s,
                          alive=lambda: docker.is_running(self.container), what="comunica")
        return ServerHandle(self.system_id, self.container, self.endpoint, time.monotonic() - started,
                            extra={"server_query_timeout_s": timeout})

    def ready(self) -> bool:
        response = requests.post(self.endpoint, data={"query": "ASK { ?s ?p ?o }"},
                                 headers={"Accept": "application/sparql-results+json"}, timeout=30)
        response.raise_for_status()
        response.json()
        return True
