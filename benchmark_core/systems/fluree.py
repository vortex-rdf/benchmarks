"""Fluree DB 4 (``fluree create --from`` bulk import, ``fluree server run`` to serve), upstream image."""
from __future__ import annotations

import math
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from benchmark_core.systems import docker, resources
from benchmark_core.systems.base import ServerHandle, ServerSystem

FLUREE_VERSION = "4.2.3"
FLUREE_IMAGE = f"vortex-rdf-bench/fluree:{FLUREE_VERSION}"
LEDGER = "bench"
STATE_DIR = "/var/lib/fluree"       # the image's working directory and volume: .fluree/ (config and storage)
# `fluree create --from <one large .nt>` splits the file itself and, on the DBpedia N-Triples, silently stopped after 6
# chunks (31.8M of 232.5M triples, exit code 0). A directory of line-aligned pieces imports completely.
SPLIT_ABOVE_BYTES = 700 * 1024 * 1024
PIECE_SIZE = "512M"


def check_import(logs: str, source_triples: int) -> int:
    """Fail unless the import reports about as many flakes as the source has triples (it prints millions, one decimal)."""
    match = re.search(r"Imported ([\d.]+)M flakes", logs)
    if match is None:
        raise RuntimeError("fluree create did not report the imported flake count")
    flakes_m = float(match.group(1))
    if flakes_m < source_triples / 1e6 * 0.98 - 0.06:
        raise RuntimeError(f"fluree imported {flakes_m}M flakes from {source_triples:,} source triples")
    return int(flakes_m * 1e6)


class Fluree(ServerSystem):
    docker_context = Path(__file__).resolve().parents[2] / "docker" / "fluree"
    system_id = "fluree/default"
    container = "vortex-rdf-bench-fluree"
    image = FLUREE_IMAGE
    persistent = True
    port = 8090
    query_path = f"/v1/fluree/query/{LEDGER}"

    def __init__(self):
        self.query_timeout_s: float | None = None     # set by the campaign

    def server_environment(self) -> dict[str, str]:
        """Fluree's own query timeout one second past the client's (its default is 15 minutes; it covers query
        execution, not building a very large result), and its cache budget made explicit."""
        timeout_ms = (math.ceil(self.query_timeout_s) + 1) * 1000 if self.query_timeout_s else 60_000
        return {"FLUREE_QUERY_TIMEOUT_MS": str(timeout_ms), "FLUREE_CACHE_MAX_MB": str(resources.FLUREE_CACHE_MB)}

    def build(self, *, source: Path, store: Path, timeout_s: float = 10800.0) -> dict[str, Any]:
        self.ensure_image()
        source, store = Path(source).resolve(), Path(store).resolve()
        if store.exists() and any(store.iterdir()):
            raise FileExistsError(f"ledger directory is not empty: {store} (refusing to overwrite)")
        store.mkdir(parents=True, exist_ok=True)
        store.chmod(0o777)      # the image runs as uid 1000
        result_extra: dict[str, Any] = {}
        mount, origin = source.parent, f"/source/{source.name}"
        pieces = None
        if source.suffix == ".nt" and source.stat().st_size > SPLIT_ABOVE_BYTES:
            pieces = store.with_name(store.name + ".pieces")
            began = time.monotonic()
            pieces.mkdir(parents=True)
            subprocess.run(["split", "-C", PIECE_SIZE, "-d", "-a", "4", "--additional-suffix=.nt", str(source),
                            str(pieces / "part-")], check=True)
            result_extra["source_split_s"] = round(time.monotonic() - began, 1)    # not part of the measured build
            result_extra["source_pieces"] = len(list(pieces.iterdir()))
            mount, origin = pieces, "/source"
        counted = subprocess.run(["grep", "-c", "-v", "-e", "^$", "-e", "^#", str(source)], capture_output=True, text=True)
        source_triples = int(counted.stdout.strip())
        script = (f"cd {STATE_DIR} && fluree init && fluree create {LEDGER} --from {origin} "
                  f"--memory-budget-mb {resources.FLUREE_IMPORT_MEMORY_MB} --parallelism {resources.FLUREE_IMPORT_THREADS}")
        try:
            result = self.measured_one_shot(
                f"{self.container}-import", self.image, ["-c", script],
                volumes=[f"{mount}:/source:ro", f"{store}:{STATE_DIR}"], timeout_s=timeout_s,
                extra=["--entrypoint", "sh"])
        finally:
            docker.make_user_writable(store, self.image)
            if pieces is not None:
                shutil.rmtree(pieces, ignore_errors=True)
        if result.get("exit_code") != 0:
            raise RuntimeError(f"fluree create failed: {result.get('error') or result.get('logs')}")
        result["imported_flakes"] = check_import(result.get("logs", ""), source_triples)
        result["source_triples"] = source_triples
        result.update(result_extra)
        result["representation_size_bytes"] = sum(p.stat().st_size for p in store.rglob("*") if p.is_file())
        return {"build": result}

    def start(self, *, source: Path | None, store: Path | None) -> ServerHandle:
        self.ensure_image()
        if store is None:
            raise ValueError("fluree/default needs the directory its import created")
        started = time.monotonic()
        environment = self.server_environment()
        docker.run_detached(self.container, self.image, [], ports={self.port: self.port},
                            volumes=[f"{Path(store).resolve()}:{STATE_DIR}"], environment=environment)
        docker.wait_until(self.ready, timeout_s=self.ready_timeout_s,
                          alive=lambda: docker.is_running(self.container), what="fluree")
        return ServerHandle(self.system_id, self.container, self.endpoint, time.monotonic() - started,
                            extra={"server_environment": environment})
