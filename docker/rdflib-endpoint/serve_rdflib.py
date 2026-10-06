#!/usr/bin/env python3
"""SPARQL HTTP endpoint over one rdflib store (rdflib-endpoint), for the benchmark.

    serve_rdflib.py --engine vortex|rdflib|cottas|hdt --store /data/<file> [--in-memory] [--no-pushdown]

Endpoint: POST/GET ``/sparql`` (SPARQL protocol); readiness and identity: GET ``/ready``.
The store is opened exactly as in the embedded workers; one single-threaded worker process
answers requests one at a time, like the in-process baseline.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
import threading
import time


class QueryDeadline(BaseException):
    """Raised inside the query thread when the server-side deadline passes.

    A BaseException so that rdflib-endpoint's ``except Exception`` handlers do not turn it into an HTTP 400.
    """


class DeadlineMiddleware:
    """Cancel a query that runs past ``QUERY_DEADLINE_S`` (answer 504) instead of letting it run on.

    rdflib-endpoint evaluates queries inline in the event-loop thread, so a query nobody waits for any
    more would block the server (and keep growing memory). The watchdog raises ``QueryDeadline`` in that
    thread; evaluation stops at the next Python bytecode. A long call inside a native extension finishes
    first. The deadline is set slightly above the client timeout, so the client always times out first.
    """

    def __init__(self, app, deadline_s: float, on_cancel=None):
        self.app, self.deadline_s, self.on_cancel = app, deadline_s, on_cancel
        self.lock = threading.Lock()
        self.cancelled = 0

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") != "/sparql" or self.deadline_s <= 0:
            return await self.app(scope, receive, send)
        thread_id = threading.get_ident()
        state = {"active": True}

        def fire():
            with self.lock:
                if state["active"]:
                    ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(thread_id), ctypes.py_object(QueryDeadline))
                    if self.on_cancel is not None:
                        self.on_cancel()    # interrupt native work so that the thread reaches Python again

        timer = threading.Timer(self.deadline_s, fire)
        timer.start()
        started = False

        async def tracked_send(message):
            nonlocal started
            started = started or message["type"] == "http.response.start"
            await send(message)

        try:
            try:
                await self.app(scope, receive, tracked_send)
            except QueryDeadline:
                self.cancelled += 1
                if not started:
                    body = b"query exceeded the server-side deadline"
                    await send({"type": "http.response.start", "status": 504,
                                "headers": [(b"content-type", b"text/plain"), (b"content-length", str(len(body)).encode())]})
                    await send({"type": "http.response.body", "body": body})
        finally:
            while True:     # never leave a pending deadline behind for the next request
                try:
                    timer.cancel()
                    with self.lock:
                        state["active"] = False
                        ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(thread_id), None)
                    break
                except QueryDeadline:
                    continue


def build_graph(engine: str, store: str, layout: str, in_memory: bool):
    from rdflib import Graph
    if engine == "rdflib":
        graph = Graph()
        graph.parse(store, format="nt")
        return graph
    if engine == "vortex":
        from vortex_rdflib import VortexRdflibStore
        return Graph(store=VortexRdflibStore(path=store, in_memory=in_memory))
    if engine == "cottas":
        from pycottas.cottas_store import COTTASStore
        return Graph(store=COTTASStore(store))
    if engine == "hdt":
        from rdflib_hdt import HDTStore, optimize_sparql
        optimize_sparql()
        return Graph(store=HDTStore(store, mapped=False, indexed=True, safe_mode=True))
    raise SystemExit(f"unsupported engine: {engine}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", required=True, choices=["vortex", "rdflib", "cottas", "hdt"])
    parser.add_argument("--store", required=True)
    parser.add_argument("--layout", default="cottas-native-ids")
    parser.add_argument("--in-memory", action="store_true")
    parser.add_argument("--no-pushdown", action="store_true")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if args.engine == "vortex" and args.no_pushdown:
        os.environ["VORTEX_RDF_DISABLE_PUSHDOWN"] = "1"   # read when the store registers its hook

    started = time.monotonic()
    graph = build_graph(args.engine, args.store, args.layout, args.in_memory)
    opened_s = time.monotonic() - started

    identity = {"worker": "rdflib-endpoint", "engine": args.engine, "store": os.path.basename(args.store),
                "in_memory": bool(args.in_memory), "open_s": round(opened_s, 3)}
    if args.engine == "vortex":
        from rdflib.plugins.sparql import CUSTOM_EVALS
        from vortex_rdflib import pushdown
        installed = pushdown._EVAL_KEY in CUSTOM_EVALS
        if installed != (not args.no_pushdown):
            raise SystemExit(f"vortex_rdflib pushdown hook installed={installed}, requested={not args.no_pushdown}")
        identity["sparql_pushdown"] = installed
        import importlib.metadata as md
        identity["vortex_rdflib"] = md.version("vortex-rdflib")
        identity["vortex_rdf"] = md.version("vortex-rdf")

    if args.engine == "hdt":
        # rdflib-hdt prints one diagnostic line per triple pattern; discard it so logging does not
        # become part of the measured work (the embedded worker sent it to a drained pipe).
        sys.stdout.flush()
        os.dup2(os.open(os.devnull, os.O_WRONLY), 1)

    from fastapi import FastAPI
    import rdflib_endpoint.sparql_router as sparql_router
    from rdflib_endpoint import SparqlRouter

    # rdflib-endpoint answers DESCRIBE with a SPARQL-results content type; a DESCRIBE result is a
    # graph, so serialize it as N-Triples, which is what the benchmark client requests.
    _default_content_type = sparql_router.get_default_content_type
    sparql_router.get_default_content_type = (
        lambda operation: "application/n-triples" if operation == "Describe Query" else _default_content_type(operation))

    class NoParseCacheRouter(SparqlRouter):
        """Parse every query, as the embedded baseline does (no per-endpoint parse cache)."""

        def _prepare_query_cached(self, query, graph_ns):
            from rdflib.plugins.sparql import prepareQuery
            return prepareQuery(query, initNs=graph_ns)

    app = FastAPI(title="vortex-rdf-bench rdflib endpoint")
    app.include_router(NoParseCacheRouter(graph=graph, path="/sparql", title=f"{args.engine} endpoint",
                                          enable_update=False))

    deadline_s = float(os.environ.get("QUERY_DEADLINE_S", "0") or 0)
    identity["server_query_deadline_s"] = deadline_s
    on_cancel = None
    if args.engine == "cottas":     # pycottas runs every triple pattern as a DuckDB query on the default connection
        import duckdb
        on_cancel = duckdb.interrupt
    middleware = DeadlineMiddleware(app, deadline_s, on_cancel)

    @app.get("/ready")
    def ready():
        return {**identity, "queries_cancelled": middleware.cancelled}

    import uvicorn
    # A single worker answers one request at a time; keep-alive must outlive idle periods.
    uvicorn.run(middleware, host="0.0.0.0", port=args.port, workers=1, log_level="warning", access_log=False,
                timeout_keep_alive=3600)


if __name__ == "__main__":
    sys.exit(main())
