#!/usr/bin/env python3
"""Build BSBM 100k HDT, COTTAS, and two Vortex representations unattended."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from benchmark_core.hashing import sha256_file
from benchmark_core.build_metrics import (
    measure_representation_size,
    run_build_command,
)

SCHEMA = "bsbm-representation-build-ledger-v1"
RECEIPT_SCHEMA = "rdf-representation-receipt-v1"
BENCHMARKS = Path(__file__).resolve().parent
# Checkouts used for the Vortex stage; override with VORTEX_RDF_REPO / VORTEX_RDFLIB_REPO.
VORTEX_RDF = Path(os.environ.get("VORTEX_RDF_REPO", BENCHMARKS.parent / "vortex-rdf")).expanduser().resolve()
VORTEX_RDFLIB = Path(os.environ.get("VORTEX_RDFLIB_REPO", BENCHMARKS.parent / "vortex-rdflib")).expanduser().resolve()
RDF2HDT = BENCHMARKS / "BSBM/data/tools/rdf2hdt-0.2.0/bin/rdf2hdt"
VORTEX_CLI = VORTEX_RDF / "target/release/vortex-rdf-cli"
# Python of the pinned rdflib-hdt 3.3 runtime (see README: BSBM/tools/setup_hdt_runtime.sh).
HDT_INDEX_PYTHON = Path(
    os.environ.get("VORTEX_RDF_BENCH_HDT_PYTHON") or os.environ.get("KROWN_HDT_INDEX_PYTHON")
    or BENCHMARKS / "BSBM/data/tools/rdflib-hdt-3.3/bin/python"
).expanduser().resolve()
REPRESENTATIONS = ("hdt", "cottas", "vortex")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256(path: Path) -> str:
    # Cached by (device, inode, size, mtime): unchanged sources are read once.
    return sha256_file(path)


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def git_info(path: Path) -> dict[str, Any]:
    def call(*args: str) -> str | None:
        result = subprocess.run(
            ["git", "-C", str(path), *args], text=True,
            capture_output=True, check=False,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    return {
        "repository": str(path),
        "commit": call("rev-parse", "HEAD"),
        "dirty": bool(call("status", "--porcelain")),
    }


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def file_record(path: Path, relative_to: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(relative_to).as_posix(),
        "size_bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def source_receipt(source: Path, output_dir: Path, triple_count: int) -> Path:
    receipt = output_dir / "rdf-source-receipt.json"
    identity = file_record(source, output_dir)
    value = {
        "schema": RECEIPT_SCHEMA,
        "benchmark": "bsbm",
        "dataset": "explore-100k",
        "created_at_utc": utc_now(),
        "source": {"format": "ntriples", **{k: identity[k] for k in ("size_bytes", "sha256")}},
        "representation": "rdf/source",
        "files": [identity],
        "producer": {"kind": "official-bsbm", "generation_receipt": "generation-receipt.json",
                     "source_triple_count": triple_count},
    }
    atomic_json(receipt, value)
    return receipt


def update_build_timing(receipt: Path, timing: dict[str, Any]) -> None:
    value = read_json(receipt)
    producer = value.setdefault("producer", {})
    producer["serialization_timing"] = timing
    atomic_json(receipt, value)


def upsert_inventory(output_dir: Path, receipts: list[Path], source: Path) -> Path:
    values = [read_json(path) for path in receipts]
    source_identity = {"format": "ntriples", "size_bytes": source.stat().st_size,
                       "sha256": sha256(source)}
    for value in values:
        if value["source"] != source_identity:
            raise ValueError(f"source identity mismatch in {value['representation']}")
    inventory = {
        "schema": "rdf-dataset-inventory-v1",
        "benchmark": "bsbm",
        "dataset": "explore-100k",
        "source": source_identity,
        "representations": [
            {"representation": value["representation"], "receipt": path.name}
            for path, value in zip(receipts, values)
        ],
    }
    path = output_dir / "dataset-inventory.json"
    atomic_json(path, inventory)
    return path


def command_version(command: list[str], cwd: Path | None = None) -> str | None:
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)
    text = (result.stdout + result.stderr).strip()
    return text[:4000] if text else None


def run_stage(
    name: str,
    command: list[str],
    log_path: Path,
    outputs: list[Path],
    receipt: Path,
    resume: bool,
    env: dict[str, str] | None = None,
    cwd: Path = BENCHMARKS,
    after: Callable[[], None] | None = None,
) -> dict[str, Any]:
    if resume and receipt.is_file() and all(path.is_file() for path in outputs):
        value = read_json(receipt)
        expected = {item["path"]: item for item in value.get("files", [])}
        valid = all(
            path.name in expected
            and path.stat().st_size == expected[path.name]["size_bytes"]
            and sha256(path) == expected[path.name]["sha256"]
            for path in outputs
        )
        if valid:
            return {
                "stage": name,
                "status": "resumed",
                "receipt": str(receipt),
                "outputs": [str(path) for path in outputs],
                "representation_size": measure_representation_size(outputs),
            }

    for path in outputs:
        path.unlink(missing_ok=True)
    receipt.unlink(missing_ok=True)
    failure_path = log_path.with_suffix(".failure.json")
    failure_path.unlink(missing_ok=True)
    build_metrics = run_build_command(
        command,
        cwd=cwd,
        environment=env,
        log_path=log_path,
    )
    error = None
    confirmed_oom = False
    if build_metrics["status"] != "ok":
        error = f"command exited with code {build_metrics['returncode']}"
    else:
        try:
            if after is not None:
                after()
            for output in outputs:
                if not output.is_file() or output.stat().st_size == 0:
                    raise RuntimeError(f"missing or empty output: {output}")
            if not receipt.is_file():
                raise RuntimeError(f"missing build receipt: {receipt}")
        except BaseException as exception:
            error = f"{type(exception).__name__}: {exception}"
            confirmed_oom = isinstance(exception, MemoryError)

    if error is not None:
        failure = {
            "schema": "rdf-representation-build-failure-v1",
            "stage": name,
            "status": "failed",
            "error": error,
            "build_metrics": build_metrics,
            "partial_outputs": [str(path) for path in outputs if path.exists()],
            "confirmed_oom": confirmed_oom,
        }
        atomic_json(failure_path, failure)
        raise RuntimeError(f"{name} failed; see {log_path} and {failure_path}")

    representation_size = measure_representation_size(outputs)
    value = read_json(receipt)
    producer = value.setdefault("producer", {})
    producer.pop("serialization_timing", None)
    producer["build_metrics"] = build_metrics
    producer["representation_size"] = representation_size
    atomic_json(receipt, value)
    return {
        "stage": name,
        "status": "ok",
        "receipt": str(receipt),
        "build_metrics": build_metrics,
        "representation_size": representation_size,
        "outputs": [file_record(path, path.parent) for path in outputs],
    }


def write_vortex_receipt(source: Path, output: Path, receipt: Path,
                         triple_count: int, index: str) -> None:
    module = __import__("vortex_rdflib")
    module_path = Path(module.__file__).resolve()
    try:
        module_path.relative_to(VORTEX_RDFLIB.resolve())
    except ValueError:
        # Editable installs can expose the repository through a loader. Record, but do not guess.
        pass
    value = {
        "schema": RECEIPT_SCHEMA,
        "benchmark": "bsbm", "dataset": "explore-100k", "created_at_utc": utc_now(),
        "source": {"format": "ntriples", "size_bytes": source.stat().st_size,
                   "sha256": sha256(source)},
        "representation": f"vortex-rdf/dictionary-{index}",
        "files": [file_record(output, output.parent)],
        "producer": {
            "kind": "vortex-rdf-cli", "tool": "vortex-rdf-cli",
            "repository": git_info(VORTEX_RDF),
            "binary_sha256": sha256(VORTEX_CLI),
            "command": ["vortex-rdf-cli", "serialize", "-i", source.name,
                        "-o", output.name, "--indexes", index, "--layout", "dictionary"],
            "layout": "dictionary", "index": index,
            "source_triple_count": triple_count,
            "vortex_rdflib": {"repository": git_info(VORTEX_RDFLIB),
                              "module_path": str(module_path),
                              "version": importlib.metadata.version("vortex-rdflib")},
        },
    }
    atomic_json(receipt, value)


def preflight(source: Path, only: set[str]) -> None:
    errors = []
    required = [(BENCHMARKS, "benchmarks repository")]
    if "vortex" in only:
        required.append((VORTEX_RDF, "Vortex-RDF repository (set VORTEX_RDF_REPO)"))
    if "hdt" in only:
        required += [(RDF2HDT, "rdf2hdt 0.2.0 binary"), (HDT_INDEX_PYTHON, "pinned rdflib-hdt 3.3 Python")]
    for path, label in required:
        if not path.exists(): errors.append(f"missing {label}: {path}")
    if not source.is_file(): errors.append(f"missing source RDF: {source}")
    if shutil.which("vortex-rdf-bench") is None:
        errors.append("vortex-rdf-bench is not installed")
    try:
        if "cottas" in only and importlib.metadata.version("pycottas") != "1.1.0":
            errors.append("pycottas 1.1.0 is required")
        if "vortex" in only:
            importlib.metadata.version("vortex-rdflib")
    except importlib.metadata.PackageNotFoundError as exception:
        errors.append(f"missing Python package: {exception.name}")
    if errors:
        raise RuntimeError("preflight failed:\n- " + "\n- ".join(errors))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path,
        default=BENCHMARKS / "BSBM/data/explore-100k/dataset.nt")
    parser.add_argument("--triple-count", type=int, required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--only", nargs="+", choices=REPRESENTATIONS, default=list(REPRESENTATIONS),
                        help="build only these representations (default: all); 'vortex' needs neither "
                             "rdf2hdt nor pycottas")
    args = parser.parse_args()
    only = set(args.only)
    source = args.source.expanduser().resolve()
    output_dir = source.parent
    preflight(source, only)
    if args.triple_count <= 0:
        raise ValueError("--triple-count must be positive")
    with source.open("rb") as stream:
        observed_lines = sum(1 for line in stream if line.strip())
    if observed_lines != args.triple_count:
        raise ValueError(
            f"--triple-count={args.triple_count} differs from "
            f"non-empty N-Triples lines={observed_lines}"
        )
    logs = output_dir / "build-logs"
    logs.mkdir(parents=True, exist_ok=True)
    ledger_path = output_dir / "representation-build-ledger.json"
    ledger = {
        "schema": SCHEMA, "benchmark": "bsbm", "dataset": "explore-100k",
        "started_at_utc": utc_now(), "status": "running",
        "environment": {"python": sys.version, "platform": platform.platform(),
                        "benchmarks": git_info(BENCHMARKS),
                        "vortex_rdf": git_info(VORTEX_RDF),
                        "vortex_rdflib": git_info(VORTEX_RDFLIB)},
        "source": file_record(source, output_dir), "stages": [],
    }
    atomic_json(ledger_path, ledger)
    rdf_receipt = source_receipt(source, output_dir, args.triple_count)
    inventory = output_dir / "dataset-inventory.json"

    try:
        # Build the current Vortex CLI once. Compilation time is not serialization time.
        build_command = ["cargo", "build", "--release", "-p", "vortex-rdf-cli"]
        build_log = logs / "vortex-cli-build.log"
        started = time.perf_counter_ns()
        with build_log.open("w", encoding="utf-8") as log:
            result = subprocess.run(build_command, cwd=VORTEX_RDF, stdout=log,
                                    stderr=subprocess.STDOUT, check=False)
        if result.returncode != 0 or not VORTEX_CLI.is_file():
            raise RuntimeError(f"Vortex CLI build failed; see {build_log}")
        ledger["vortex_cli_build"] = {
            "elapsed_ns": time.perf_counter_ns() - started,
            "command": build_command, "binary": str(VORTEX_CLI),
            "binary_sha256": sha256(VORTEX_CLI), "log": str(build_log),
        }
        atomic_json(ledger_path, ledger)

        hdt_receipt = output_dir / "hdt-default-receipt.json"
        cottas_receipt = output_dir / "cottas-default-receipt.json"
        if "hdt" in only:
            hdt = output_dir / "dataset.hdt"
            hdt_index = output_dir / "dataset.hdt.index.v1-1"
            hdt_receipt = output_dir / "hdt-default-receipt.json"
            ledger["stages"].append(run_stage(
                "hdt/default",
                ["vortex-rdf-bench", "bsbm", "generate-hdt", "--source", str(source),
                 "--output", str(hdt), "--rdf-receipt", str(rdf_receipt),
                 "--hdt-receipt", str(hdt_receipt), "--inventory", str(inventory),
                 "--rdf2hdt", str(RDF2HDT), "--source-triple-count", str(args.triple_count)],
                logs / "hdt.log", [hdt, hdt_index], hdt_receipt, args.resume,
                env={**os.environ, "VORTEX_RDF_BENCH_HDT_PYTHON": str(HDT_INDEX_PYTHON)},
            )); atomic_json(ledger_path, ledger)

        if "cottas" in only:
            cottas = output_dir / "dataset.cottas"
            cottas_receipt = output_dir / "cottas-default-receipt.json"
            ledger["stages"].append(run_stage(
                "cottas/default",
                ["vortex-rdf-bench", "bsbm", "generate-cottas", "--source", str(source),
                 "--output", str(cottas), "--rdf-receipt", str(rdf_receipt),
                 "--cottas-receipt", str(cottas_receipt), "--inventory", str(inventory),
                 "--source-triple-count", str(args.triple_count)],
                logs / "cottas.log", [cottas], cottas_receipt, args.resume,
            )); atomic_json(ledger_path, ledger)

        vortex_receipts = []
        if "vortex" in only:
            for index in ("secondary-by-reference", "secondary-by-copy"):
                output = output_dir / f"dataset-dictionary-{index}.vortex"
                receipt = output_dir / f"vortex-rdf-dictionary-{index}-receipt.json"
                vortex_receipts.append(receipt)
                command = [str(VORTEX_CLI), "serialize", "-i", str(source), "-o", str(output),
                           "--indexes", index, "--layout", "dictionary"]
                ledger["stages"].append(run_stage(
                    f"vortex-rdf/dictionary-{index}", command,
                    logs / f"vortex-{index}.log", [output], receipt, args.resume,
                    env={**os.environ, "RUST_LOG": "vortex_rdf_cli=debug,vortex_rdf_core=debug"},
                    cwd=VORTEX_RDF,
                    after=lambda s=source, o=output, r=receipt, i=index:
                        write_vortex_receipt(s, o, r, args.triple_count, i),
                )); atomic_json(ledger_path, ledger)

        receipts = [rdf_receipt, *([hdt_receipt] if "hdt" in only else []),
                    *([cottas_receipt] if "cottas" in only else []), *vortex_receipts]
        upsert_inventory(output_dir, receipts, source)
        ledger["status"] = "ok"
        ledger["finished_at_utc"] = utc_now()
        ledger["inventory"] = str(inventory)
        ledger["receipts"] = [str(path) for path in receipts]
        atomic_json(ledger_path, ledger)
    except BaseException as error:
        ledger["status"] = "failed"
        ledger["finished_at_utc"] = utc_now()
        ledger["error"] = f"{type(error).__name__}: {error}"
        atomic_json(ledger_path, ledger)
        raise

    print(ledger_path)
    for stage in ledger["stages"]:
        elapsed = stage.get("timing", {}).get("elapsed_ns")
        print(f"{stage['stage']}: {stage['status']} elapsed_ns={elapsed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
