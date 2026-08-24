"""Prepare a generic RDF workload manifest from instantiated BSBM queries."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any
from benchmark_core.atomic_io import write_json_atomic
from benchmark_core.hashing import sha256_file, sha256_text
from benchmark_core.manifest import validate_manifest

_SUFFIXES = frozenset({'.rq', '.sparql'})


def _query_files(query_root: Path) -> list[Path]:
    root = query_root.resolve()
    if not root.is_dir():
        raise FileNotFoundError(f'BSBM query root is not a directory: {root}')
    files = sorted(path for path in root.rglob('*')
                   if path.is_file() and path.suffix.lower() in _SUFFIXES)
    if not files:
        raise ValueError('BSBM query root contains no .rq or .sparql files')
    return files


def prepare(*, query_root: Path, output: Path, workload: str,
            dataset: str) -> dict[str, Any]:
    root = query_root.resolve(); queries = []
    for path in _query_files(root):
        relative = path.relative_to(root).as_posix()
        query = path.read_text(encoding='utf-8').strip()
        if not query:
            raise ValueError(f'BSBM query file is empty: {relative}')
        queries.append({
            'query_id': relative,
            'query': query,
            'query_sha256': sha256_text(query),
            'source_relative_path': relative,
        })
    manifest = {
        'schema_version': 1,
        'workload': workload,
        'dataset': dataset,
        'source_format': 'bsbm-instantiated-queries',
        'query_count': len(queries),
        'source': {
            'kind': 'query_tree',
            'path': str(root),
            'files': [
                {'path': q['source_relative_path'],
                 'sha256': sha256_file(root / q['source_relative_path'])}
                for q in queries
            ],
        },
        'queries': queries,
    }
    write_json_atomic(output, validate_manifest(manifest))
    return manifest
