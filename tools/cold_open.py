#!/usr/bin/env python3
"""Cold-open measurement for the file-backed engines (Vortex-RDF, COTTAS, HDT-RDFLib, RDFLib): what a consumer
pays to open the artifact and answer a first query, without container or HTTP start-up.

For every system and repetition: drop the page cache, start the system's container idle, start an in-process
worker in it (``benchmark_core.http_runner.inproc``) and record the worker's own ``import_s`` (engine modules)
and ``open_s`` (store constructor), plus the first query's latency, measured like any other attempt. One JSON
line per repetition goes to --output.

  python tools/cold_open.py --declaration BSBM/experiments/explore-100k-full.json --benchmark-root BSBM \
      --manifest BSBM/data/explore-100k/full-manifest.json --reps 5 --output BSBM/data/runs/cold-open-100k.jsonl \
      --system vortex-rdf/dictionary-secondary-by-copy --system pycottas/default
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmark_core.experiment import load_experiment_declaration  # noqa: E402
from benchmark_core.http_runner.campaign import _representation_files, drop_page_cache  # noqa: E402
from benchmark_core.http_runner.worker import HttpQueryWorker  # noqa: E402
from benchmark_core.manifest import load_manifest  # noqa: E402
from benchmark_core.systems.registry import get_system  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--declaration", required=True)
    parser.add_argument("--benchmark-root", required=True)
    parser.add_argument("--manifest", required=True, help="the first measured query is the first query timed")
    parser.add_argument("--system", action="append", required=True)
    parser.add_argument("--reps", type=int, default=5)
    parser.add_argument("--timeout-s", type=float, default=60.0, help="limit for the first query")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    root = Path(args.benchmark_root).resolve()
    declared = load_experiment_declaration(Path(args.declaration))
    bindings = {item["system"]: item["representation"] for item in declared["bindings"]}
    first = next(q for q in load_manifest(Path(args.manifest))["queries"] if q.get("stream_phase", "measured") == "measured")
    with Path(args.output).open("a", encoding="utf-8") as out:
        for system_id in args.system:
            _, files = _representation_files(root, declared["representations"][bindings[system_id]])
            artifact = next((path for path in files if not path.name.endswith(".index.v1-1")), files[0])
            for rep in range(args.reps):
                system = get_system(system_id)
                system.in_process = True
                cache = drop_page_cache()
                started = time.monotonic()
                handle = system.start(source=None, store=artifact)
                worker = HttpQueryWorker(endpoint=handle.endpoint, container=handle.container, system=system_id,
                                         timeout_s=args.timeout_s, startup_timeout_s=system.ready_timeout_s,
                                         command=system.worker_command(args.timeout_s))
                try:
                    worker_started = time.monotonic()
                    worker.open()
                    worker_ready_s = time.monotonic() - worker_started
                    outcome = worker.execute(first["query"])
                    ready = worker.ready_messages[0]
                    peak = worker.lifetime_peak_bytes()
                    record = {"system": system_id, "rep": rep, "dataset": declared["dataset"],
                              "artifact": artifact.name, "page_cache": cache["status"],
                              "container_start_s": round(handle.start_to_ready_s, 4),
                              "worker_ready_s": round(worker_ready_s, 4), "import_s": ready["import_s"],
                              "open_s": ready["open_s"], "first_query_id": first["query_id"],
                              "first_query_s": round(outcome.elapsed_ns / 1e9, 4),
                              "first_query_result_count": outcome.result_count,
                              "open_plus_first_query_s": round(ready["open_s"] + outcome.elapsed_ns / 1e9, 4),
                              "container_peak_bytes": peak, "total_s": round(time.monotonic() - started, 4)}
                except Exception as error:  # noqa: BLE001 - record and continue with the next repetition
                    record = {"system": system_id, "rep": rep, "error": f"{type(error).__name__}: {error}"[:500]}
                finally:
                    worker.close()
                    system.stop()
                out.write(json.dumps(record, sort_keys=True) + "\n")
                out.flush()
                print(json.dumps(record, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
