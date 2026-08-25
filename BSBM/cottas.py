"""Create and verify a COTTAS representation for one RDF source."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from importlib import import_module, metadata
from pathlib import Path
from types import ModuleType

from benchmark_core.representation import create_inventory, create_receipt, load_receipt

PYCOTTAS_VERSION = "1.1.0"
COTTAS_INDEX = "spo"


def _load_pycottas() -> ModuleType:
    try:
        version = metadata.version("pycottas")
    except metadata.PackageNotFoundError as error:
        raise RuntimeError("pycottas 1.1.0 is required") from error
    if version != PYCOTTAS_VERSION:
        raise RuntimeError(f"pycottas {PYCOTTAS_VERSION} is required, found {version}")
    return import_module("pycottas")


def _inventory_receipts(path: Path) -> list[str]:
    if not path.is_file():
        return []
    value = json.loads(path.read_text(encoding="utf-8"))
    representations = value.get("representations")
    if not isinstance(representations, list):
        raise ValueError("Existing dataset inventory has invalid representations")
    receipts: list[str] = []
    for item in representations:
        if not isinstance(item, dict) or not isinstance(item.get("receipt"), str):
            raise ValueError("Existing dataset inventory has an invalid receipt entry")
        if item["receipt"] not in receipts:
            receipts.append(item["receipt"])
    return receipts


def generate(*, source: Path, output: Path, rdf_receipt: Path,
             cottas_receipt: Path, inventory: Path,
             source_triple_count: int) -> dict:
    source = source.resolve()
    output = output.resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Source RDF file is missing: {source}")
    if source_triple_count < 0:
        raise ValueError("source_triple_count must be non-negative")
    source_value = load_receipt(rdf_receipt)
    if source_value["representation"] != "rdf/source":
        raise ValueError("Source receipt must describe rdf/source")
    source_file = source_value["files"][0]
    if (source_file["sha256"] != source_value["source"]["sha256"] or
            source_file["size_bytes"] != source_value["source"]["size_bytes"]):
        raise ValueError("rdf/source receipt has inconsistent source identity")
    if (source.stat().st_size != source_value["source"]["size_bytes"]):
        raise ValueError("Source RDF file size differs from rdf/source receipt")

    pycottas = _load_pycottas()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.stem}.tmp{output.suffix or '.cottas'}")
    temporary.unlink(missing_ok=True)
    try:
        pycottas.rdf2cottas(str(source), str(temporary), index=COTTAS_INDEX, disk=True)
        if not temporary.is_file() or temporary.stat().st_size == 0:
            raise ValueError("pycottas did not create a non-empty COTTAS file")
        verified = pycottas.verify(str(temporary))
        if verified is False:
            raise ValueError("pycottas rejected the generated COTTAS file")
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)

    receipt = create_receipt(
        receipt_path=cottas_receipt, benchmark=source_value["benchmark"],
        dataset=source_value["dataset"], source_format=source_value["source"]["format"],
        source_path=source, representation="cottas/default", files=[output.name],
        producer={"kind": "pycottas", "tool": "pycottas", "version": PYCOTTAS_VERSION,
                  "index": COTTAS_INDEX, "disk": True,
                  "command": ["pycottas.rdf2cottas", source.name, output.name,
                              "index=spo", "disk=True"],
                  "source_triple_count": source_triple_count},
        created_at_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    receipts = _inventory_receipts(inventory)
    for required in (rdf_receipt.name, cottas_receipt.name):
        if required not in receipts:
            receipts.append(required)
    create_inventory(inventory_path=inventory, benchmark=source_value["benchmark"],
                     dataset=source_value["dataset"], receipt_paths=receipts)
    return receipt


def verify(*, receipt: Path) -> dict:
    value = load_receipt(receipt)
    if value["representation"] != "cottas/default":
        raise ValueError("Receipt must describe cottas/default")
    return value
