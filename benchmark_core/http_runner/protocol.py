"""The jsonl-v2 worker protocol, without third-party imports (it also runs inside system containers)."""
from __future__ import annotations

import json
import os
import sys
import time
import traceback

PROTOCOL = "jsonl-v2"

# Systems whose SPARQL endpoint takes the query as the raw POST body (Content-Type: application/sparql-query).
RAW_QUERY_SYSTEMS = frozenset({"millenniumdb/default"})


class _Protocol:
    """Own the original stdout; route everything else printed to stderr."""

    def __init__(self):
        self._stream = os.fdopen(os.dup(sys.stdout.fileno()), "w", buffering=1)
        sys.stdout.flush()
        os.dup2(sys.stderr.fileno(), sys.stdout.fileno())

    def emit(self, value) -> None:
        self._stream.write(json.dumps(value, separators=(",", ":")) + "\n")
        self._stream.flush()


def serve(ready: dict, execute, finish, *, discard_stdout: bool = False) -> None:
    """Serve requests until shutdown.

    ``execute(request)`` runs the query, consumes the complete result, and
    returns ``(state, worker_stages_ns)``. ``finish(request, state)`` returns
    the ``result`` payload fields. Only ``execute`` is inside the timer.
    """
    protocol = _Protocol()
    if discard_stdout:      # engines that print per pattern (rdflib-hdt): keep that out of the measured work
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
    protocol.emit({"kind": "ready", "protocol": PROTOCOL, **ready})
    for line in sys.stdin:
        request = json.loads(line)
        if request.get("kind") == "shutdown":
            protocol.emit({"kind": "stopped"})
            return
        request_id = request.get("request_id")
        try:
            state, stages = execute(request)
        except BaseException as error:
            protocol.emit({"kind": "done", "request_id": request_id,
                           "status": "error", "error_type": type(error).__name__,
                           "error_message": str(error)[:4000]})
            traceback.print_exc(file=sys.stderr)
            continue
        protocol.emit({"kind": "done", "request_id": request_id,
                       "status": "ok", "worker_stages_ns": stages})
        try:
            payload = finish(request, state)
            protocol.emit({"kind": "result", "request_id": request_id,
                           "status": "ok", **payload})
        except BaseException as error:
            protocol.emit({"kind": "result", "request_id": request_id,
                           "status": "error", "error_type": type(error).__name__,
                           "error_message": str(error)[:4000]})
            traceback.print_exc(file=sys.stderr)


def stage_clock():
    return time.perf_counter_ns()
