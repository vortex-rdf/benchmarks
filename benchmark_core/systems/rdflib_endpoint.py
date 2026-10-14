"""rdflib-based systems (Vortex-RDF, RDFLib, COTTAS, optimized HDT) behind one SPARQL HTTP endpoint.

All of them are served by ``docker/rdflib-endpoint`` (rdflib-endpoint + uvicorn, one worker), so the
HTTP layer, query parsing and result serialization are identical and only the store differs.

System identifiers (as in the experiment declarations):

* ``vortex-rdf/dictionary-secondary-by-{copy,reference}[-memory][-no-pushdown]``
* ``rdflib/default``  ``pycottas/default``  ``pycottas/endpoint`` (COTTAS's own router)  ``hdt-rdflib/optimized-in-memory``

``VORTEX_RDFLIB_VERSION`` (default 0.1.3) selects the image ``vortex-rdf-bench/rdflib-endpoint:vrl-<version>``;
it is built from ``docker/rdflib-endpoint`` on first use. ``VORTEX_RDFLIB_IMAGE`` overrides the image name.
Selected ``VORTEX_RDF_*`` tuning variables of the calling environment are passed into the container.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

import requests

from benchmark_core.systems import docker
from benchmark_core.systems.base import ServerHandle, ServerSystem

DOCKER_CONTEXT = Path(__file__).resolve().parents[2] / "docker" / "rdflib-endpoint"
BENCHMARK_CORE = Path(__file__).resolve().parents[1]      # mounted into the container for in-process workers
IMAGE_REPOSITORY = "vortex-rdf-bench/rdflib-endpoint"
DEFAULT_VORTEX_RDFLIB = "0.1.3"
# vortex-rdflib minor version -> the vortex-rdf it requires
VORTEX_RDF_FOR = {"0.1": "0.10.0", "0.2": "0.11.0"}
PASSTHROUGH = ("VORTEX_RDF_NATIVE_FILTERS", "VORTEX_RDF_FILTER_FAST", "VORTEX_RDF_DISABLE_CODE_PATH",
               "VORTEX_RDF_DICT_MAX_RESIDENT_BYTES", "VORTEX_RDF_DICT_MAX_RESIDENT_TERMS", "VORTEX_RDF_PUSHDOWN_OPS")
_VORTEX_ID = re.compile(r"^vortex-rdf/(dictionary|default)-(secondary-by-copy|secondary-by-reference|no-index)"
                        r"(-memory)?(-no-pushdown)?$")
PORT = 7880
SETTLE_WAIT_S = 30.0


PYCOTTAS_ENDPOINT = "0.5.3"


def matches(system_id: str) -> bool:
    vortex = _VORTEX_ID.match(system_id)
    if vortex and vortex.group(1) == "default" and vortex.group(4):
        return False        # the default (string) layout has no pushdown to disable
    return bool(vortex) or system_id in {"rdflib/default", "pycottas/default", "pycottas/endpoint",
                                                             "hdt-rdflib/optimized-in-memory"}


def image_name() -> tuple[str, str]:
    version = os.environ.get("VORTEX_RDFLIB_VERSION", DEFAULT_VORTEX_RDFLIB)
    return os.environ.get("VORTEX_RDFLIB_IMAGE", f"{IMAGE_REPOSITORY}:vrl-{version}"), version


def ensure_image(image: str, vortex_rdflib: str) -> None:
    """Build the endpoint image when it does not exist locally."""
    if docker.image_digest(image) is not None:
        return
    vortex_rdf = os.environ.get("VORTEX_RDF_VERSION") or VORTEX_RDF_FOR.get(".".join(vortex_rdflib.split(".")[:2]))
    if vortex_rdf is None:
        raise RuntimeError(f"no known vortex-rdf version for vortex-rdflib {vortex_rdflib}; set VORTEX_RDF_VERSION")
    print(f"building {image} (vortex-rdflib {vortex_rdflib}, vortex-rdf {vortex_rdf}); this takes a few minutes",
          flush=True)
    subprocess.run(["docker", "build", "-t", image, "--build-arg", f"VORTEX_RDFLIB_VERSION={vortex_rdflib}",
                    "--build-arg", f"VORTEX_RDF_VERSION={vortex_rdf}", str(DOCKER_CONTEXT)], check=True)


class RdflibEndpoint(ServerSystem):
    port = PORT
    query_path = "/sparql"

    def __init__(self, system_id: str, *, port: int = PORT):
        if not matches(system_id):
            raise ValueError(f"not an rdflib endpoint system: {system_id}")
        self.system_id = system_id
        self.port = port
        self.container = "vortex-rdf-bench-rdflib-" + re.sub(r"[^A-Za-z0-9._-]+", "-", system_id)
        self.image, self.vortex_rdflib_version = image_name()
        self.persistent = False
        self.ready_timeout_s = float(os.environ.get("VORTEX_RDF_BENCH_READY_TIMEOUT_S", "3600"))
        self._last: tuple[Path | None, Path | None] | None = None
        self.query_timeout_s: float | None = None     # set by the campaign; enables server-side cancellation
        self.in_process = False     # set by the campaign: library mode, the engine runs in a worker in the container
        vortex = _VORTEX_ID.match(system_id)
        if vortex:
            self.engine, self.in_memory, self.pushdown = "vortex", bool(vortex.group(3)), not vortex.group(4)
        else:
            self.engine = {"rdflib/default": "rdflib", "pycottas/default": "cottas", "pycottas/endpoint": "cottas",
                           "hdt-rdflib/optimized-in-memory": "hdt"}[system_id]
            self.in_memory, self.pushdown = False, True
        # pycottas/endpoint: COTTAS's own router (pycottas-endpoint) on the same base image and middleware.
        self.router = "pycottas-endpoint" if system_id == "pycottas/endpoint" else "rdflib-endpoint"
        if self.router == "pycottas-endpoint":
            self.base_image, self.image = self.image, f"vortex-rdf-bench/pycottas-endpoint:{PYCOTTAS_ENDPOINT}-{self.image.rsplit(':', 1)[1]}"

    @property
    def endpoint(self) -> str:
        return f"http://localhost:{self.port}/sparql"

    def _arguments(self, artifact: Path) -> list[str]:
        args = ["--engine", self.engine, "--store", f"/data/{artifact.name}"]
        if self.in_memory:
            args.append("--in-memory")
        if not self.pushdown:
            args.append("--no-pushdown")
        if self.router != "rdflib-endpoint":
            args += ["--router", self.router]
        return args

    def _identity(self) -> dict[str, Any]:
        response = requests.get(f"http://localhost:{self.port}/ready", timeout=5)
        response.raise_for_status()
        return response.json()

    def start(self, *, source: Path | None, store: Path | None) -> ServerHandle:
        if store is None:
            raise ValueError(f"{self.system_id} needs its artifact (store) path")
        artifact = Path(store).resolve()
        if self.engine == "hdt" and not Path(str(artifact) + ".index.v1-1").is_file():
            raise FileNotFoundError(f"HDT query-ready index is missing: {artifact}.index.v1-1")
        self._last = (source, store)
        if self.router == "pycottas-endpoint":
            ensure_image(self.base_image, self.vortex_rdflib_version)
            if docker.image_digest(self.image) is None:
                subprocess.run(["docker", "build", "-t", self.image, "--build-arg", f"BASE={self.base_image}",
                                "--build-arg", f"PYCOTTAS_ENDPOINT_VERSION={PYCOTTAS_ENDPOINT}",
                                "-f", str(DOCKER_CONTEXT / "Dockerfile.pycottas-endpoint"), str(DOCKER_CONTEXT)], check=True)
        else:
            ensure_image(self.image, self.vortex_rdflib_version)
        environment = {name: os.environ[name] for name in PASSTHROUGH if name in os.environ}
        if self.in_process:
            # Same image and mounts; the container only idles, and the runner starts the engine inside it with
            # ``docker exec`` (see worker_command), so its memory is still charged to this container.
            self._store_path = f"/data/{artifact.name}"
            started = time.monotonic()
            docker.run_detached(self.container, self.image, ["infinity"], environment=environment,
                                volumes=[f"{artifact.parent}:/data:ro", f"{BENCHMARK_CORE}:/bench/benchmark_core:ro",
                                         f"{DOCKER_CONTEXT}:/bench/server:ro"],
                                extra=["--entrypoint", "sleep"])
            return ServerHandle(self.system_id, self.container, f"inproc://{self.container}",
                                time.monotonic() - started, extra={"transport": "in-process",
                                                                    "tuning_environment": environment})
        if self.query_timeout_s and os.environ.get("VORTEX_RDF_BENCH_SERVER_DEADLINE", "1") != "0":   # cancel server-side shortly after the client has given up
            environment["QUERY_DEADLINE_S"] = f"{self.query_timeout_s + 0.5:g}"
        started = time.monotonic()
        # The repository's serve_rdflib.py, not the image's copy (it fixes rdflib-endpoint's double decoding).
        docker.run_detached(self.container, self.image, self._arguments(artifact), ports={self.port: 8000},
                            volumes=[f"{artifact.parent}:/data:ro",
                                     f"{DOCKER_CONTEXT / 'serve_rdflib.py'}:/app/serve_rdflib.py:ro"],
                            environment=environment)
        alive = lambda: docker.is_running(self.container)  # noqa: E731
        docker.wait_until(lambda: bool(self._identity()), timeout_s=self.ready_timeout_s, alive=alive,
                          what=self.system_id)
        identity = self._identity()
        if self.engine == "vortex" and identity.get("sparql_pushdown") != self.pushdown:
            raise RuntimeError(f"pushdown state {identity.get('sparql_pushdown')} differs from requested {self.pushdown}")
        docker.wait_until(self.ready, timeout_s=self.ready_timeout_s, alive=alive, what=self.system_id)
        return ServerHandle(self.system_id, self.container, self.endpoint, time.monotonic() - started,
                            extra={"identity": identity, "tuning_environment": environment})

    def worker_command(self, timeout_s: float) -> list[str]:
        """argv that starts one in-process worker (``benchmark_core.http_runner.inproc``) in the container."""
        config = {"engine": self.engine, "store": self._store_path, "in_memory": self.in_memory,
                  "no_pushdown": not self.pushdown, "deadline_s": timeout_s + 0.5,
                  "server_dir": "/bench/server"}      # the repository's serve_rdflib.py, not the image's copy
        return ["docker", "exec", "-i", "-e", "PYTHONPATH=/bench", self.container,
                "python", "-m", "benchmark_core.http_runner.inproc", json.dumps(config)]

    def ready(self) -> bool:
        # ASK {} goes through SPARQL parsing, evaluation and serialization without touching the store;
        # ASK { ?s ?p ?o } makes pycottas scan the file, past the server deadline on BSBM 100K.
        response = requests.post(self.endpoint, data={"query": "ASK {}"},
                                 headers={"Accept": "application/sparql-results+json"}, timeout=30)
        response.raise_for_status()
        return response.json()["boolean"] is True

    def idle_probe(self) -> None:
        # The single event loop only answers /ready when no query is running. An ASK over all triples is
        # not trivial for every store (pycottas scans the whole file for ?s ?p ?o).
        requests.get(f"http://localhost:{self.port}/ready", timeout=5).raise_for_status()

    def settle(self, *, timeout_s: float | None = None) -> bool:
        """The endpoint cannot cancel a running query. Wait for the abandoned query to end, then restart.

        Engines that reopen in seconds (Vortex, COTTAS, HDT) wait at most ``SETTLE_WAIT_S``; RDFLib re-parses
        the whole dataset on restart, so it waits for the query to finish (up to ten minutes).
        """
        if self.in_process:
            # ponytail: fixed wait; the timed-out worker ends itself at deadline_s (0.5 s past the runner's timeout)
            time.sleep(1.0)
            return True
        wait = timeout_s if timeout_s is not None else (600.0 if self.engine == "rdflib" else SETTLE_WAIT_S)
        if super().settle(timeout_s=wait):
            return True
        if self._last is None:
            return False
        docker.remove(self.container)
        self.start(source=self._last[0], store=self._last[1])
        return True

    def provenance(self) -> dict[str, Any]:
        base = super().provenance()
        base.update({"engine": self.engine, "in_memory": self.in_memory, "pushdown": self.pushdown,
                     "vortex_rdflib_version": self.vortex_rdflib_version})
        return base
