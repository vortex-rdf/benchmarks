"""WatDiv representation declarations and atomic build orchestration."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from BSBM.cottas import PYCOTTAS_VERSION, verify as verify_cottas
from BSBM.hdt import HDT_INDEX_SUFFIX, RDF2HDT_VERSION, verify as verify_hdt
from benchmark_core.atomic_io import write_json_atomic
from benchmark_core.build_metrics import measure_representation_size, run_build_command
from benchmark_core.hashing import sha256_file
from benchmark_core.representation import create_inventory, create_receipt, load_receipt
from WatDiv.manifest import DATASET_DECLARATIONS

DEFAULT_OUTPUT_ROOT = Path("WatDiv/data/generated")
DEFAULT_HDT_TOOL = Path("BSBM/data/tools/rdf2hdt-0.2.0/bin/rdf2hdt")
DEFAULT_VORTEX_REPOSITORY = Path("/users/u0182905/vortex-rdf")
DEFAULT_VORTEX_CLI = DEFAULT_VORTEX_REPOSITORY / "target/release/vortex-rdf-cli"
DEFAULT_HDT_INDEX_PYTHON = Path(
    os.environ.get("KROWN_HDT_INDEX_PYTHON", "/users/u0182905/KROWN/.runtime/rdflib-hdt-3.3/bin/python")
)
VORTEX_LAYOUT = "dictionary"
VORTEX_CONFIGURATIONS = {
    "vortex-by-reference": {
        "index": "secondary-by-reference",
        "receipt_representation": "vortex-rdf/dictionary-secondary-by-reference",
        "output_name": "vortex",
    },
    "vortex-by-copy": {
        "index": "secondary-by-copy",
        "receipt_representation": "vortex-rdf/dictionary-secondary-by-copy",
        "output_name": "vortex-by-copy",
    },
}

REPRESENTATION_TYPES = (
    "hdt",
    "cottas",
    "vortex-by-reference",
    "vortex-by-copy",
)

REPRESENTATION_DECLARATIONS: dict[tuple[str, str], dict[str, Any]] = {
    (dataset, representation): {
        "benchmark": "watdiv",
        "dataset": dataset,
        "source_path": declaration["dataset_path"],
        "source_format": "ntriples",
        "representation": representation,
        "output_relative": (
            f"{dataset}/{VORTEX_CONFIGURATIONS[representation]['output_name']}"
            if representation in VORTEX_CONFIGURATIONS
            else f"{dataset}/{representation}"
        ),
        "builder": {
            "hdt": "BSBM.hdt.generate via vortex-rdf-bench bsbm generate-hdt",
            "cottas": "BSBM.cottas.generate via vortex-rdf-bench bsbm generate-cottas",
            "vortex-by-reference": "vortex-rdf-cli serialize (dictionary, secondary-by-reference)",
            "vortex-by-copy": "vortex-rdf-cli serialize (dictionary, secondary-by-copy)",
        }[representation],
        "build_mode": "atomic-directory-promotion",
        "expected_files": {
            "hdt": ("dataset.hdt", f"dataset.hdt{HDT_INDEX_SUFFIX}"),
            "cottas": ("dataset.cottas",),
            "vortex-by-reference": ("dataset.vortex",),
            "vortex-by-copy": ("dataset.vortex",),
        }[representation],
        "validation": {
            "hdt": "rdf-representation-receipt-v1 plus rdflib-hdt side-index verification",
            "cottas": "rdf-representation-receipt-v1 plus pycottas.verify",
            "vortex-by-reference": "rdf-representation-receipt-v1 plus matching dictionary/by-reference identity",
            "vortex-by-copy": "rdf-representation-receipt-v1 plus matching dictionary/by-copy identity",
        }[representation],
        "receipt_name": (
            "vortex-receipt.json"
            if representation in VORTEX_CONFIGURATIONS
            else f"{representation}-receipt.json"
        ),
    }
    for dataset, declaration in DATASET_DECLARATIONS.items()
    for representation in REPRESENTATION_TYPES
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _resolve_path(value: str | Path, *, base: Path | None = None) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = (base or _repo_root()) / path
    return path.resolve()


def declaration(dataset: str, representation: str) -> dict[str, Any]:
    if dataset not in DATASET_DECLARATIONS:
        raise ValueError(f"Unsupported WatDiv dataset: {dataset!r}")
    if representation not in REPRESENTATION_TYPES:
        raise ValueError(f"Unsupported WatDiv representation: {representation!r}")
    return dict(REPRESENTATION_DECLARATIONS[(dataset, representation)])


def output_directory(dataset: str, representation: str, output_root: str | Path | None = None) -> Path:
    item = declaration(dataset, representation)
    root = _resolve_path(output_root or DEFAULT_OUTPUT_ROOT)
    return root / item["output_relative"]


def _artifact_paths(root: Path, representation: str) -> list[Path]:
    return [root / name for name in {
        "hdt": ("dataset.hdt", f"dataset.hdt{HDT_INDEX_SUFFIX}"),
        "cottas": ("dataset.cottas",),
        "vortex-by-reference": ("dataset.vortex",),
        "vortex-by-copy": ("dataset.vortex",),
    }[representation]]


def _source_path(dataset: str) -> Path:
    return _resolve_path(DATASET_DECLARATIONS[dataset]["dataset_path"])


def _source_receipt(root: Path, source: Path, dataset: str) -> Path:
    staged = root / source.name
    if not staged.exists():
        os.link(source, staged)
    if staged.stat().st_size != source.stat().st_size:
        raise ValueError("staged source size differs from source dataset")
    create_receipt(
        receipt_path=root / "rdf-source-receipt.json",
        benchmark="watdiv",
        dataset=dataset,
        source_format="ntriples",
        source_path=staged,
        representation="rdf/source",
        files=[staged.name],
        producer={"kind": "WatDiv-local-dataset", "source_path": str(source)},
        created_at_utc=_utc_now(),
    )
    return root / "rdf-source-receipt.json"


def _existing_complete(output: Path, representation: str, receipt: Path) -> bool:
    if not output.is_dir() or not receipt.is_file():
        return False
    try:
        load_receipt(receipt)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return False
    return all(path.is_file() and path.stat().st_size > 0 for path in _artifact_paths(output, representation))


def _dependency_path(value: str | Path | None, default: Path) -> Path:
    return _resolve_path(value or default)


def _command_for(
    representation: str,
    *,
    source: Path,
    output: Path,
    source_receipt: Path,
    receipt: Path,
    inventory: Path,
    rdf2hdt: Path,
    hdt_index_python: Path,
    vortex_cli: Path,
    vortex_repository: Path,
    source_triple_count: int,
) -> tuple[list[str], dict[str, str], Path]:
    log_cwd = _repo_root()
    if representation == "hdt":
        return (
            [
                sys.executable,
                "-m",
                "benchmark_core.cli",
                "bsbm",
                "generate-hdt",
                "--source",
                str(source),
                "--output",
                str(output),
                "--rdf-receipt",
                str(source_receipt),
                "--hdt-receipt",
                str(receipt),
                "--inventory",
                str(inventory),
                "--rdf2hdt",
                str(rdf2hdt),
                "--source-triple-count",
                str(source_triple_count),
            ],
            {**os.environ, "KROWN_HDT_INDEX_PYTHON": str(hdt_index_python)},
            log_cwd,
        )
    if representation == "cottas":
        return (
            [
                sys.executable,
                "-m",
                "benchmark_core.cli",
                "bsbm",
                "generate-cottas",
                "--source",
                str(source),
                "--output",
                str(output),
                "--rdf-receipt",
                str(source_receipt),
                "--cottas-receipt",
                str(receipt),
                "--inventory",
                str(inventory),
                "--source-triple-count",
                str(source_triple_count),
            ],
            dict(os.environ),
            log_cwd,
        )
    if representation in VORTEX_CONFIGURATIONS:
        configuration = VORTEX_CONFIGURATIONS[representation]
        return (
            [
                str(vortex_cli),
                "serialize",
                "-i",
                str(source),
                "-o",
                str(output),
                "--layout",
                VORTEX_LAYOUT,
                "--indexes",
                configuration["index"],
            ],
            {**os.environ, "RUST_LOG": "vortex_rdf_cli=debug,vortex_rdf_core=debug"},
            vortex_repository,
        )
    raise ValueError(f"Unsupported WatDiv representation: {representation!r}")


def _write_vortex_receipt(
    *,
    root: Path,
    source: Path,
    dataset: str,
    receipt: Path,
    output: Path,
    source_triple_count: int,
    vortex_cli: Path,
    vortex_repository: Path,
    representation: str,
) -> None:
    configuration = VORTEX_CONFIGURATIONS[representation]
    commit = subprocess.run(
        ["git", "-C", str(vortex_repository), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    create_receipt(
        receipt_path=receipt,
        benchmark="watdiv",
        dataset=dataset,
        source_format="ntriples",
        source_path=source,
        representation=configuration["receipt_representation"],
        files=[output.name],
        producer={
            "kind": "vortex-rdf-cli",
            "tool": "vortex-rdf-cli",
            "version": "verified-by-cli-help",
            "repository_commit": commit,
            "binary_sha256": sha256_file(vortex_cli),
            "index": configuration["index"],
            "layout": VORTEX_LAYOUT,
            "source_triple_count": source_triple_count,
            "command": ["vortex-rdf-cli", "serialize", "-i", source.name, "-o", output.name,
                        "--layout", VORTEX_LAYOUT, "--indexes", configuration["index"]],
        },
        created_at_utc=_utc_now(),
    )


def _annotate_receipt(receipt: Path, build_metrics: dict[str, Any], validation: dict[str, Any],
                      output_paths: list[Path], source: Path) -> dict[str, Any]:
    value = load_receipt(receipt)
    value["producer"]["build_metrics"] = build_metrics
    value["producer"]["validation"] = validation
    value["producer"]["representation_size"] = measure_representation_size(output_paths)
    value["producer"]["source_path"] = str(source)
    write_json_atomic(receipt, value)
    return load_receipt(receipt)


def _validate_output(representation: str, receipt: Path, root: Path) -> dict[str, Any]:
    started = time.perf_counter_ns()
    if representation == "hdt":
        from BSBM.hdt import verify

        verify(receipt=receipt)
    elif representation == "cottas":
        verify_cottas(receipt=receipt)
    else:
        value = load_receipt(receipt)
        expected = VORTEX_CONFIGURATIONS[representation]["receipt_representation"]
        if value["representation"] != expected:
            raise ValueError(
                f"Vortex receipt has representation {value['representation']!r}; expected {expected!r}"
            )
    paths = _artifact_paths(root, representation)
    for path in paths:
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f"Representation output is missing or empty: {path}")
    return {"duration_ns": time.perf_counter_ns() - started, "result": "passed"}


def classify_failure(error: BaseException, *, returncode: int | None = None) -> str:
    """Classify failures without treating every nonzero exit as OOM."""
    if isinstance(error, MemoryError) or str(error) == "confirmed_oom":
        return "confirmed_oom"
    if isinstance(error, TimeoutError):
        return "timeout"
    if isinstance(error, KeyboardInterrupt):
        return "interrupted"
    if isinstance(error, (FileNotFoundError, ModuleNotFoundError)):
        return "missing_dependency"
    if returncode is not None and returncode < 0:
        return "interrupted"
    return "build_failed"


def build(
    *,
    dataset: str,
    representation: str,
    output_root: str | Path | None = None,
    force: bool = False,
    source_path: str | Path | None = None,
    rdf2hdt: str | Path | None = None,
    hdt_index_python: str | Path | None = None,
    vortex_cli: str | Path | None = None,
    vortex_repository: str | Path | None = None,
    log_dir: str | Path | None = None,
) -> dict[str, Any]:
    item = declaration(dataset, representation)
    source = _resolve_path(source_path or item["source_path"])
    if not source.is_file():
        raise FileNotFoundError(f"WatDiv source dataset is missing: {source}")
    final_root = output_directory(dataset, representation, output_root)
    final_receipt = final_root / item["receipt_name"]
    if _existing_complete(final_root, representation, final_receipt) and not force:
        raise FileExistsError(f"Complete representation already exists: {final_root}; use --force to rebuild")
    if representation == "hdt":
        rdf2hdt_path = _dependency_path(rdf2hdt, DEFAULT_HDT_TOOL)
        hdt_python_path = _dependency_path(hdt_index_python, DEFAULT_HDT_INDEX_PYTHON)
        if not rdf2hdt_path.is_file():
            raise FileNotFoundError(f"rdf2hdt binary is missing: {rdf2hdt_path}")
        if not hdt_python_path.is_file():
            raise FileNotFoundError(f"HDT index Python is missing: {hdt_python_path}")
    else:
        rdf2hdt_path = _dependency_path(rdf2hdt, DEFAULT_HDT_TOOL)
        hdt_python_path = _dependency_path(hdt_index_python, DEFAULT_HDT_INDEX_PYTHON)
    if representation in VORTEX_CONFIGURATIONS:
        vortex_cli_path = _dependency_path(vortex_cli, DEFAULT_VORTEX_CLI)
        vortex_repository_path = _resolve_path(vortex_repository or DEFAULT_VORTEX_REPOSITORY)
        if not vortex_cli_path.is_file():
            raise FileNotFoundError(f"Vortex-RDF CLI is missing: {vortex_cli_path}")
        if not vortex_repository_path.is_dir():
            raise FileNotFoundError(f"Vortex-RDF repository is missing: {vortex_repository_path}")
    else:
        vortex_cli_path = _dependency_path(vortex_cli, DEFAULT_VORTEX_CLI)
        vortex_repository_path = _resolve_path(vortex_repository or DEFAULT_VORTEX_REPOSITORY)

    final_root.parent.mkdir(parents=True, exist_ok=True)
    logs = _resolve_path(log_dir or "/tmp/watdiv-representation-build-logs")
    logs.mkdir(parents=True, exist_ok=True)
    log_path = logs / f"{dataset}-{representation}.log"
    temp_root = Path(tempfile.mkdtemp(prefix=f".{dataset}-{representation}.", dir=final_root.parent))
    output = temp_root / item["expected_files"][0]
    receipt = temp_root / item["receipt_name"]
    inventory = temp_root / "dataset-inventory.json"
    staged_source = temp_root / source.name
    try:
        source_receipt = _source_receipt(temp_root, source, dataset)
        source_count = sum(1 for line in source.open("rb") if line.strip())
        command, environment, cwd = _command_for(
            representation,
            source=source,
            output=output,
            source_receipt=source_receipt,
            receipt=receipt,
            inventory=inventory,
            rdf2hdt=rdf2hdt_path,
            hdt_index_python=hdt_python_path,
            vortex_cli=vortex_cli_path,
            vortex_repository=vortex_repository_path,
            source_triple_count=source_count,
        )
        metrics = run_build_command(command, cwd=cwd, environment=environment, log_path=log_path)
        if metrics["status"] != "ok":
            raise RuntimeError(f"{representation} build failed with exit code {metrics['returncode']}")
        if representation in VORTEX_CONFIGURATIONS:
            _write_vortex_receipt(
                root=temp_root,
                source=staged_source,
                dataset=dataset,
                receipt=receipt,
                output=output,
                source_triple_count=source_count,
                vortex_cli=vortex_cli_path,
                vortex_repository=vortex_repository_path,
                representation=representation,
            )
            create_inventory(
                inventory_path=inventory,
                benchmark="watdiv",
                dataset=dataset,
                receipt_paths=[source_receipt.name, receipt.name],
            )
        validation = _validate_output(representation, receipt, temp_root)
        _annotate_receipt(receipt, metrics, validation, _artifact_paths(temp_root, representation), source)
        if final_root.exists():
            if not force:
                raise FileExistsError(f"Output appeared during build: {final_root}")
            shutil.rmtree(final_root)
        temp_root.replace(final_root)
        temp_root = final_root
        receipt = final_root / item["receipt_name"]
        result = load_receipt(receipt)
        return {
            "dataset": dataset,
            "representation": representation,
            "status": "ok",
            "source_path": str(source),
            "source_sha256": result["source"]["sha256"],
            "output_paths": [str(path) for path in _artifact_paths(final_root, representation)],
            "receipt_path": str(receipt),
            "builder": item["builder"],
            "builder_version": {
                "hdt": RDF2HDT_VERSION,
                "cottas": PYCOTTAS_VERSION,
                "vortex-by-reference": "verified-by-cli-help",
                "vortex-by-copy": "verified-by-cli-help",
            }[representation],
            "verified_command": command,
            "build_duration_seconds": metrics["elapsed_ns"] / 1_000_000_000,
            "validation_duration_seconds": validation["duration_ns"] / 1_000_000_000,
            "source_size_bytes": source.stat().st_size,
            "output_size_bytes": result["producer"]["representation_size"]["logical_bytes"],
            "peak_rss_bytes": metrics["memory"]["peak_rss_bytes"],
            "host": {"platform": sys.platform, "python": sys.version.split()[0]},
            "failure_classification": None,
            "log_paths": [str(log_path)],
        }
    except MemoryError:
        raise RuntimeError("confirmed_oom") from None
    finally:
        if temp_root.exists() and temp_root != final_root:
            shutil.rmtree(temp_root, ignore_errors=True)


def validate(dataset: str, representation: str, output_root: str | Path | None = None) -> dict[str, Any]:
    item = declaration(dataset, representation)
    root = output_directory(dataset, representation, output_root)
    receipt = root / item["receipt_name"]
    validation = _validate_output(representation, receipt, root)
    return {"dataset": dataset, "representation": representation, "status": "passed", **validation}


def inspect(dataset: str, representation: str, output_root: str | Path | None = None) -> dict[str, Any]:
    item = declaration(dataset, representation)
    source = _source_path(dataset)
    root = output_directory(dataset, representation, output_root)
    return {
        "dataset": dataset,
        "representation": representation,
        "source_path": str(source),
        "source_exists": source.is_file(),
        "output_directory": str(root),
        "output_exists": root.exists(),
        "expected_files": list(item["expected_files"]),
        "receipt_path": str(root / item["receipt_name"]),
        "declaration": item,
    }