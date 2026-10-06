#!/usr/bin/env python3
"""Write a bsbm-generation-receipt-v1 for a freshly generated dataset and query stream."""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from benchmark_core.hashing import sha256_file  # noqa: E402

def stream_info(path: Path) -> dict:
    """Record count and per-template counts; a row's ``id`` column is its BSBM template id."""
    counts: Counter = Counter()
    records = 0
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            records += 1
            counts[row["id"].strip()] += 1
    return {"records": records, "template_counts": dict(sorted(counts.items(), key=lambda kv: int(kv[0])))}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--products", type=int, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--stream", type=Path, required=True)
    parser.add_argument("--generator-commit", required=True)
    parser.add_argument("--generator-repo", required=True)
    parser.add_argument("--dataset-seconds", type=int)
    parser.add_argument("--time-zone", required=True)
    parser.add_argument("--jre-image", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    triples = sum(1 for _ in args.dataset.open("rb"))
    info = stream_info(args.stream)
    receipt = {
        "schema": "bsbm-generation-receipt-v1",
        "benchmark": "BSBM",
        "use_case": "Explore",
        "specification": "3.1",
        "product_count": args.products,
        "forward_chaining": True,
        "created_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "dataset": {
            "format": "ntriples", "path": "dataset.nt", "sha256": sha256_file(args.dataset),
            "size_bytes": args.dataset.stat().st_size, "triple_count": triples,
        },
        "query_stream": {
            "format": "bsbm-log-csv", "columns": ["id", "kind", "content"], "path": "explore.csv",
            "sha256": sha256_file(args.stream), "size_bytes": args.stream.stat().st_size,
            "record_count": info["records"], "warmup_records": 1250,
            "measured_records": info["records"] - 1250, "template_counts": info["template_counts"],
        },
        "generator": {
            "repository": args.generator_repo, "commit": args.generator_commit, "branch": "bench-data",
            "dataset_command": f"./generate -fc -pc {args.products} -s nt -fn dataset -ud -ufn dataset-update",
            "query_command": "./testdriver -ucf usecases/explore/sparql.txt <endpoint>/query -w 50 -runs 500",
            "seed": 808080, "seed_source": "generator default (no -seed argument)",
            "warmup_mix_runs": 50, "measured_mix_runs": 500,
            "time_zone": args.time_zone, "jre_image": args.jre_image,
            "dataset_generation_elapsed_ns": None if args.dataset_seconds is None else args.dataset_seconds * 10**9,
        },
    }
    args.output.write_text(json.dumps(receipt, indent=1, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
