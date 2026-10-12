"""Fluree DB 4 (``fluree create --from`` bulk import, ``fluree server run`` to serve), upstream image."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from benchmark_core.systems import docker, resources
from benchmark_core.systems.base import ServerHandle, ServerSystem

FLUREE_VERSION = "4.2.3"
FLUREE_IMAGE = f"vortex-rdf-bench/fluree:{FLUREE_VERSION}"
LEDGER = "bench"
STATE_DIR = "/var/lib/fluree"       # the image's working directory and volume: .fluree/ (config and storage)


class Fluree(ServerSystem):
    docker_context = Path(__file__).resolve().parents[2] / "docker" / "fluree"
    system_id = "fluree/default"
    container = "vortex-rdf-bench-fluree"
    image = FLUREE_IMAGE
    persistent = True
    port = 8090
    query_path = f"/v1/fluree/query/{LEDGER}"

    def build(self, *, source: Path, store: Path, timeout_s: float = 10800.0) -> dict[str, Any]:
        self.ensure_image()
        source, store = Path(source).resolve(), Path(store).resolve()
        if store.exists() and any(store.iterdir()):
            raise FileExistsError(f"ledger directory is not empty: {store} (refusing to overwrite)")
        store.mkdir(parents=True, exist_ok=True)
        store.chmod(0o777)      # the image runs as uid 1000
        script = (f"cd {STATE_DIR} && fluree init && fluree create {LEDGER} --from /source/{source.name} "
                  f"--memory-budget-mb {resources.FLUREE_IMPORT_MEMORY_MB} --parallelism {resources.FLUREE_IMPORT_THREADS}")
        try:
            result = self.measured_one_shot(
                f"{self.container}-import", self.image, ["-c", script],
                volumes=[f"{source.parent}:/source:ro", f"{store}:{STATE_DIR}"], timeout_s=timeout_s,
                extra=["--entrypoint", "sh"])
        finally:
            docker.make_user_writable(store, self.image)
        if result.get("exit_code") != 0:
            raise RuntimeError(f"fluree create failed: {result.get('error') or result.get('logs')}")
        result["representation_size_bytes"] = sum(p.stat().st_size for p in store.rglob("*") if p.is_file())
        return {"build": result}

    def start(self, *, source: Path | None, store: Path | None) -> ServerHandle:
        self.ensure_image()
        if store is None:
            raise ValueError("fluree/default needs the directory its import created")
        started = time.monotonic()
        docker.run_detached(self.container, self.image, [], ports={self.port: self.port},
                            volumes=[f"{Path(store).resolve()}:{STATE_DIR}"])
        docker.wait_until(self.ready, timeout_s=self.ready_timeout_s,
                          alive=lambda: docker.is_running(self.container), what="fluree")
        return ServerHandle(self.system_id, self.container, self.endpoint, time.monotonic() - started)
