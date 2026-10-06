#!/usr/bin/env python3
"""Runner-side handle on one persistent SPARQL HTTP client worker (protocol ``jsonl-v2``).

Every system is measured with this one timer boundary:

1. The runner classifies the query and builds the request (untimed).
2. The runner stamps ``perf_counter_ns`` and writes the request line to the client worker.
3. The worker POSTs the query over a keep-alive connection, reads the complete response body
   and writes ``done``. The runner stops its timer when it reads ``done``.
4. The worker then writes ``result`` with the count and, in fingerprint mode, the normalized
   result. This transfer and all correctness work are outside the timer.

A timeout kills the client worker; the next attempt starts a new one (and a new connection)
before its timer starts. The server's memory is read from its container's cgroup v2.
"""
from __future__ import annotations

import collections
import dataclasses
import functools
import hashlib
import json
import os
import select
import subprocess
import sys
import threading
import time
from typing import Any

from benchmark_core.http_runner.cgroup import ContainerCgroupMemory
from benchmark_core.http_runner.query_features import classify_query

PROTOCOL = "jsonl-v2"
MEASUREMENT_BOUNDARY = "harness-request-to-complete-result-v2"


class QueryTimeoutError(TimeoutError):
    """The query did not complete within the per-query limit."""


@dataclasses.dataclass(frozen=True)
class QueryOutcome:
    result_count: int
    result_fingerprint: str | None
    elapsed_ns: int
    metadata: dict[str, Any]
    stage_timings_ns: dict[str, int]


@functools.lru_cache(maxsize=65536)
def _result_type(query: str) -> str:
    """Classify each distinct query once; classification is never timed."""
    return classify_query(query).result_type


def worker_mode(correctness_mode: str) -> str:
    return "count" if correctness_mode in {"count-only", "none"} else "fingerprint"


