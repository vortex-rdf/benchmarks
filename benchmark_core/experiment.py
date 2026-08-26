"""Versioned, benchmark-owned RDF experiment declarations."""
from __future__ import annotations
import json, re
from pathlib import Path
from typing import Any, Mapping
SCHEMA = "rdf-experiment-declaration-v1"
_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*(?:/[a-z0-9][a-z0-9._-]*)*$")
def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError(f"{field} must be a stable lowercase identifier")
    return value
def _relative(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or Path(value).is_absolute() or ".." in Path(value).parts:
        raise ValueError(f"{field} must be a contained relative path")
    return value
def validate_experiment_declaration(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping): raise TypeError("experiment declaration must be an object")
    result = dict(value)
    required={"schema","experiment","benchmark","dataset","workload","inventory","representations","bindings","execution_policy","semantic_baseline"}
    if set(result)!=required: raise ValueError("experiment declaration has unexpected fields")
    if result["schema"]!=SCHEMA: raise ValueError("unsupported experiment declaration schema")
    for field in ("experiment","benchmark","dataset","workload"): _identifier(result[field],field)
    _relative(result["inventory"],"inventory")
    representations=result["representations"]
    if not isinstance(representations,Mapping) or not representations: raise ValueError("representations must be a non-empty object")
    for identifier,receipt in representations.items(): _identifier(identifier,"representation"); _relative(receipt,"representation receipt")
    bindings=result["bindings"]
    if not isinstance(bindings,list) or not bindings: raise ValueError("bindings must be a non-empty array")
    systems=set()
    for index,item in enumerate(bindings):
        if not isinstance(item,Mapping) or set(item)!={"system","representation"}: raise ValueError(f"binding {index} has unexpected fields")
        system=_identifier(item["system"],f"binding {index} system"); representation=_identifier(item["representation"],f"binding {index} representation")
        if system in systems: raise ValueError(f"duplicate system binding: {system}")
        if representation not in representations: raise ValueError(f"binding uses undeclared representation: {representation}")
        systems.add(system)
    policy=result["execution_policy"]
    if not isinstance(policy,Mapping) or set(policy)!={"warmup_runs","measured_runs","timeout_s"}: raise ValueError("execution_policy has unexpected fields")
    if not isinstance(policy["warmup_runs"],int) or policy["warmup_runs"]<0: raise ValueError("warmup_runs must be non-negative")
    if not isinstance(policy["measured_runs"],int) or policy["measured_runs"]<1: raise ValueError("measured_runs must be positive")
    if not isinstance(policy["timeout_s"],(int,float)) or isinstance(policy["timeout_s"],bool) or policy["timeout_s"]<=0: raise ValueError("timeout_s must be positive")
    _relative(result["semantic_baseline"],"semantic_baseline")
    json.dumps(result,sort_keys=True,allow_nan=False)
    return result
def load_experiment_declaration(path: str|Path) -> dict[str,Any]:
    return validate_experiment_declaration(json.loads(Path(path).read_text(encoding="utf-8")))
