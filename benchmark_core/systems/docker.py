"""Thin Docker CLI helpers: one network, exact-name containers, readiness waits."""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from collections.abc import Callable, Mapping, Sequence

import requests

from benchmark_core.systems.resources import DOCKER_MEMORY

NETWORK = "vortex_rdf_bench"


class DockerError(RuntimeError):
    pass


def _run(args: Sequence[str], *, check: bool = True, timeout: float | None = None) -> subprocess.CompletedProcess:
    result = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout, check=False)
    if check and result.returncode != 0:
        raise DockerError(f"docker {' '.join(args[:3])} failed: {result.stderr.strip() or result.stdout.strip()}")
    return result


def ensure_network(name: str = NETWORK) -> None:
    if _run(["network", "inspect", name], check=False).returncode != 0:
        _run(["network", "create", name])


def remove(name: str) -> None:
    """Remove the container with exactly this name, if any."""
    _run(["rm", "-f", name], check=False)


def run_detached(name: str, image: str, command: Sequence[str] = (), *, environment: Mapping[str, str] | None = None,
                 ports: Mapping[int, int] | None = None, volumes: Sequence[str] = (), memory: str = DOCKER_MEMORY,
                 user: str | None = None, workdir: str | None = None,
                 extra: Sequence[str] = ()) -> str:
    """Start a long-running container (replacing a stale one of the same name) and return its id."""
    ensure_network()
    remove(name)
    args = ["run", "--detach", "--name", name, "--memory", memory, "--memory-swap", memory, "--network", NETWORK]
    if user:
        args += ["--user", user]
    if workdir:
        args += ["--workdir", workdir]
    for key, value in (environment or {}).items():
        args += ["--env", f"{key}={value}"]
    for host_port, container_port in (ports or {}).items():
        args += ["-p", f"{host_port}:{container_port}"]
    for volume in volumes:
        args += ["-v", volume]
    args += list(extra) + [image, *command]
    return _run(args).stdout.strip()


def run_to_exit(name: str, image: str, command: Sequence[str] = (), *, environment: Mapping[str, str] | None = None,
                volumes: Sequence[str] = (), memory: str = DOCKER_MEMORY, user: str | None = None,
                workdir: str | None = None, timeout: float | None = None,
                extra: Sequence[str] = ()) -> tuple[int, str]:
    """Run a one-shot container (a loader or indexer) to completion; return (exit code, logs)."""
    run_detached(name, image, command, environment=environment, volumes=volumes, memory=memory, user=user,
                 workdir=workdir, extra=extra)
    try:
        waited = _run(["wait", name], timeout=timeout)
        code = int(waited.stdout.strip() or 1)
    except subprocess.TimeoutExpired:
        remove(name)
        raise
    logs = _run(["logs", name], check=False)
    remove(name)
    return code, (logs.stdout + logs.stderr)


def logs(name: str, tail: int = 200) -> str:
    result = _run(["logs", "--tail", str(tail), name], check=False)
    return result.stdout + result.stderr


def is_running(name: str) -> bool:
    result = _run(["container", "inspect", "--format", "{{.State.Running}}", name], check=False)
    return result.returncode == 0 and result.stdout.strip() == "true"


def image_digest(image: str) -> str | None:
    """Content-addressed identity of a local image (repo digest if pulled, else the image id)."""
    result = _run(["image", "inspect", "--format", "{{json .RepoDigests}}|{{.Id}}", image], check=False)
    if result.returncode != 0:
        return None
    digests, _, image_id = result.stdout.strip().partition("|")
    try:
        listed = json.loads(digests)
    except json.JSONDecodeError:
        listed = []
    return listed[0] if listed else image_id


def wait_until(predicate: Callable[[], bool], *, timeout_s: float, interval_s: float = 1.0,
               alive: Callable[[], bool] | None = None, what: str = "server") -> float:
    """Poll until ``predicate`` holds; return the elapsed seconds."""
    started = time.monotonic()
    while time.monotonic() - started < timeout_s:
        if alive is not None and not alive():
            raise DockerError(f"{what} container exited before becoming ready")
        try:
            if predicate():
                return time.monotonic() - started
        except (requests.RequestException, ValueError):
            pass
        time.sleep(interval_s)
    raise DockerError(f"{what} was not ready within {timeout_s}s")


def sparql_ask_ready(endpoint: str, timeout_s: float = 30.0) -> bool:
    response = requests.post(endpoint, data={"query": "ASK { ?s ?p ?o }"},
                             headers={"Accept": "application/sparql-results+json"}, timeout=timeout_s)
    response.raise_for_status()
    response.json()
    return True


def exec_in(name: str, command: Sequence[str], *, timeout: float | None = None) -> tuple[int, str]:
    """``docker exec`` in a running container; return (exit code, combined output)."""
    result = _run(["exec", name, *command], check=False, timeout=timeout)
    return result.returncode, result.stdout + result.stderr


def make_user_writable(path: Path | str, image: str) -> None:
    """Let the host user manage files a container created as another user (chmod -R a+rwX)."""
    result = _run(["run", "--rm", "--user", "0:0", "--volume", f"{Path(path).resolve()}:/cleanup",
                   "--entrypoint", "sh", image, "-c", "chmod -R a+rwX /cleanup"], check=False)
    if result.returncode != 0:
        raise DockerError(f"cannot make {path} writable: {result.stderr.strip()}")
