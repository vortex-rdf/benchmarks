"""Create one reproducible Vortex-RDF representation from an RDF source."""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from benchmark_core.hashing import sha256_file
from benchmark_core.representation import create_inventory, create_receipt, load_receipt

VORTEX_RDF_COMMIT = "0a0e51171aa42e79defdcd322bc1a328a93fcd11"
CONFIGURATION = "simple-dictionary-native-rdf-store"
INDEX_TYPE = "simple-dictionary"
STORAGE_LAYOUT = "native-rdf-store"


def _inventory_receipts(path: Path) -> list[str]:
    if not path.is_file():
        return []
    value = json.loads(path.read_text(encoding="utf-8"))
    items = value.get("representations")
    if not isinstance(items, list):
        raise ValueError("Existing dataset inventory has invalid representations")
    receipts = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("receipt"), str):
            raise ValueError("Existing dataset inventory has an invalid receipt entry")
        if item["receipt"] not in receipts:
            receipts.append(item["receipt"])
    return receipts


def generate(*, source: Path, output: Path, rdf_receipt: Path, vortex_receipt: Path,
             inventory: Path, vortex_cli: Path, vortex_repository: Path,
             source_triple_count: int) -> dict:
    source = source.resolve(); output = output.resolve(); vortex_cli = vortex_cli.resolve()
    vortex_repository = vortex_repository.resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Source RDF file is missing: {source}")
    if not vortex_cli.is_file():
        raise FileNotFoundError(f"Vortex-RDF CLI is missing: {vortex_cli}")
    if source_triple_count < 0:
        raise ValueError("source_triple_count must be non-negative")
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=vortex_repository,
                            check=True, text=True, capture_output=True).stdout.strip()
    if commit != VORTEX_RDF_COMMIT:
        raise ValueError(f"Expected Vortex-RDF commit {VORTEX_RDF_COMMIT}, found {commit}")
    source_value = load_receipt(rdf_receipt)
    if source_value["representation"] != "rdf/source":
        raise ValueError("Source receipt must describe rdf/source")
    identity = source_value["source"]
    if source.stat().st_size != identity["size_bytes"] or sha256_file(source) != identity["sha256"]:
        raise ValueError("Source RDF file differs from rdf/source receipt")

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.stem}.tmp{output.suffix or '.vortex'}")
    temporary.unlink(missing_ok=True)
    command = [str(vortex_cli), "serialize", "--input", str(source), "--output", str(temporary),
               "--index-type", INDEX_TYPE, "--storage-layout", STORAGE_LAYOUT]
    try:
        subprocess.run(command, check=True)
        if not temporary.is_file() or temporary.stat().st_size == 0:
            raise ValueError("Vortex-RDF did not create a non-empty artifact")
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)

    receipt = create_receipt(
        receipt_path=vortex_receipt, benchmark=source_value["benchmark"],
        dataset=source_value["dataset"], source_format=identity["format"], source_path=source,
        representation=f"vortex-rdf/{CONFIGURATION}", files=[output.name],
        producer={"kind": "vortex-rdf-cli", "tool": "vortex-rdf-cli", "version": "0.1.0",
                  "repository_commit": commit, "binary_sha256": sha256_file(vortex_cli),
                  "index_type": INDEX_TYPE, "storage_layout": STORAGE_LAYOUT,
                  "build_profile": "release", "source_triple_count": source_triple_count,
                  "command": ["vortex-rdf-cli", "serialize", "--input", source.name,
                              "--output", output.name, "--index-type", INDEX_TYPE,
                              "--storage-layout", STORAGE_LAYOUT]},
        created_at_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    receipts = _inventory_receipts(inventory)
    for required in (rdf_receipt.name, vortex_receipt.name):
        if required not in receipts:
            receipts.append(required)
    create_inventory(inventory_path=inventory, benchmark=source_value["benchmark"],
                     dataset=source_value["dataset"], receipt_paths=receipts)
    return receipt


def verify(*, receipt: Path) -> dict:
    value = load_receipt(receipt)
    expected = f"vortex-rdf/{CONFIGURATION}"
    if value["representation"] != expected:
        raise ValueError(f"Receipt must describe {expected}")
    return value
