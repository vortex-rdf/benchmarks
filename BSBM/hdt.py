"""Create and verify an HDT representation for one RDF source."""
from __future__ import annotations
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from benchmark_core.representation import create_inventory, create_receipt, load_receipt

RDF2HDT_VERSION = "0.2.0"

def generate(*, source: Path, output: Path, rdf_receipt: Path, hdt_receipt: Path,
             inventory: Path, rdf2hdt: Path, source_triple_count: int) -> dict:
    source = source.resolve(); output = output.resolve(); rdf2hdt = rdf2hdt.resolve()
    if not source.is_file(): raise FileNotFoundError(f"Source RDF file is missing: {source}")
    if not rdf2hdt.is_file(): raise FileNotFoundError(f"rdf2hdt binary is missing: {rdf2hdt}")
    source_value = load_receipt(rdf_receipt)
    if source_value["representation"] != "rdf/source":
        raise ValueError("Source receipt must describe rdf/source")
    source_file = source_value["files"][0]
    if source_file["sha256"] != source_value["source"]["sha256"]:
        raise ValueError("rdf/source receipt has inconsistent source identity")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    temporary.unlink(missing_ok=True)
    command = [str(rdf2hdt), "convert", "--input", str(source), "--output", str(temporary)]
    try:
        subprocess.run(command, check=True)
        if not temporary.is_file() or temporary.stat().st_size == 0:
            raise ValueError("rdf2hdt did not create a non-empty HDT file")
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    receipt = create_receipt(
        receipt_path=hdt_receipt, benchmark=source_value["benchmark"],
        dataset=source_value["dataset"], source_format=source_value["source"]["format"],
        source_path=source, representation="hdt/default", files=[output.name],
        producer={"kind":"rdf2hdt-rust", "tool":"rdf2hdt", "version":RDF2HDT_VERSION,
                  "command":["rdf2hdt","convert","--input",source.name,"--output",output.name],
                  "source_triple_count":source_triple_count},
        created_at_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    create_inventory(inventory_path=inventory, benchmark=source_value["benchmark"],
                     dataset=source_value["dataset"],
                     receipt_paths=[rdf_receipt.name, hdt_receipt.name])
    return receipt

def verify(*, receipt: Path) -> dict:
    value = load_receipt(receipt)
    if value["representation"] != "hdt/default":
        raise ValueError("Receipt must describe hdt/default")
    return value
