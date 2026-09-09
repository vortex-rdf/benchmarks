"""Measure representation-build commands and declared persistent paths."""
from __future__ import annotations

import subprocess
import threading
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import psutil

BUILD_SCHEMA = "rdf-representation-build-metrics-v1"
SIZE_SCHEMA = "rdf-representation-size-v1"


def measure_representation_size(paths: Sequence[Path]) -> dict[str, Any]:
    """Measure exact declared files or directory trees without following links."""
    if not isinstance(paths, Sequence) or isinstance(paths, (str, bytes)) or not paths:
        raise ValueError("paths must be a non-empty sequence")
    roots: list[Path] = []
    seen: set[Path] = set()
    for value in paths:
        if not isinstance(value, Path):
            raise TypeError("representation paths must be Path values")
        root = value.expanduser().resolve()
        if root in seen:
            raise ValueError("representation paths must be unique")
        if not root.exists():
            raise FileNotFoundError(f"representation path is missing: {root}")
        if root.is_symlink():
            raise ValueError(f"representation root must not be a symlink: {root}")
        seen.add(root)
        roots.append(root)

    logical = allocated = file_count = directory_count = 0
    for root in roots:
        entries = [root] if root.is_file() else [root, *root.rglob("*")]
        for entry in entries:
            if entry.is_symlink():
                raise ValueError(f"representation contains a symlink: {entry}")
            info = entry.stat(follow_symlinks=False)
            if entry.is_file():
                file_count += 1
                logical += info.st_size
                allocated += info.st_blocks * 512
            elif entry.is_dir():
                directory_count += 1
            else:
                raise ValueError(f"unsupported representation entry: {entry}")
    return {
        "schema": SIZE_SCHEMA,
        "boundary": "adapter-declared-paths",
        "paths": [str(path) for path in roots],
        "logical_bytes": logical,
        "allocated_bytes": allocated,
        "file_count": file_count,
        "directory_count": directory_count,
    }


def _process_tree_rss_bytes(pid: int) -> int | None:
    """Return concurrent RSS for one live process tree."""
    try:
        process = psutil.Process(pid)
        processes = [process, *process.children(recursive=True)]
    except (psutil.NoSuchProcess, psutil.ZombieProcess):
        return None
    total = 0
    found = False
    for current in processes:
        try:
            total += current.memory_info().rss
            found = True
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
            continue
    return total if found else None


def run_build_command(
    command: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str] | None = None,
    log_path: Path | None = None,
    interval_s: float = 0.01,
) -> dict[str, Any]:
    """Run one builder and measure wall time plus concurrent process-tree RSS."""
    if not isinstance(command, Sequence) or isinstance(command, (str, bytes)):
        raise TypeError("command must be a sequence")
    argv = list(command)
    if not argv or any(not isinstance(item, str) or not item for item in argv):
        raise ValueError("command entries must be non-empty strings")
    if not isinstance(cwd, Path) or not cwd.is_dir():
        raise ValueError("cwd must be an existing directory")
    if interval_s <= 0:
        raise ValueError("interval_s must be positive")
    if environment is not None and (
        not isinstance(environment, Mapping)
        or any(not isinstance(key, str) or not isinstance(value, str)
               for key, value in environment.items())
    ):
        raise TypeError("environment must map strings to strings")

    stream = subprocess.DEVNULL
    opened = None
    if log_path is not None:
        if not isinstance(log_path, Path):
            raise TypeError("log_path must be a Path or None")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        opened = log_path.open("w", encoding="utf-8")
        stream = opened

    started_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    started_ns = time.perf_counter_ns()
    process = None
    peak = samples = errors = 0
    stop = threading.Event()

    def sample() -> None:
        nonlocal peak, samples, errors
        if process is None:
            return
        try:
            value = _process_tree_rss_bytes(process.pid)
            if value is not None:
                peak = max(peak, value)
                samples += 1
        except (OSError, RuntimeError, TypeError, ValueError):
            errors += 1

    def worker() -> None:
        while not stop.wait(interval_s):
            sample()

    thread = threading.Thread(target=worker, name="build-memory-sampler", daemon=True)
    try:
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            env=None if environment is None else dict(environment),
            stdout=stream,
            stderr=subprocess.STDOUT,
            text=True,
        )
        sample()
        thread.start()
        returncode = process.wait()
    finally:
        stop.set()
        if thread.ident is not None:
            thread.join(timeout=max(1.0, interval_s * 10))
        sample()
        if opened is not None:
            opened.close()

    elapsed_ns = time.perf_counter_ns() - started_ns
    status = "ok" if returncode == 0 else "failed"
    return {
        "schema": BUILD_SCHEMA,
        "status": status,
        "clock": "perf_counter_ns",
        "started_at_utc": started_utc,
        "elapsed_ns": elapsed_ns,
        "command": argv,
        "cwd": str(cwd.resolve()),
        "returncode": returncode,
        "memory": {
            "scope": "builder-process-tree",
            "unit": "bytes",
            "sampling_interval_ms": interval_s * 1000,
            "sample_count": samples,
            "sample_errors": errors,
            "peak_rss_bytes": peak if samples else None,
        },
        "log": None if log_path is None else str(log_path.resolve()),
    }
