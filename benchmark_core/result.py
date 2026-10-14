"""Versioned per-query result contract."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Mapping
from benchmark_core import RESULT_SCHEMA_VERSION

RESULT_STATUSES = frozenset({
    "ok", "timeout", "unsupported", "engine_error", "connection_error",
    "parse_error", "result_error", "validation_mismatch", "skipped",
})
REQUIRED_FIELDS = frozenset({
    "schema_version", "experiment_id", "system", "dataset", "workload",
    "query_id", "phase", "run", "order", "status", "elapsed_ns",
})


def _integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def validate_result(record: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(record, Mapping):
        raise TypeError("result record must be a mapping")
    result = dict(record)
    missing = sorted(REQUIRED_FIELDS.difference(result))
    if missing:
        raise ValueError(f"Missing required fields: {', '.join(missing)}")
    if result["schema_version"] != RESULT_SCHEMA_VERSION:
        raise ValueError(f"Unsupported schema_version: {result['schema_version']}")
    for field in ("experiment_id", "system", "dataset", "workload",
                  "query_id", "phase", "status"):
        if not isinstance(result[field], str) or not result[field]:
            raise ValueError(f"{field} must be a non-empty string")
    for field in ("run", "order"):
        if not _integer(result[field]) or result[field] < 0:
            raise ValueError(f"{field} must be a non-negative integer")
    if result["status"] not in RESULT_STATUSES:
        raise ValueError(f"Unsupported status: {result['status']}")
    elapsed = result["elapsed_ns"]
    if elapsed is None:
        if result["status"] not in {"skipped", "unsupported"}:
            raise ValueError("elapsed_ns can be null only for skipped or unsupported records")
    elif not _integer(elapsed) or elapsed < 0:
        raise ValueError("elapsed_ns must be null or a non-negative integer")
    count = result.get("result_count")
    if count is not None and (not _integer(count) or count < 0):
        raise ValueError("result_count must be null or a non-negative integer")
    try:
        json.dumps(result, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ValueError(f"Result is not valid JSON: {error}") from error
    return result


def load_results(path: str | Path) -> list[dict[str, Any]]:
    records = []
    with Path(path).open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                records.append(validate_result(json.loads(line)))
            except (json.JSONDecodeError, TypeError, ValueError) as error:
                raise ValueError(f"Invalid result at line {line_number}: {error}") from error
    if not records:
        raise ValueError("result file must contain at least one record")
    return records
