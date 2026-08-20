"""Versioned query-manifest contract."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Mapping
from benchmark_core import MANIFEST_SCHEMA_VERSION
from benchmark_core.hashing import sha256_text


def _json_safe(value: Any, label: str) -> None:
    try:
        json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} is not valid JSON: {error}") from error


def validate_manifest(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError("manifest must be a mapping")
    manifest = dict(value)
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported manifest schema_version: {manifest.get('schema_version')}"
        )
    for field in ("workload", "dataset"):
        item = manifest.get(field)
        if not isinstance(item, str) or not item:
            raise ValueError(f"manifest {field} must be a non-empty string")
    queries = manifest.get("queries")
    if not isinstance(queries, list) or not queries:
        raise ValueError("manifest queries must be a non-empty array")
    identifiers = set()
    validated_queries = []
    for index, raw in enumerate(queries):
        if not isinstance(raw, Mapping):
            raise ValueError(f"query {index} must be an object")
        query = dict(raw)
        query_id = query.get("query_id")
        text = query.get("query")
        if not isinstance(query_id, str) or not query_id:
            raise ValueError(f"query {index} query_id must be a non-empty string")
        if query_id in identifiers:
            raise ValueError(f"Duplicate query_id: {query_id}")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"query {index} query must be a non-empty string")
        supplied_hash = query.get("query_sha256")
        if supplied_hash is not None and supplied_hash != sha256_text(text):
            raise ValueError(f"query {index} query_sha256 does not match query")
        identifiers.add(query_id)
        _json_safe(query, f"query {index}")
        validated_queries.append(query)
    manifest["queries"] = validated_queries
    _json_safe(manifest, "manifest")
    return manifest


def load_manifest(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as stream:
        return validate_manifest(json.load(stream))
