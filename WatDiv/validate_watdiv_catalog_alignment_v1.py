"""Independently diagnose the WatDiv catalog hashing and canonicalization contract."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from WatDiv.manifest import DATASET_DECLARATIONS, compute_catalog_digest, parse_stream

SELECTED_IDS = (1, 2, 3, 6200, 12398, 12399, 12400)


def _remove_line_terminator(line: bytes) -> bytes:
    if line.endswith(b"\r\n"):
        return line[:-2]
    if line.endswith((b"\n", b"\r")):
        return line[:-1]
    return line


def _independent_catalog(workload_root: Path) -> tuple[dict[int, bytes], dict[int, str]]:
    query_lines = [_remove_line_terminator(line) for line in (workload_root / "warmup.sparql").read_bytes().splitlines(keepends=True)]
    native_ids = [int(line) for line in (workload_root / "warmup.desc").read_text(encoding="utf-8").splitlines()]
    query_bytes = {native_id: query_lines[position] for position, native_id in enumerate(native_ids)}
    query_hashes = {native_id: hashlib.sha256(value).hexdigest() for native_id, value in query_bytes.items()}
    return query_bytes, query_hashes


def _canonical_rows(mapping: dict[int, str]) -> list[bytes]:
    return [f"{native_id}\t{mapping[native_id]}".encode("ascii") for native_id in sorted(mapping)]


def _implementation_report(
    name: str,
    query_bytes: dict[int, bytes],
    query_hashes: dict[int, str],
) -> dict[str, Any]:
    rows = _canonical_rows(query_hashes)
    payload = b"\n".join(rows)
    selected = {
        str(native_id): {
            "bytes_hex": query_bytes[native_id].hex(),
            "bytes_repr": repr(query_bytes[native_id]),
            "sha256": query_hashes[native_id],
            "leading_whitespace_preserved": query_bytes[native_id][:1] in (b" ", b"\t"),
            "trailing_whitespace_preserved": query_bytes[native_id][-1:] in (b" ", b"\t"),
            "contains_cr_byte": b"\r" in query_bytes[native_id],
            "contains_lf_byte": b"\n" in query_bytes[native_id],
        }
        for native_id in SELECTED_IDS
    }
    return {
        "implementation": name,
        "selected_ids": selected,
        "first_five_canonical_rows": [row.decode("ascii") for row in rows[:5]],
        "last_five_canonical_rows": [row.decode("ascii") for row in rows[-5:]],
        "final_newline_in_digest_input": payload.endswith(b"\n"),
        "numeric_id_ordering": [int(row.split(b"\t", 1)[0]) for row in rows] == sorted(query_hashes),
        "canonical_catalog_byte_length": len(payload),
        "catalog_sha256": hashlib.sha256(payload).hexdigest(),
    }


def diagnose(dataset: str) -> dict[str, Any]:
    declaration = DATASET_DECLARATIONS[dataset]
    root = Path(__file__).resolve().parents[1]
    workload_root = root / declaration["workload_dir"]
    independent_bytes, independent_hashes = _independent_catalog(workload_root)
    parsed = parse_stream(
        workload_root / "warmup.sparql",
        workload_root / "warmup.desc",
        expected_count=declaration["query_count"],
    )
    adapter_bytes = {item["native_query_id"]: item["query"].encode("utf-8") for item in parsed}
    adapter_hashes = {item["native_query_id"]: item["query_sha256"] for item in parsed}
    return {
        "dataset": dataset,
        "expected_catalog_sha256": declaration["catalog_digest"],
        "independent_validator": _implementation_report("independent-byte-validator", independent_bytes, independent_hashes),
        "WatDiv.manifest": _implementation_report("WatDiv.manifest", adapter_bytes, adapter_hashes),
        "query_hashes_match": independent_hashes == adapter_hashes,
        "catalog_digests_match": compute_catalog_digest(adapter_hashes) == hashlib.sha256(
            b"\n".join(_canonical_rows(independent_hashes))
        ).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", choices=tuple(DATASET_DECLARATIONS), action="append")
    args = parser.parse_args()
    datasets = args.dataset or list(DATASET_DECLARATIONS)
    print(json.dumps({dataset: diagnose(dataset) for dataset in datasets}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())