"""qEndpoint (RDF4J on HDT), upstream image, with its own HDT store built from the N-Triples source.

qEndpoint rejects the benchmark's HDT files (its reader needs a base URI in the HDT header, which the Rust
converter leaves empty), so the store is built the documented way: the running endpoint receives the N-Triples file
on ``/api/endpoint/load`` and writes ``qendpoint/hdt-store/index_dev.hdt`` plus its index under its working directory.
That upload is the build step, measured in the container's cgroup like every other store build.
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any

from benchmark_core.systems import docker, resources
from benchmark_core.systems.base import ServerHandle, ServerSystem

QENDPOINT_VERSION = "2.5.4"
QENDPOINT_IMAGE = f"vortex-rdf-bench/qendpoint:{QENDPOINT_VERSION}"
STATE_DIR = "/data"             # working directory of the endpoint; its repository is ./qendpoint/


class QEndpoint(ServerSystem):
    docker_context = Path(__file__).resolve().parents[2] / "docker" / "qendpoint"
    system_id = "qendpoint/hdt"
    container = "vortex-rdf-bench-qendpoint"
    image = QENDPOINT_IMAGE
    persistent = True
    port = 1234
    query_path = "/api/endpoint/sparql"

    def _launch(self, store: Path) -> None:
        script = f"cd {STATE_DIR} && exec java -jar -Xmx{resources.QENDPOINT_HEAP} /app/qendpoint.jar"
        docker.run_detached(self.container, self.image, ["-c", script], ports={self.port: self.port},
                            volumes=[f"{store}:{STATE_DIR}"], extra=["--entrypoint", "sh"])

    def build(self, *, source: Path, store: Path, timeout_s: float = 10800.0) -> dict[str, Any]:
        self.ensure_image()
        source, store = Path(source).resolve(), Path(store).resolve()
        if store.exists() and any(store.iterdir()):
            raise FileExistsError(f"endpoint directory is not empty: {store} (refusing to overwrite)")
        store.mkdir(parents=True, exist_ok=True)
        store.chmod(0o777)
        started = time.perf_counter_ns()
        self._launch(store)
        sampler = self.sample_container(self.container)
        try:
            docker.wait_until(self.ready, timeout_s=300, alive=lambda: docker.is_running(self.container),
                              what="qendpoint")
            upload = subprocess.run(
                ["curl", "-sS", "--fail-with-body", "--max-time", str(int(timeout_s)), "-F", f"file=@{source}",
                 f"http://localhost:{self.port}/api/endpoint/load"], capture_output=True, text=True)
            if upload.returncode != 0:
                raise RuntimeError(f"qendpoint load failed: {(upload.stderr or upload.stdout)[-600:]}")
            logs = (upload.stdout or "")[-800:]
        finally:
            memory = sampler.stop()
            docker.stop(self.container)
            docker.make_user_writable(store, self.image)
        size = sum(p.stat().st_size for p in (store / "qendpoint" / "hdt-store").rglob("*") if p.is_file())
        return {"build": {"elapsed_ns": time.perf_counter_ns() - started, "memory": memory, "logs": logs,
                          "representation_size_bytes": size}}

    def start(self, *, source: Path | None, store: Path | None) -> ServerHandle:
        self.ensure_image()
        if store is None:
            raise ValueError("qendpoint/hdt needs the directory its load created")
        started = time.monotonic()
        self._launch(Path(store).resolve())
        docker.wait_until(self.ready, timeout_s=self.ready_timeout_s,
                          alive=lambda: docker.is_running(self.container), what="qendpoint")
        return ServerHandle(self.system_id, self.container, self.endpoint, time.monotonic() - started,
                            extra={"heap": resources.QENDPOINT_HEAP})
