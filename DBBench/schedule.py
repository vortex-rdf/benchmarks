"""Expand a DBBench query manifest into the phased TP3 schedule used for the paper.

Schedule (stream positions are consecutive from 0):

1. warm-up: every valid triple-pattern (TP) query once, set repetition 0;
2. measured: the same TP queries in the same order, ``tp_passes`` times (set repetitions 1..N);
3. measured: every valid join query once (set repetition 1).

TP queries are ordered by (file name, index in file); join queries keep the base manifest's order.
Queries listed in the invalid-query inventory (they do not parse in rdflib) are excluded.
Result comparison is count-only: fingerprinting DBpedia result sets is prohibitively slow.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from benchmark_core.atomic_io import write_json_atomic

SCHEDULE_SCHEMA = "rdf-preexpanded-stream-schedule-v1"


def _family(record: dict[str, Any]) -> str:
    stem = record["source_file_name"].removesuffix(".txt")
    if record["source_top_group"] == "TP":
        return f"TP/{stem}"
    return f"JOINS/{record['source_size_group']}/{stem}"


def _scheduled(record: dict[str, Any], phase: str, tag: str, position: int, repetition: int,
               source_index: int, comparison_mode: str) -> dict[str, Any]:
    result = dict(record)
    family = _family(record)
    result.update({
        "bsbm_template_id": family,
        "reporting_family": family,
        "comparison_mode": comparison_mode,
        "query_id": f"{tag}/{position:05d}/r{repetition:02d}/{record['query_id']}",
        "set_repetition": repetition,
        "source_query_id": record["query_id"],
        "source_query_index": source_index,
        "stream_phase": phase,
        "stream_position": position,
    })
    return result


def expand_tp3(base: dict[str, Any], invalid_query_ids: set[str], *, tp_passes: int = 3,
               comparison_mode: str = "count-only") -> dict[str, Any]:
    """Return the preexpanded manifest for ``base`` (a ``dbbench prepare`` manifest)."""
    if tp_passes < 1:
        raise ValueError("tp_passes must be positive")
    valid = [q for q in base["queries"] if q["query_id"] not in invalid_query_ids]
    unknown = invalid_query_ids - {q["query_id"] for q in base["queries"]}
    if unknown:
        raise ValueError(f"invalid-query ids not in the base manifest: {sorted(unknown)[:3]}")
    tp = sorted((q for q in valid if q["source_top_group"] == "TP"),
                key=lambda q: (q["source_file_name"], q["source_query_index"]))
    joins = [q for q in valid if q["source_top_group"] == "JOINS"]
    records: list[dict[str, Any]] = []
    for index, query in enumerate(tp):
        records.append(_scheduled(query, "warmup", "warmup", len(records), 0, index, comparison_mode))
    for repetition in range(1, tp_passes + 1):
        for index, query in enumerate(tp):
            records.append(_scheduled(query, "measured", "measured", len(records), repetition, index, comparison_mode))
    for index, query in enumerate(joins):
        records.append(_scheduled(query, "measured", "measured-joins", len(records), 1, index, comparison_mode))
    manifest = {key: value for key, value in base.items() if key != "queries"}
    manifest.update({
        "queries": records,
        "query_count": len(records),
        "source_format": "dbbench-preexpanded",
        "source_query_count": len(valid),
        "warmup_query_count": len(tp),
        "measured_query_count": len(records) - len(tp),
        "invalid_source_query_count": len(invalid_query_ids),
        "schedule": {"schema": SCHEDULE_SCHEMA, "mode": "preexpanded", "tp_passes": tp_passes,
                     "warmup": "all TP queries once", "joins": "once, after the TP passes"},
    })
    return manifest


def load_invalid_ids(path: Path) -> set[str]:
    inventory = json.loads(path.read_text(encoding="utf-8"))
    if inventory.get("schema") != "dbbench-invalid-query-inventory-v1":
        raise ValueError("unsupported invalid-query inventory")
    return {entry["source_query_id"] for entry in inventory["queries"]}


def records_sha256(manifest: dict[str, Any]) -> str:
    """Identity of the schedule: SHA-256 of the canonical JSON of its query records."""
    canonical = json.dumps(manifest["queries"], sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def write_schedule(*, base: Path, invalid: Path, output: Path, tp_passes: int = 3) -> dict[str, Any]:
    manifest = expand_tp3(json.loads(base.read_text(encoding="utf-8")), load_invalid_ids(invalid), tp_passes=tp_passes)
    write_json_atomic(output, manifest)
    return manifest
