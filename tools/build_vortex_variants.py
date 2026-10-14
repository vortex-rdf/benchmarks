#!/usr/bin/env python3
"""Build extra Vortex-RDF layout/index variants of one N-Triples source, with receipts.

    python tools/build_vortex_variants.py --source BSBM/data/explore-10k/dataset.nt \
        --benchmark bsbm --dataset explore-10k --triple-count 3421251 \
        [--variants default-no-index default-secondary-by-reference ...] [--out-subdir vortex-rdf-0.12.1]

Variants are ``<layout>-<index>`` with layout in {dictionary, default} and index in {no-index,
secondary-by-reference, secondary-by-copy}. Each writes ``dataset-<variant>.vortex`` and
``vortex-rdf-<variant>-receipt.json`` next to the source (representation ``vortex-rdf/<variant>``) and
is added to ``dataset-inventory.json``. ``--out-subdir`` writes them into a subdirectory of the source's directory
instead (for stores of another vortex-rdf store format; the inventory is then left alone). Existing outputs are
never overwritten. The builder runs in its
own cgroup scope (``benchmark_core.build_metrics``), as the other representation builds do.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # repository root: benchmark_core, the BSBM builder
from benchmark_core.build_metrics import run_build_command
from run_bsbm_10k_representation_builds_v1 import (RECEIPT_SCHEMA, VORTEX_CLI, VORTEX_RDF, atomic_json,
                                                    file_record, git_info, sha256, utc_now)

LAYOUTS = ("dictionary", "default")
INDEXES = ("no-index", "secondary-by-reference", "secondary-by-copy")
NEW_VARIANTS = ["default-no-index", "default-secondary-by-reference", "default-secondary-by-copy",
                "dictionary-no-index"]


def split(variant: str) -> tuple[str, str]:
    layout, _, index = variant.partition("-")
    if layout not in LAYOUTS or index not in INDEXES:
        raise ValueError(f"unknown variant {variant!r}")
    return layout, index


def build(source: Path, benchmark: str, dataset: str, triple_count: int, variant: str, out_subdir: str = "") -> dict:
    layout, index = split(variant)
    out_dir = source.parent / out_subdir
    out_dir.mkdir(exist_ok=True)
    output = out_dir / f"dataset-{variant}.vortex"
    receipt = out_dir / f"vortex-rdf-{variant}-receipt.json"
    if output.exists() or receipt.exists():
        return {"variant": variant, "status": "exists", "output": str(output)}
    command = [str(VORTEX_CLI), "serialize", "-i", str(source), "-o", str(output), "--layout", layout]
    if index != "no-index":
        command += ["--indexes", index]
    logs = out_dir / "build-logs"
    logs.mkdir(exist_ok=True)
    metrics = run_build_command(command, cwd=VORTEX_RDF, log_path=logs / f"vortex-{variant}.log",
                                environment={**os.environ, "RUST_LOG": "vortex_rdf_cli=info"})
    if metrics["status"] != "ok" or not output.is_file():
        output.unlink(missing_ok=True)
        raise RuntimeError(f"{variant}: build failed (exit {metrics.get('returncode')})")
    atomic_json(receipt, {
        "schema": RECEIPT_SCHEMA, "benchmark": benchmark, "dataset": dataset, "created_at_utc": utc_now(),
        "source": {"format": "ntriples", "size_bytes": source.stat().st_size, "sha256": sha256(source)},
        "representation": f"vortex-rdf/{variant}",
        "files": [file_record(output, out_dir)],
        "producer": {"kind": "vortex-rdf-cli", "tool": "vortex-rdf-cli", "repository": git_info(VORTEX_RDF),
                     "binary_sha256": sha256(VORTEX_CLI),
                     "command": ["vortex-rdf-cli", *command[1:2], "-i", source.name, "-o", output.name, *command[6:]],
                     "layout": layout, "index": None if index == "no-index" else index,
                     "source_triple_count": triple_count, "build_metrics": metrics},
    })
    inventory = out_dir / "dataset-inventory.json"
    if not out_subdir and inventory.is_file():
        value = json.loads(inventory.read_text())
        entries = [e for e in value["representations"] if e["representation"] != f"vortex-rdf/{variant}"]
        value["representations"] = entries + [{"representation": f"vortex-rdf/{variant}", "receipt": receipt.name}]
        atomic_json(inventory, value)
    return {"variant": variant, "status": "built", "bytes": output.stat().st_size,
            "seconds": round(metrics["elapsed_ns"] / 1e9, 1), "free_gib": round(shutil.disk_usage(out_dir).free / 2**30, 1)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--benchmark", required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--triple-count", type=int, required=True)
    parser.add_argument("--variants", nargs="+", default=NEW_VARIANTS)
    parser.add_argument("--out-subdir", default="")
    args = parser.parse_args()
    for variant in args.variants:
        print(json.dumps(build(args.source.resolve(), args.benchmark, args.dataset, args.triple_count, variant,
                               args.out_subdir)),
              flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
