"""In-process (library-mode) worker: the engine runs in this process, inside the system's container.

The runner starts it with ``docker exec -i <container> python -m benchmark_core.http_runner.inproc '<config>'``
(``/bench`` on ``PYTHONPATH``) and opens the store with the endpoint image's own ``/app/serve_rdflib.py``, so
store and engine are configured exactly as behind HTTP. The worker imports the engine, opens the store once
(both timed, reported in the ready message), then answers jsonl-v2 queries: ``execute`` evaluates the query and
consumes the complete result (timed), ``finish`` normalizes it (untimed).

``docker exec`` cannot kill a process inside the container, so a watchdog ends this worker at ``deadline_s``
(set just past the runner's timeout); the runner then starts a new worker, which reopens the store.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time

from benchmark_core.http_runner.protocol import serve, stage_clock

GRAPH_RESULTS = {"CONSTRUCT", "DESCRIBE"}


def consume(result) -> list:
    """Materialize the complete result: what an application gets after iterating it to the end."""
    kind = str(result.type).upper()
    if kind in GRAPH_RESULTS:
        return list(result.graph)
    if kind == "ASK":
        return [bool(result.askAnswer)]
    return list(result)


def count(result, rows: list) -> int:
    return int(rows[0]) if str(result.type).upper() == "ASK" else len(rows)


def main() -> None:
    config = json.loads(sys.argv[1])
    if config.get("no_pushdown"):
        os.environ["VORTEX_RDF_DISABLE_PUSHDOWN"] = "1"     # read when the store registers its hook
    sys.path.insert(0, config.get("server_dir", "/app"))
    import serve_rdflib

    started = time.monotonic()
    serve_rdflib.import_engine(config["engine"])
    import_s = time.monotonic() - started
    started = time.monotonic()
    graph = serve_rdflib.build_graph(config["engine"], config["store"], config.get("layout", "cottas-native-ids"),
                                     config.get("in_memory", False))
    open_s = time.monotonic() - started
    ready = {"worker": "inproc", "engine": config["engine"], "import_s": round(import_s, 4), "open_s": round(open_s, 4)}
    if config["engine"] == "vortex":
        from rdflib.plugins.sparql import CUSTOM_EVALS
        from vortex_rdflib import pushdown
        ready["sparql_pushdown"] = pushdown._EVAL_KEY in CUSTOM_EVALS
        if ready["sparql_pushdown"] == bool(config.get("no_pushdown")):
            raise SystemExit(f"vortex_rdflib pushdown installed={ready['sparql_pushdown']}, "
                             f"requested={not config.get('no_pushdown')}")
    from benchmark_core.http_runner.normalize import normalize_materialized_result
    deadline_s = config.get("deadline_s")

    def execute(request):
        watchdog = threading.Timer(deadline_s, os._exit, (124,)) if deadline_s else None
        if watchdog is not None:
            watchdog.daemon = True
            watchdog.start()
        try:
            started_ns = stage_clock()
            result = graph.query(request["query"])
            rows = consume(result)
            consumed_ns = stage_clock()
        finally:
            if watchdog is not None:
                watchdog.cancel()
        return (result, rows), {"engine_execute_and_consume": consumed_ns - started_ns}

    def finish(request, state):
        result, rows = state
        if request["mode"] == "count":
            return {"result_count": count(result, rows), "metadata": {}}
        normalized = normalize_materialized_result(result, rows, request["query"])
        normalized.pop("normalized_result", None)
        normalized["result_count"] = count(result, rows)
        return {"normalized": normalized, "metadata": {}}

    # rdflib-hdt prints one line per triple pattern and join; the HTTP endpoint sends that to /dev/null too.
    serve(ready, execute, finish, discard_stdout=config["engine"] == "hdt")


if __name__ == "__main__":
    main()