class HttpQueryWorker:
    """Exchange complete query results with one persistent HTTP client process."""

    def __init__(self, *, endpoint: str, container: str | None, system: str,
                 timeout_s: float, startup_timeout_s: float = 120.0,
                 correctness_mode: str = "fingerprint", result_timeout_s: float | None = None,
                 direct: bool = True, tcp_quickack: bool = True,
                 request_max_rows: int | None = None, python: str | None = None):
        if timeout_s <= 0 or startup_timeout_s <= 0:
            raise ValueError("worker timeouts must be positive")
        self._config = {"endpoint": endpoint, "container": container, "system": system,
                        "direct": direct, "tcp_quickack": tcp_quickack,
                        "request_max_rows": request_max_rows}
        self._endpoint = endpoint
        self._container = container
        self._timeout_s = timeout_s
        self._startup_timeout_s = startup_timeout_s
        self._result_timeout_s = (float(os.environ.get("VORTEX_RDF_RESULT_TRANSFER_TIMEOUT_S", "900"))
                                  if result_timeout_s is None else result_timeout_s)
        self._correctness_mode = correctness_mode
        self._mode = worker_mode(correctness_mode)
        self._python = python or sys.executable
        self._process: subprocess.Popen | None = None
        self._request_id = 0
        self._stdout_buffer = bytearray()
        self._stderr_tail: collections.deque = collections.deque(maxlen=200)
        self._stderr_thread: threading.Thread | None = None
        self._memory = ContainerCgroupMemory(container) if container else None
        self.recovery_restarts = 0

    # ---- memory ----------------------------------------------------------------------
    def current_rss_bytes(self):
        """One cgroup v2 sample (current/anon/file/...) of the server container."""
        return None if self._memory is None else self._memory.sample()

    def lifetime_peak_bytes(self) -> int | None:
        return None if self._memory is None else self._memory.lifetime_peak_bytes()

    def progress_metadata(self) -> dict[str, Any]:
        process = self._process
        return {"worker_pid": process.pid if process is not None and process.poll() is None else "none",
                "worker_restarts": self.recovery_restarts}

    # ---- process plumbing ------------------------------------------------------------
    def _drain_stderr(self, process) -> None:
        try:
            for line in process.stderr or ():
                self._stderr_tail.append(line.decode("utf-8", errors="replace").rstrip("\n"))
        except (OSError, ValueError):
            pass

    def _stderr(self) -> str:
        return "\n".join(self._stderr_tail).strip()

    @staticmethod
    def _exit_diagnostic(process) -> str:
        code = None if process is None else process.poll()
        if code is None:
            return "returncode=running"
        return f"returncode={code}" + (f" signal={-code}" if code < 0 else "")

    def _read_message(self, timeout_s: float, phase: str):
        """Return the next JSON line, or None when ``timeout_s`` passes.

        Lines are split from raw reads of the stdout file descriptor: a buffered reader would
        hide a second, already-received line from ``select`` (``done`` and ``result`` arrive
        back to back).
        """
        process = self._process
        if process is None or process.stdout is None:
            raise RuntimeError("persistent worker is not open")
        deadline = time.monotonic() + timeout_s
        descriptor = process.stdout.fileno()
        while True:
            newline = self._stdout_buffer.find(b"\n")
            if newline >= 0:
                break
            remaining = deadline - time.monotonic()
            ready = select.select([descriptor], [], [], remaining)[0] if remaining > 0 else []
            if not ready:
                if process.poll() is not None:
                    detail = self._stderr()
                    raise RuntimeError(f"persistent worker exited during {phase}" + (f": {detail}" if detail else ""))
                return None
            chunk = os.read(descriptor, 1 << 20)
            if chunk == b"":
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    pass
                detail = self._stderr()
                raise RuntimeError(f"persistent worker closed stdout during {phase}; "
                                   f"{self._exit_diagnostic(process)}" + (f"; stderr_tail={detail}" if detail else ""))
            self._stdout_buffer += chunk
        line = bytes(self._stdout_buffer[:newline])
        del self._stdout_buffer[:newline + 1]
        try:
            return json.loads(line)
        except json.JSONDecodeError as error:
            raise RuntimeError(f"persistent worker returned invalid JSON during {phase}: {line[:500]!r}") from error

    def _force_stop(self) -> None:
        process, self._process = self._process, None
        if process is not None and process.poll() is None:
            process.kill()
        if process is not None:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        thread, self._stderr_thread = self._stderr_thread, None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1)

    # ---- lifecycle -------------------------------------------------------------------
    def open(self) -> None:
        if self._process is not None:
            raise RuntimeError("persistent worker is already open")
        self._stdout_buffer = bytearray()
        self._stderr_tail.clear()
        self._process = subprocess.Popen(
            [self._python, "-m", "benchmark_core.http_runner.client", json.dumps(self._config)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0,
        )
        self._stderr_thread = threading.Thread(target=self._drain_stderr, args=(self._process,), daemon=True)
        self._stderr_thread.start()
        try:
            message = self._read_message(self._startup_timeout_s, "startup")
            if message is None:
                raise RuntimeError("persistent worker startup timed out")
            expected = {"kind": "ready", "protocol": PROTOCOL, "worker": "sparql-http", "endpoint": self._endpoint}
            if message != expected:
                raise RuntimeError(f"invalid persistent worker ready response: {message!r}")
        except BaseException:
            self._force_stop()
            raise

    def prepare_for_attempt(self) -> bool:
        """Start a fresh client when the previous one died or was killed by a timeout."""
        process = self._process
        if process is None or process.poll() is not None:
            self._force_stop()
            self.open()
            self.recovery_restarts += 1
            return True
        return False

    def close(self) -> None:
        process = self._process
        if process is None:
            return
        try:
            if process.poll() is None:
                process.stdin.write(b'{"kind":"shutdown"}\n')
                process.wait(timeout=5)
            self._process = None
            thread, self._stderr_thread = self._stderr_thread, None
            if thread is not None:
                thread.join(timeout=1)
        except (BrokenPipeError, OSError, subprocess.TimeoutExpired):
            self._force_stop()

    # ---- one query -------------------------------------------------------------------
    def _fail(self, error: BaseException, request_id: int, query_sha256: str):
        diagnostic = self._exit_diagnostic(self._process)
        detail = self._stderr()
        self._force_stop()
        suffix = (f"; request_id={request_id}; query_sha256={query_sha256}; {diagnostic}"
                  + (f"; stderr_tail={detail}" if detail else ""))
        if isinstance(error, RuntimeError):
            raise RuntimeError(str(error) + suffix) from error
        raise error

    def execute(self, query: str) -> QueryOutcome:
        process = self._process
        if process is None:
            raise RuntimeError("persistent worker is not running")
        if process.poll() is not None:
            detail = self._stderr()
            self._force_stop()
            raise RuntimeError("persistent worker is not running" + (f": {detail}" if detail else ""))
        prepare_started_ns = time.perf_counter_ns()
        result_type = _result_type(query)
        request_id = self._request_id
        self._request_id += 1
        line = (json.dumps({"kind": "query", "request_id": request_id, "query": query,
                            "result_type": result_type, "mode": self._mode},
                           separators=(",", ":")) + "\n").encode("utf-8")
        query_sha256 = hashlib.sha256(query.encode("utf-8")).hexdigest()
        prepare_ns = time.perf_counter_ns() - prepare_started_ns

        # Timed section: request write until the worker reports a consumed result.
        started_ns = time.perf_counter_ns()
        try:
            process.stdin.write(line)
        except (BrokenPipeError, OSError) as error:
            detail = self._stderr()
            self._force_stop()
            raise RuntimeError("persistent worker rejected the query request" + (f": {detail}" if detail else "")) from error
        try:
            done = self._read_message(self._timeout_s, "query")
        except BaseException as error:
            self._fail(error, request_id, query_sha256)
        complete_ns = time.perf_counter_ns() - started_ns
        if done is None:
            self._force_stop()
            raise QueryTimeoutError(f"persistent worker query exceeded {self._timeout_s}s")
        if done.get("kind") != "done" or done.get("request_id") != request_id:
            self._force_stop()
            raise RuntimeError(f"invalid persistent worker response: {done!r}"[:2000])
        if done.get("status") != "ok":
            raise RuntimeError(f"{done.get('error_type', 'WorkerError')}: "
                               f"{done.get('error_message', 'unknown worker error')}")

        # Untimed: result transfer and correctness.
        transfer_started_ns = time.perf_counter_ns()
        try:
            message = self._read_message(self._result_timeout_s, "result")
        except BaseException as error:
            self._fail(error, request_id, query_sha256)
        transfer_ns = time.perf_counter_ns() - transfer_started_ns
        if message is None:
            self._force_stop()
            raise RuntimeError(f"persistent worker result transfer exceeded {self._result_timeout_s}s")
        if message.get("kind") != "result" or message.get("request_id") != request_id:
            self._force_stop()
            raise RuntimeError(f"invalid persistent worker response: {message!r}"[:2000])
        if message.get("status") != "ok":
            raise RuntimeError(f"{message.get('error_type', 'WorkerError')}: "
                               f"{message.get('error_message', 'unknown worker error')}")
        correctness_started_ns = time.perf_counter_ns()
        if "normalized" in message:
            normalized = dict(message["normalized"])
        else:
            normalized = {"result_count": message["result_count"], "result_fingerprint": None}
        correctness_ns = time.perf_counter_ns() - correctness_started_ns
        metadata = {key: value for key, value in normalized.items()
                    if key not in {"result_count", "result_fingerprint", "normalized_result"}}
        metadata.update(message.get("metadata") or {})
        metadata["measurement_boundary"] = MEASUREMENT_BOUNDARY
        metadata["worker_mode"] = self._mode
        if self._mode == "count":
            # Count-only results carry no normalizer metadata; record the workload's mode.
            metadata.setdefault("comparison_mode", self._correctness_mode)
        metadata["worker_stages_ns"] = done.get("worker_stages_ns") or {}
        return QueryOutcome(
            result_count=normalized["result_count"], result_fingerprint=normalized.get("result_fingerprint"),
            elapsed_ns=complete_ns, metadata=metadata,
            stage_timings_ns={"request_preparation": prepare_ns, "request_until_complete_result": complete_ns,
                              "result_transfer": transfer_ns, "correctness": correctness_ns},
        )
