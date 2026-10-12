"""qEndpoint (RDF4J on HDT), upstream image, serving the benchmark's own HDT file.

The HDT file and its index are copied (before the timer) to ``<hdt dir>/qendpoint-work/hdt-store/index_dev.hdt``,
where the endpoint looks for its dataset, so the shared representation files are never written by it.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path

from benchmark_core.systems import docker, resources
from benchmark_core.systems.base import ServerHandle, ServerSystem

QENDPOINT_VERSION = "2.5.4"
QENDPOINT_IMAGE = f"vortex-rdf-bench/qendpoint:{QENDPOINT_VERSION}"


class QEndpoint(ServerSystem):
    docker_context = Path(__file__).resolve().parents[2] / "docker" / "qendpoint"
    system_id = "qendpoint/hdt"
    container = "vortex-rdf-bench-qendpoint"
    image = QENDPOINT_IMAGE
    persistent = False
    port = 1234
    query_path = "/api/endpoint/sparql"

    @staticmethod
    def prepare_work_dir(hdt: Path) -> Path:
        work = Path(hdt).resolve().parent / "qendpoint-work"
        store = work / "hdt-store"
        store.mkdir(parents=True, exist_ok=True)
        for name, suffix in ((hdt.name, ""), (hdt.name + ".index.v1-1", ".index.v1-1")):
            source, target = hdt.parent / name, store / f"index_dev.hdt{suffix}"
            if source.is_file() and not (target.is_file() and target.stat().st_size == source.stat().st_size):
                shutil.copy2(source, target)
        work.chmod(0o777)
        for path in work.rglob("*"):
            path.chmod(0o777 if path.is_dir() else 0o666)
        return work

    def start(self, *, source: Path | None, store: Path | None) -> ServerHandle:
        if store is None or Path(store).suffix.lower() != ".hdt":
            raise ValueError("qendpoint/hdt needs the dataset.hdt artifact")
        self.ensure_image()
        work = self.prepare_work_dir(Path(store))
        started = time.monotonic()
        script = f"cd /data && exec java -jar -Xmx{resources.QENDPOINT_HEAP} /app/qendpoint.jar"
        docker.run_detached(self.container, self.image, ["-c", script], ports={self.port: self.port},
                            volumes=[f"{work}:/data"], extra=["--entrypoint", "sh"])
        docker.wait_until(self.ready, timeout_s=self.ready_timeout_s,
                          alive=lambda: docker.is_running(self.container), what="qendpoint")
        return ServerHandle(self.system_id, self.container, self.endpoint, time.monotonic() - started,
                            extra={"heap": resources.QENDPOINT_HEAP})
