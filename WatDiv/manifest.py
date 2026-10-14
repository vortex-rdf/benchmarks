"""Prepare official WatDiv stress workloads into the shared manifest contract."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable, Sequence

from benchmark_core.atomic_io import write_json_atomic
from benchmark_core.hashing import sha256_bytes, sha256_file, sha256_text
from benchmark_core.manifest import validate_manifest

MANIFEST_SCHEMA_VERSION = 1
EXPECTED_STREAM_NAMES = (
    "warmup",
    "test.1",
    "test.2",
    "test.3",
    "test.4",
    "test.5",
)
EXPECTED_QUERY_COUNT = 12400
TEMPLATE_INSTANCES = 100            # every native stress template has 100 instances (ids are consecutive)
SELECTIONS = ("streams", "smoke", "qualification", "full")
QUALIFICATION_MEASURED = 1240

DATASET_DECLARATIONS = {
    "watdiv-10m": {
        "dataset_id": "watdiv-10m",
        "dataset_path": "WatDiv/data/watdiv.10M.nt",
        "serialization": "nt",
        "workload_dir": "WatDiv/data/watdiv-stress-100",
        "scale_factor": 100,
        "catalog_digest": "67a59f1e00dfc39bb237a959e5fb671dde11b5bc908c7f8a63bc0bb81cbb603c",
        "stream_names": EXPECTED_STREAM_NAMES,
        "query_count": EXPECTED_QUERY_COUNT,
    },
    "watdiv-100m": {
        "dataset_id": "watdiv-100m",
        "dataset_path": "WatDiv/data/watdiv.100M.nt",
        "serialization": "nt",
        "workload_dir": "WatDiv/data/watdiv-stress-1000",
        "scale_factor": 1000,
        "catalog_digest": "53ba6a9dfbafb2bc957a8b88554e6bb4ae2f50852607ef2d675d3ba25a29685e",
        "stream_names": EXPECTED_STREAM_NAMES,
        "query_count": EXPECTED_QUERY_COUNT,
    },
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _dataset_path_for(value: str, dataset_path: Path | None = None) -> Path:
    if dataset_path is not None:
        path = dataset_path.resolve()
    else:
        declaration = DATASET_DECLARATIONS[value]
        path = (_repo_root() / declaration["dataset_path"]).resolve()
    if not path.exists():
        raise FileNotFoundError(f"WatDiv dataset is missing: {path}")
    return path


def _workload_path_for(value: str, workload_root: Path | None = None) -> Path:
    if workload_root is not None:
        path = workload_root.resolve()
    else:
        declaration = DATASET_DECLARATIONS[value]
        path = (_repo_root() / declaration["workload_dir"]).resolve()
    if not path.is_dir():
        raise FileNotFoundError(f"WatDiv workload directory is missing: {path}")
    return path


def _braces_are_balanced(query: str) -> bool:
    balance = 0
    for character in query:
        if character == "{":
            balance += 1
        elif character == "}":
            balance -= 1
            if balance < 0:
                return False
    return balance == 0


def _read_physical_lines(path: Path) -> list[bytes]:
    lines = path.read_bytes().splitlines(keepends=True)
    bodies: list[bytes] = []
    for line in lines:
        if line.endswith(b"\r\n"):
            bodies.append(line[:-2])
        elif line.endswith((b"\n", b"\r")):
            bodies.append(line[:-1])
        else:
            bodies.append(line)
    return bodies


def parse_stream(
    sparql_path: str | Path,
    desc_path: str | Path,
    expected_count: int = EXPECTED_QUERY_COUNT,
) -> list[dict[str, Any]]:
    """Parse one WatDiv stream and validate the native desc permutation."""
    sparql_file = Path(sparql_path)
    desc_file = Path(desc_path)
    if not sparql_file.is_file():
        raise FileNotFoundError(f"WatDiv SPARQL stream is missing: {sparql_file}")
    if not desc_file.is_file():
        raise FileNotFoundError(f"WatDiv desc stream is missing: {desc_file}")

    query_lines = [line.decode("utf-8") for line in _read_physical_lines(sparql_file)]
    if not query_lines:
        raise ValueError(f"WatDiv SPARQL stream has no records: {sparql_file}")
    for line_no, text in enumerate(query_lines, start=1):
        if not text.strip():
            raise ValueError(f"Blank SPARQL record at {sparql_file}:{line_no}")
        stripped = text.lstrip()
        if not stripped.upper().startswith("SELECT"):
            raise ValueError(f"SPARQL record {line_no} in {sparql_file} does not start with SELECT")
        if not _braces_are_balanced(text):
            raise ValueError(f"Unbalanced braces in SPARQL record {line_no} of {sparql_file}")
    desc_lines = desc_file.read_text(encoding="utf-8").splitlines()
    for line_no, text in enumerate(desc_lines, start=1):
        if not text.strip():
            raise ValueError(f"Blank description record at {desc_file}:{line_no}")
    if len(query_lines) != len(desc_lines):
        raise ValueError(
            f"Description count mismatch for {sparql_file}: "
            f"{len(query_lines)} SPARQL lines vs {len(desc_lines)} desc lines"
        )
    if len(query_lines) != expected_count:
        raise ValueError(
            f"Expected {expected_count} records but found {len(query_lines)} in {sparql_file}"
        )

    seen: set[int] = set()
    native_ids: list[int] = []
    for line_no, text in enumerate(desc_lines, start=1):
        if not re.fullmatch(r"\d+", text.strip()):
            raise ValueError(f"Non-integer description record at {desc_file}:{line_no}: {text!r}")
        native_id = int(text.strip())
        if native_id < 1 or native_id > expected_count:
            raise ValueError(
                f"Description record {line_no} in {desc_file} is out of range 1..{expected_count}: {native_id}"
            )
        if native_id in seen:
            raise ValueError(f"Duplicate description ID {native_id} in {desc_file}")
        seen.add(native_id)
        native_ids.append(native_id)

    expected_ids = list(range(1, expected_count + 1))
    if sorted(native_ids) != expected_ids:
        raise ValueError(
            f"Description IDs in {desc_file} are not a complete permutation of 1..{expected_count}"
        )

    entries: list[dict[str, Any]] = []
    for line_no, (query_text, native_id) in enumerate(zip(query_lines, native_ids), start=1):
        digest = sha256_text(query_text)
        entries.append(
            {
                "native_query_id": native_id,
                "query": query_text,
                "query_sha256": digest,
                "line_no": line_no,
            }
        )
    return entries


def compute_catalog_digest(mapping: dict[int, str]) -> str:
    """Compute the canonical WatDiv catalog digest using native ID -> query_sha256."""
    if not mapping:
        raise ValueError("WatDiv catalog mapping is empty")
    payload = b"\n".join(
        f"{native_id}\t{mapping[native_id]}".encode("ascii")
        for native_id in sorted(mapping)
    )
    return sha256_bytes(payload)


def _stream_phase(stream_name: str) -> str:
    return "warmup" if stream_name == "warmup" else "measured"


def template_id(native_query_id: int) -> str:
    return f"watdiv-T{(native_query_id - 1) // TEMPLATE_INSTANCES:03d}"


def select_http_queries(queries: Sequence[dict[str, Any]], selection: str) -> list[dict[str, Any]]:
    """Pre-expanded schedule for the HTTP runner.

    smoke: the first test.1 instance of every template (one pass, no warm-up).
    qualification / full: one warm-up query per template (its first instance in ``warmup``), then the
    first 1,240 / all queries of ``test.1`` in stream order.
    """
    by_stream: dict[str, list[dict[str, Any]]] = {}
    for query in queries:
        by_stream.setdefault(query["stream"], []).append(query)
    if "test.1" not in by_stream:
        raise ValueError("the HTTP selections need the test.1 stream")

    def first_per_template(stream: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[str] = set()
        picked = []
        for query in stream:
            template = template_id(query["native_query_id"])
            if template not in seen:
                seen.add(template)
                picked.append(query)
        return picked

    if selection == "smoke":
        plan = [("measured", q) for q in first_per_template(by_stream["test.1"])]
    else:
        if "warmup" not in by_stream:
            raise ValueError("the qualification and full selections need the warmup stream")
        measured = by_stream["test.1"]
        if selection == "qualification":
            measured = measured[:QUALIFICATION_MEASURED]
        plan = [("warmup", q) for q in first_per_template(by_stream["warmup"])] + [("measured", q) for q in measured]
    return [{**q, "phase": phase, "stream_phase": phase, "stream_position": position,
             "template_id": template_id(q["native_query_id"])}
            for position, (phase, q) in enumerate(plan)]


def prepare(
    *,
    output: str | Path,
    dataset: str,
    dataset_path: str | Path | None = None,
    workload_root: str | Path | None = None,
    workload: str | None = None,
    expected_count: int = EXPECTED_QUERY_COUNT,
    stream_names: Sequence[str] | None = None,
    selection: str = "streams",
) -> dict[str, Any]:
    """Prepare one validated WatDiv workload manifest.

    ``selection="streams"`` keeps every native stream (embedded runner). ``smoke``, ``qualification`` and
    ``full`` write the pre-expanded schedule of the HTTP runner (see :func:`select_http_queries`).
    """
    if selection not in SELECTIONS:
        raise ValueError(f"unknown selection {selection!r}; choose from {SELECTIONS}")
    if dataset not in DATASET_DECLARATIONS:
        raise ValueError(f"Unsupported WatDiv dataset: {dataset!r}")
    declaration = DATASET_DECLARATIONS[dataset]
    if stream_names is None:
        stream_names = declaration["stream_names"]
    dataset_file = _dataset_path_for(dataset, Path(dataset_path) if dataset_path is not None else None)
    workload_dir = _workload_path_for(dataset, Path(workload_root) if workload_root is not None else None)
    workload_name = workload or workload_dir.name
    baseline_mapping: dict[int, str] | None = None
    catalog_entries: list[dict[str, Any]] = []
    queries: list[dict[str, Any]] = []
    provenance_files: list[dict[str, Any]] = []

    for stream_name in stream_names:
        sparql_path = workload_dir / f"{stream_name}.sparql"
        desc_path = workload_dir / f"{stream_name}.desc"
        parsed = parse_stream(sparql_path, desc_path, expected_count=expected_count)
        stream_mapping = {item["native_query_id"]: item["query_sha256"] for item in parsed}
        if baseline_mapping is None:
            baseline_mapping = stream_mapping
            catalog_entries = [
                {
                    "native_query_id": item["native_query_id"],
                    "query": item["query"],
                    "query_sha256": item["query_sha256"],
                }
                for item in sorted(parsed, key=lambda x: x["native_query_id"])
            ]
        elif stream_mapping != baseline_mapping:
            raise ValueError(
                f"WatDiv stream {stream_name} does not match the canonical catalog mapping"
            )

        phase = _stream_phase(stream_name)
        for position, item in enumerate(parsed):
            queries.append(
                {
                    "query_id": f"{dataset}-{stream_name}-{position:05d}",
                    "query": item["query"],
                    "query_sha256": item["query_sha256"],
                    "benchmark": "WatDiv",
                    "dataset": dataset,
                    "workload": workload_name,
                    "scale_factor": declaration["scale_factor"],
                    "phase": phase,
                    "stream": stream_name,
                    "position": position,
                    "native_query_id": item["native_query_id"],
                    "source_sparql": str(sparql_path),
                    "source_desc": str(desc_path),
                }
            )

        provenance_files.extend(
            [
                {
                    "path": str(sparql_path),
                    "size_bytes": sparql_path.stat().st_size,
                    "sha256": sha256_file(sparql_path),
                },
                {
                    "path": str(desc_path),
                    "size_bytes": desc_path.stat().st_size,
                    "sha256": sha256_file(desc_path),
                },
            ]
        )

    if baseline_mapping is None:
        raise ValueError(f"WatDiv workload {workload_dir} contains no valid stream data")
    if selection != "streams":
        queries = select_http_queries(queries, selection)
        stream_names = sorted({q["stream"] for q in queries}, key=list(stream_names).index)

    official_workload_root = (_repo_root() / declaration["workload_dir"]).resolve()
    official_dataset_path = (_repo_root() / declaration["dataset_path"]).resolve()
    actual_digest = compute_catalog_digest(baseline_mapping)
    expected_digest = declaration["catalog_digest"]
    if expected_count == EXPECTED_QUERY_COUNT and workload_dir == official_workload_root and dataset_file == official_dataset_path:
        if actual_digest != expected_digest:
            raise ValueError(
                f"WatDiv catalog digest mismatch for {dataset}: expected {expected_digest}, "
                f"got {actual_digest}"
            )

    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "benchmark": "WatDiv",
        "workload": workload_name,
        "dataset": dataset,
        "dataset_path": str(dataset_file),
        "workload_dir": str(workload_dir),
        "source_format": "watdiv-native-stress" if selection == "streams" else f"watdiv-native-stress-{selection}",
        "query_count": len(queries),
        "expected_query_count": expected_count,
        "stream_order": list(stream_names),
        "stream_count": len(stream_names),
        "scale_factor": declaration["scale_factor"],
        "catalog": {
            "query_count": len(catalog_entries),
            "digest": actual_digest,
            "expected_digest": expected_digest,
            "entries": catalog_entries,
        },
        "provenance": {
            "schema": "watdiv-manifest-v1",
            "dataset_path": str(dataset_file),
            "workload_dir": str(workload_dir),
            "files": provenance_files,
            "query_hashing_rule": "sha256(utf8(query_without_line_terminator))",
            "stream_order": list(stream_names),
        },
        "queries": queries,
    }
    validated = validate_manifest(manifest)
    write_json_atomic(output, validated)
    return validated
