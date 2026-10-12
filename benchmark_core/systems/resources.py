"""Single-system resource policy shared by every server (identical to the paper campaigns).

The defaults assume a 64 GiB host: each system gets 58 GiB (no swap). Set
``VORTEX_RDF_BENCH_MEMORY_GIB`` to run on a smaller machine; derived settings (Fuseki heaps,
Virtuoso buffers, QLever memory) scale with it, but then results are not comparable with the paper.
"""
from __future__ import annotations

import os

SYSTEM_MEMORY_GIB = int(os.environ.get("VORTEX_RDF_BENCH_MEMORY_GIB", "58"))
SYSTEM_MEMORY_BYTES = SYSTEM_MEMORY_GIB * 1024 ** 3
DOCKER_MEMORY = f"{SYSTEM_MEMORY_GIB}g"
_SCALE = SYSTEM_MEMORY_GIB / 58


def _g(value_gib: int) -> str:
    return f"{max(1, round(value_gib * _SCALE))}g"


FUSEKI_HEAPS = {"memory": ("4g", _g(54)), "tdb2": ("4g", _g(16))}
VIRTUOSO_EFFECTIVE_FRACTION = 0.85
VIRTUOSO_BUFFER_FRACTION = 0.66
VIRTUOSO_DIRTY_FRACTION = 0.75
VIRTUOSO_LOADER_CORES = 6
QLEVER_QUERY_MEMORY = f"{max(1, round(42 * _SCALE))}G"
QLEVER_CACHE_MEMORY = f"{max(1, round(8 * _SCALE))}G"
QLEVER_SIMULTANEOUS_QUERIES = 1
QLEVER_THREADS = 6


def virtuoso_buffers() -> tuple[int, int]:
    effective = SYSTEM_MEMORY_BYTES * VIRTUOSO_EFFECTIVE_FRACTION
    number = int(effective * VIRTUOSO_BUFFER_FRACTION / 8000)
    return number, int(number * VIRTUOSO_DIRTY_FRACTION)


def provenance() -> dict:
    number, dirty = virtuoso_buffers()
    return {
        "schema": "rdf-system-resource-profile-v1", "memory_max_bytes": SYSTEM_MEMORY_BYTES,
        "memory_swap_max_bytes": 0, "docker_memory": DOCKER_MEMORY,
        "fuseki_heaps": {k: {"xms": v[0], "xmx": v[1]} for k, v in FUSEKI_HEAPS.items()},
        "virtuoso": {"number_of_buffers": number, "max_dirty_buffers": dirty, "loader_cores": VIRTUOSO_LOADER_CORES},
        "qlever": {"memory_max_size": QLEVER_QUERY_MEMORY, "cache_max_size": QLEVER_CACHE_MEMORY,
                   "num_simultaneous_queries": QLEVER_SIMULTANEOUS_QUERIES, "threads": QLEVER_THREADS},
    }

# Fluree bulk import (`fluree create --from`): memory budget and parse threads (its default is 80% of the host RAM).
FLUREE_IMPORT_MEMORY_MB = int(SYSTEM_MEMORY_GIB * 1024 * 0.7)
FLUREE_IMPORT_THREADS = 6
# MillenniumDB server buffers (the Sparqloscope setup guidance for 32/64 GiB hosts: about 70% for the versioned buffer).
MDB_VERSIONED_BUFFER = f"{max(1, round(38 * _SCALE))}GB"
MDB_UNVERSIONED_BUFFER = "2GB"
MDB_STRING_BUFFERS = f"{max(1, round(5 * _SCALE))}GB"
MDB_THREADS = 6
# qEndpoint JVM heap (MEM_SIZE of its image).
QENDPOINT_HEAP = f"{max(4, round(40 * _SCALE))}G"
