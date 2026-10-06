#!/usr/bin/env python3
"""SPARQL HTTP endpoint over one rdflib store (rdflib-endpoint), for the benchmark.

    serve_rdflib.py --engine vortex|rdflib|cottas|hdt --store /data/<file> [--in-memory] [--no-pushdown]

Endpoint: POST/GET ``/sparql`` (SPARQL protocol); readiness and identity: GET ``/ready``.
The store is opened exactly as in the embedded workers; one single-threaded worker process
answers requests one at a time, like the in-process baseline.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time


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

    @app.get("/ready")
    def ready():
        return identity

    import uvicorn
    # A single worker answers one request at a time; keep-alive must outlive idle periods.
    uvicorn.run(app, host="0.0.0.0", port=args.port, workers=1, log_level="warning", access_log=False,
                timeout_keep_alive=3600)


if __name__ == "__main__":
    sys.exit(main())
