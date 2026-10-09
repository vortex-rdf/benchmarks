"""Common interface of the server systems compared over SPARQL HTTP.

Life cycle of one system: ``build`` (persistent stores only: create the on-disk store from the
N-Triples source, measured in a container cgroup) -> ``start`` (container up, data loaded for
in-memory servers, until the server answers queries; ``start_to_ready_s`` is recorded) ->
queries through :mod:`benchmark_core.http_runner.runner` -> ``stop``.
"""
from __future__ import annotations

import abc
import dataclasses
import threading
import time
from pathlib import Path
from typing import Any

from benchmark_core.http_runner.cgroup import ContainerCgroupMemory
from benchmark_core.http_runner.memory import PhaseAwareMemorySampler
from benchmark_core.systems import docker, resources


@dataclasses.dataclass
class ServerHandle:
    system_id: str
    container: str
    endpoint: str                      # published (host) query endpoint
    start_to_ready_s: float
    load_s: float | None = None        # in-memory servers: time to load the dataset
    extra: dict[str, Any] = dataclasses.field(default_factory=dict)


class ServerSystem(abc.ABC):
    """One benchmarked server. Subclasses fill in images, commands and loading."""

    system_id: str
    container: str
    image: str
    persistent: bool = False           # needs ``build`` before ``start``
    query_path: str = "/query"
    port: int = 7878
    ready_timeout_s: float = 3600.0
    docker_context: Path | None = None     # Dockerfile directory of ``image`` (built on first use)

    def ensure_image(self) -> None:
        if self.docker_context is not None:
            docker.ensure_image(self.image, self.docker_context)

    # ---- required ----------------------------------------------------------------------
    @abc.abstractmethod
    def start(self, *, source: Path | None, store: Path | None) -> ServerHandle: ...

    # ---- optional ----------------------------------------------------------------------
    def build(self, *, source: Path, store: Path, timeout_s: float = 10800.0) -> dict[str, Any]:
        raise NotImplementedError(f"{self.system_id} has no persistent store to build")

    def stop(self) -> None:
        docker.remove(self.container)

    @property
    def endpoint(self) -> str:
        return f"http://localhost:{self.port}{self.query_path}"

    def provenance(self) -> dict[str, Any]:
        return {"system": self.system_id, "image": self.image, "image_digest": docker.image_digest(self.image),
                "container": self.container, "resource_profile": resources.provenance()}

    # ---- shared behaviour --------------------------------------------------------------
    def ready(self) -> bool:
        return docker.sparql_ask_ready(self.endpoint)

    def idle_probe(self) -> None:
        """A trivial request that only returns once the server is free (raises otherwise)."""
        docker.sparql_ask_ready(self.endpoint, timeout_s=5.0)

    def settle(self, *, timeout_s: float = 600.0) -> bool:
        """Untimed: wait until the server answers a trivial query quickly again.

        Called after a client timeout. Servers keep working on an abandoned query (and some cannot
        cancel it), so the next attempt must not start before the server is idle. A server that
        cannot be settled is restarted if it supports it.
        """
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            started = time.monotonic()
            try:
                self.idle_probe()
                if time.monotonic() - started < 2.0:
                    return True
            except Exception:  # noqa: BLE001 - any failure means "not idle yet"
                time.sleep(0.5)
        return False

    @staticmethod
    def sample_container(name: str) -> PhaseAwareMemorySampler:
        """Start a cgroup v2 memory sampler on a (possibly not yet running) container."""
        sampler = PhaseAwareMemorySampler(ContainerCgroupMemory(name), "docker-container-cgroup-v2")
        sampler.start()
        sampler.set_phase("build")
        return sampler

    def measured_one_shot(self, name: str, image: str, command: list[str], *, volumes: list[str],
                          timeout_s: float, environment: dict[str, str] | None = None,
                          user: str | None = None, workdir: str | None = None,
                          extra: list[str] | None = None) -> dict[str, Any]:
        """Run a loader/indexer container to completion, sampling its cgroup v2 memory.

        Returns elapsed time, exit code, logs and the anon/file/total memory peaks.
        """
        sampler = self.sample_container(name)
        stop = threading.Event()
        result: dict[str, Any] = {}

        def work():
            started = time.perf_counter_ns()
            try:
                code, logs = docker.run_to_exit(name, image, command, environment=environment, volumes=volumes,
                                                user=user, workdir=workdir, timeout=timeout_s, extra=extra or ())
                result.update(exit_code=code, logs=logs[-4000:])
            except Exception as error:  # noqa: BLE001
                result.update(exit_code=None, logs="", error=f"{type(error).__name__}: {error}")
            result["elapsed_ns"] = time.perf_counter_ns() - started
            stop.set()

        thread = threading.Thread(target=work, daemon=True)
        thread.start()
        stop.wait()
        thread.join()
        result["memory"] = sampler.stop()
        return result
