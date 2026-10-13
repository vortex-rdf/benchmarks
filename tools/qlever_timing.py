"""Split QLever's per-query time into planning, execution and export, from QLever's own runtime information.

Replays a manifest in order against ``qlever/default`` (the same adapter, store and settings as the campaigns), asking
for ``application/qlever-results+json``, which reports per query:
  planning   runtimeInformation.meta.time_query_planning
  execution  runtimeInformation.query_execution_tree.total_time  (computeResult = planning + execution)
  export     time.total - time.computeResult                       (serialization of the result)
Client time (request to full body) is recorded too, but the result format differs from the campaigns' SPARQL JSON,
so it is not a substitute for the campaign numbers.

    python tools/qlever_timing.py <manifest> <store> <out.jsonl> [--timeout-s 10] [--quarantine 3]
"""
from __future__ import annotations

import argparse
import http.client
import json
import time
import urllib.parse
from pathlib import Path

from benchmark_core.http_runner.campaign import drop_page_cache
from benchmark_core.systems.registry import get_system


def ms(value) -> float | None:
    if value is None:
        return None
    return float(str(value).removesuffix("ms"))


def split(body: dict) -> dict:
    info = body.get("runtimeInformation") or {}
    tree = info.get("query_execution_tree") or {}
    total, compute = ms(body["time"]["total"]), ms(body["time"]["computeResult"])
    return {"total_ms": total, "compute_ms": compute, "planning_ms": ms((info.get("meta") or {}).get("time_query_planning")),
            "execution_ms": ms(tree.get("total_time")), "export_ms": total - compute,
            "cache_status": tree.get("cache_status"), "rows": body.get("resultSizeTotal")}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("store", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--timeout-s", type=float, default=10.0)
    parser.add_argument("--quarantine", type=int, default=3, help="timeouts per template before skipping it; 0 = never")
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError(args.out)
    queries = json.loads(args.manifest.read_text())["queries"]
    system = get_system("qlever/default")
    cache = drop_page_cache()
    handle = system.start(source=None, store=args.store)
    host = urllib.parse.urlsplit(system.endpoint)
    timeouts: dict[str, int] = {}
    try:
        connection = http.client.HTTPConnection(host.hostname, host.port, timeout=args.timeout_s + 5)
        with args.out.open("w") as out:
            out.write(json.dumps({"header": True, "manifest": str(args.manifest), "store": str(args.store),
                                  "timeout_s": args.timeout_s, "quarantine": args.quarantine, "page_cache": cache,
                                  "start_to_ready_s": handle.start_to_ready_s, "image": system.image}) + "\n")
            for position, query in enumerate(queries):
                template = query.get("bsbm_template_id") or query.get("template_id")     # as the runner's quarantine
                row = {"position": position, "query_id": query["query_id"], "template": template,
                       "phase": query.get("stream_phase")}
                if args.quarantine and timeouts.get(template, 0) >= args.quarantine:
                    out.write(json.dumps(row | {"status": "skipped"}) + "\n")
                    continue
                payload = urllib.parse.urlencode({"query": query["query"], "timeout": f"{args.timeout_s:g}s"})
                started = time.perf_counter_ns()
                try:
                    connection.request("POST", host.path or "/", payload, {
                        "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/qlever-results+json"})
                    response = connection.getresponse()
                    raw = response.read()
                    row["client_ms"] = (time.perf_counter_ns() - started) / 1e6
                    body = json.loads(raw)
                    if response.status == 200 and body.get("status") == "OK":
                        row |= {"status": "ok"} | split(body)
                    else:
                        timed_out = "timeout" in str(body.get("exception", "")).lower() or "time limit" in str(body).lower()
                        row |= {"status": "timeout" if timed_out else "error", "http_status": response.status,
                                "message": str(body.get("exception", ""))[:300]}
                except (TimeoutError, OSError, http.client.HTTPException, json.JSONDecodeError) as error:
                    row |= {"status": "timeout" if isinstance(error, TimeoutError) else "error", "message": repr(error)[:300],
                            "client_ms": (time.perf_counter_ns() - started) / 1e6}
                    connection.close()
                    connection = http.client.HTTPConnection(host.hostname, host.port, timeout=args.timeout_s + 5)
                if row["status"] == "timeout":
                    timeouts[template] = timeouts.get(template, 0) + 1
                out.write(json.dumps(row) + "\n")
    finally:
        system.stop()


if __name__ == "__main__":
    main()
