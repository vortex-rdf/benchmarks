"""Measure representation-build commands and declared persistent paths."""
from __future__ import annotations

import os
import subprocess
import tempfile
import threading
import time
import uuid
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


_CGROUP_WRAPPER = (
    'cg=/sys/fs/cgroup$(cut -d: -f3 /proc/self/cgroup); echo "$cg" > "$0"; '
    '"$@"; rc=$?; '
    '{ echo "peak $(cat "$cg/memory.peak")"; grep -E "^(anon|file) " "$cg/memory.stat"; } > "$0.final"; '
    'exit $rc'
)


def _read_cgroup_sample(path: Path) -> dict[str, int] | None:
    try:
        current = int((path / "memory.current").read_text())
        stat = (path / "memory.stat").read_text()
    except (FileNotFoundError, ValueError):
        return None
    sample = {"current": current}
    for line in stat.splitlines():
        key, _, value = line.partition(" ")
        if key in {"anon", "file"}:
            sample[key] = int(value)
    return sample


def run_build_command(
    command: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str] | None = None,
    log_path: Path | None = None,
    interval_s: float = 0.01,
    cgroup: bool | None = None,
) -> dict[str, Any]:
    """Run one builder and measure wall time and memory.

    The builder runs in its own transient systemd user scope, so its memory
    is read from cgroup v2 like every query engine: ``memory.current`` and
    its anonymous and file-backed parts every ``interval_s``, plus the
    scope's lifetime ``memory.peak``. No memory limit is applied. Concurrent
    process-tree RSS is still sampled for continuity with earlier receipts.
    Set KROWN_BUILD_CGROUP=0 (or ``cgroup=False``) to run without a scope.
    """
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
    if cgroup is None:
        cgroup = os.environ.get("KROWN_BUILD_CGROUP", "1") != "0"

    stream = subprocess.DEVNULL
    opened = None
    if log_path is not None:
        if not isinstance(log_path, Path):
            raise TypeError("log_path must be a Path or None")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        opened = log_path.open("w", encoding="utf-8")
        stream = opened

    workspace = tempfile.TemporaryDirectory(prefix="krown-build-cgroup-")
    marker = Path(workspace.name) / "cgroup"
    launched = argv
    unit = None
    if cgroup:
        unit = f"krown-build-{uuid.uuid4().hex[:12]}"
        launched = ["systemd-run", "--user", "--scope", "--quiet", f"--unit={unit}",
                    "-p", "MemoryAccounting=yes", "--",
                    "/bin/sh", "-c", _CGROUP_WRAPPER, str(marker), *argv]

    started_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    started_ns = time.perf_counter_ns()
    process = None
    peak = samples = errors = 0
    cgroup_path: Path | None = None
    cgroup_peaks = {"current": 0, "anon": 0, "file": 0}
    cgroup_samples = 0
    stop = threading.Event()

    def sample() -> None:
        nonlocal peak, samples, errors, cgroup_path, cgroup_samples
        if process is None:
            return
        try:
            value = _process_tree_rss_bytes(process.pid)
            if value is not None:
                peak = max(peak, value)
                samples += 1
            if cgroup:
                if cgroup_path is None and marker.is_file():
                    text = marker.read_text().strip()
                    cgroup_path = Path(text) if text else None
                current = None if cgroup_path is None else _read_cgroup_sample(cgroup_path)
                if current is not None:
                    cgroup_samples += 1
                    for key, item in current.items():
                        cgroup_peaks[key] = max(cgroup_peaks[key], item)
        except (OSError, RuntimeError, TypeError, ValueError):
            errors += 1

    def worker() -> None:
        while not stop.wait(interval_s):
            sample()

    thread = threading.Thread(target=worker, name="build-memory-sampler", daemon=True)
    try:
        process = subprocess.Popen(
            launched,
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
        if opened is not None:
            opened.close()

    elapsed_ns = time.perf_counter_ns() - started_ns
    final = {}
    final_path = Path(str(marker) + ".final")
    if final_path.is_file():
        for line in final_path.read_text().splitlines():
            key, _, value = line.partition(" ")
            if value.strip().isdigit():
                final[key] = int(value)
    workspace.cleanup()
    status = "ok" if returncode == 0 else "failed"
    memory = {
        "scope": "builder-cgroup-v2" if cgroup else "builder-process-tree",
        "unit": "bytes",
        "sampling_interval_ms": interval_s * 1000,
        "sample_count": samples,
        "sample_errors": errors,
        "peak_process_tree_rss_bytes": peak if samples else None,
    }
    if cgroup:
        memory.update({
            "systemd_unit": unit,
            "cgroup_sample_count": cgroup_samples,
            "peak_cgroup_current_bytes": cgroup_peaks["current"] if cgroup_samples else None,
            "peak_anon_bytes": cgroup_peaks["anon"] if cgroup_samples else None,
            "peak_file_bytes": cgroup_peaks["file"] if cgroup_samples else None,
            "cgroup_lifetime_peak_bytes": final.get("peak"),
            "final_anon_bytes": final.get("anon"),
            "final_file_bytes": final.get("file"),
        })
        memory["peak_rss_bytes"] = memory["peak_cgroup_current_bytes"]
    else:
        memory["peak_rss_bytes"] = memory["peak_process_tree_rss_bytes"]
    return {
        "schema": BUILD_SCHEMA,
        "status": status,
        "clock": "perf_counter_ns",
        "started_at_utc": started_utc,
        "elapsed_ns": elapsed_ns,
        "command": argv,
        "cwd": str(cwd.resolve()),
        "returncode": returncode,
        "memory": memory,
        "log": None if log_path is None else str(log_path.resolve()),
    }
