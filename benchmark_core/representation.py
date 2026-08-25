"""Strict receipts for physical RDF dataset representations."""
from __future__ import annotations
import json, re
from pathlib import Path
from typing import Any, Mapping, Sequence
from benchmark_core.atomic_io import write_json_atomic
from benchmark_core.hashing import sha256_file

_SCHEMA = "rdf-representation-receipt-v1"
_INVENTORY_SCHEMA = "rdf-dataset-inventory-v1"
_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*(?:/[a-z0-9][a-z0-9._-]*)*$")
_SHA = re.compile(r"^[0-9a-f]{64}$")

def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value): raise ValueError(f"{field} must be a stable lowercase identifier")
    return value

def _contained(root: Path, value: Any, field: str) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute() or ".." in Path(value).parts: raise ValueError(f"{field} must be a contained relative path")
    result=(root/value).resolve()
    try: result.relative_to(root.resolve())
    except ValueError as error: raise ValueError(f"{field} escapes its receipt directory") from error
    return result

def _json_object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(k,str) for k in value): raise ValueError(f"{field} must be a JSON object")
    result=dict(value); json.dumps(result,allow_nan=False,sort_keys=True); return result

def _file_record(root: Path, path: str) -> dict[str, Any]:
    target=_contained(root,path,"file.path")
    if not target.is_file(): raise FileNotFoundError(f"Representation file is missing: {target}")
    return {"path":path,"size_bytes":target.stat().st_size,"sha256":sha256_file(target)}

def create_receipt(*, receipt_path: Path, benchmark: str, dataset: str, source_format: str,
                   source_path: Path, representation: str, files: Sequence[str],
                   producer: Mapping[str,Any], created_at_utc: str) -> dict[str,Any]:
    root=receipt_path.resolve().parent; source=source_path.resolve()
    if not source.is_file(): raise FileNotFoundError(f"Source RDF file is missing: {source}")
    value={"schema":_SCHEMA,"benchmark":_identifier(benchmark,"benchmark"),"dataset":_identifier(dataset,"dataset"),
      "created_at_utc":created_at_utc,"source":{"format":_identifier(source_format,"source.format"),"size_bytes":source.stat().st_size,"sha256":sha256_file(source)},
      "representation":_identifier(representation,"representation"),"files":[_file_record(root,p) for p in files],"producer":_json_object(producer,"producer")}
    validate_receipt(value,root,verify_files=True); write_json_atomic(receipt_path,value); return value

def validate_receipt(value: Any, root: Path, *, verify_files: bool) -> dict[str,Any]:
    if not isinstance(value,dict) or set(value)!={"schema","benchmark","dataset","created_at_utc","source","representation","files","producer"}: raise ValueError("Representation receipt has unexpected fields")
    if value["schema"]!=_SCHEMA: raise ValueError("Unsupported representation receipt schema")
    _identifier(value["benchmark"],"benchmark"); _identifier(value["dataset"],"dataset"); _identifier(value["representation"],"representation")
    if not isinstance(value["created_at_utc"],str) or not value["created_at_utc"].endswith("Z"): raise ValueError("created_at_utc must be a UTC timestamp ending in Z")
    source=value["source"]
    if not isinstance(source,dict) or set(source)!={"format","size_bytes","sha256"}: raise ValueError("source has unexpected fields")
    _identifier(source["format"],"source.format")
    if not isinstance(source["size_bytes"],int) or isinstance(source["size_bytes"],bool) or source["size_bytes"]<0: raise ValueError("source.size_bytes must be non-negative")
    if not isinstance(source["sha256"],str) or not _SHA.fullmatch(source["sha256"]): raise ValueError("source.sha256 must be lowercase SHA-256")
    files=value["files"]
    if not isinstance(files,list) or not files: raise ValueError("files must be a non-empty array")
    paths=[]
    for item in files:
      if not isinstance(item,dict) or set(item)!={"path","size_bytes","sha256"}: raise ValueError("file record has unexpected fields")
      target=_contained(root,item["path"],"file.path"); paths.append(item["path"])
      if not isinstance(item["size_bytes"],int) or isinstance(item["size_bytes"],bool) or item["size_bytes"]<0: raise ValueError("file size must be non-negative")
      if not isinstance(item["sha256"],str) or not _SHA.fullmatch(item["sha256"]): raise ValueError("file sha256 must be lowercase SHA-256")
      if verify_files and (not target.is_file() or target.stat().st_size!=item["size_bytes"] or sha256_file(target)!=item["sha256"]): raise ValueError(f"Representation file differs from receipt: {item['path']}")
    if len(paths)!=len(set(paths)): raise ValueError("Representation file paths must be unique")
    _json_object(value["producer"],"producer"); return value

def load_receipt(path: Path, *, verify_files: bool=True) -> dict[str,Any]:
    target=path.resolve(); return validate_receipt(json.loads(target.read_text(encoding="utf-8")),target.parent,verify_files=verify_files)

def create_inventory(*, inventory_path: Path, benchmark: str, dataset: str, receipt_paths: Sequence[str]) -> dict[str,Any]:
    if not receipt_paths: raise ValueError("receipt_paths must not be empty")
    root=inventory_path.resolve().parent; receipts=[]; identity=None; ids=set()
    for relative in receipt_paths:
      receipt_path=_contained(root,relative,"receipt path"); receipt=load_receipt(receipt_path)
      current=(receipt["benchmark"],receipt["dataset"],receipt["source"]["format"],receipt["source"]["size_bytes"],receipt["source"]["sha256"])
      if identity is None: identity=current
      if current!=identity: raise ValueError("All inventory receipts must use one source RDF identity")
      if receipt["representation"] in ids: raise ValueError("Inventory representation identifiers must be unique")
      ids.add(receipt["representation"]); receipts.append({"representation":receipt["representation"],"receipt":relative})
    if identity[:2]!=(benchmark,dataset): raise ValueError("Inventory logical dataset differs from its receipts")
    value={"schema":_INVENTORY_SCHEMA,"benchmark":_identifier(benchmark,"benchmark"),"dataset":_identifier(dataset,"dataset"),"source":{"format":identity[2],"size_bytes":identity[3],"sha256":identity[4]},"representations":receipts}
    write_json_atomic(inventory_path,value); return value
