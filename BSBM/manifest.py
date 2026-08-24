"""Prepare generic RDF manifests from official or file-based BSBM queries."""
from __future__ import annotations
import csv
import json
from pathlib import Path
from typing import Any
from benchmark_core.atomic_io import write_json_atomic
from benchmark_core.hashing import sha256_file, sha256_text
from benchmark_core.manifest import validate_manifest

_SUFFIXES = frozenset({'.rq', '.sparql'})
_SELECTIONS = frozenset({'full', 'smoke'})


def _query_files(query_root: Path) -> list[Path]:
    root = query_root.resolve()
    if not root.is_dir():
        raise FileNotFoundError(f'BSBM query root is not a directory: {root}')
    files = sorted(path for path in root.rglob('*')
                   if path.is_file() and path.suffix.lower() in _SUFFIXES)
    if not files:
        raise ValueError('BSBM query root contains no .rq or .sparql files')
    return files


def _read_receipt(path: Path, stream: Path, dataset_path: Path | None) -> dict[str, Any]:
    receipt_path = path.resolve()
    value = json.loads(receipt_path.read_text(encoding='utf-8'))
    if not isinstance(value, dict) or value.get('schema') != 'bsbm-generation-receipt-v1':
        raise ValueError('Unsupported BSBM generation receipt')
    if value.get('benchmark') != 'BSBM' or value.get('use_case') != 'Explore':
        raise ValueError('Generation receipt must describe BSBM Explore')
    query_info = value.get('query_stream')
    dataset_info = value.get('dataset')
    if not isinstance(query_info, dict) or not isinstance(dataset_info, dict):
        raise ValueError('Generation receipt misses dataset or query_stream metadata')
    if query_info.get('sha256') != sha256_file(stream):
        raise ValueError('BSBM query stream SHA-256 differs from generation receipt')
    if query_info.get('size_bytes') != stream.stat().st_size:
        raise ValueError('BSBM query stream size differs from generation receipt')
    if dataset_path is not None:
        resolved_dataset = dataset_path.resolve()
        if dataset_info.get('sha256') != sha256_file(resolved_dataset):
            raise ValueError('BSBM dataset SHA-256 differs from generation receipt')
        if dataset_info.get('size_bytes') != resolved_dataset.stat().st_size:
            raise ValueError('BSBM dataset size differs from generation receipt')
    return value


def _stream_queries(stream: Path, receipt: dict[str, Any], selection: str) -> list[dict[str, Any]]:
    if selection not in _SELECTIONS:
        raise ValueError('selection must be full or smoke')
    query_info = receipt['query_stream']
    warmup = query_info.get('warmup_records')
    measured = query_info.get('measured_records')
    total = query_info.get('record_count')
    if not all(isinstance(value, int) and not isinstance(value, bool) and value >= 0
               for value in (warmup, measured, total)) or warmup + measured != total:
        raise ValueError('Generation receipt has invalid stream counts')
    rows = []
    with stream.open('r', encoding='utf-8', newline='') as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ['id', 'kind', 'content']:
            raise ValueError(f'Unexpected BSBM CSV columns: {reader.fieldnames!r}')
        for position, row in enumerate(reader):
            if row.get('kind') != 'query':
                raise ValueError(f'BSBM Explore row {position} is not a query')
            template_id = row.get('id', '').strip()
            query = row.get('content', '').strip()
            if not template_id or not query:
                raise ValueError(f'BSBM Explore row {position} has empty fields')
            phase = 'warmup' if position < warmup else 'measured'
            rows.append({
                'query_id': f'explore/stream-{position:06d}/query-{int(template_id):02d}',
                'query': query,
                'query_sha256': sha256_text(query),
                'bsbm_template_id': template_id,
                'stream_position': position,
                'stream_phase': phase,
            })
    if len(rows) != total:
        raise ValueError(f'BSBM stream count mismatch: expected {total}, found {len(rows)}')
    if selection == 'full':
        return rows
    selected = []
    seen = set()
    for row in rows[warmup:]:
        template = row['bsbm_template_id']
        if template not in seen:
            seen.add(template); selected.append(row)
    if not selected:
        raise ValueError('BSBM smoke selection contains no measured query templates')
    return selected


def prepare(*, output: Path, workload: str, dataset: str,
            query_root: Path | None = None, query_stream: Path | None = None,
            generation_receipt: Path | None = None,
            dataset_path: Path | None = None, selection: str = 'smoke') -> dict[str, Any]:
    if (query_root is None) == (query_stream is None):
        raise ValueError('Exactly one of query_root and query_stream is required')
    if query_stream is not None:
        if generation_receipt is None:
            raise ValueError('generation_receipt is required with query_stream')
        stream = query_stream.resolve()
        if not stream.is_file():
            raise FileNotFoundError(f'BSBM query stream is not a file: {stream}')
        receipt = _read_receipt(generation_receipt, stream, dataset_path)
        queries = _stream_queries(stream, receipt, selection)
        source = {
            'kind': 'official_query_stream', 'format': 'bsbm-log-csv',
            'path': str(stream), 'sha256': sha256_file(stream),
            'selection': selection,
            'record_count': receipt['query_stream']['record_count'],
            'warmup_records': receipt['query_stream']['warmup_records'],
            'measured_records': receipt['query_stream']['measured_records'],
            'generation_receipt': {
                'path': str(generation_receipt.resolve()),
                'sha256': sha256_file(generation_receipt),
                'specification': receipt.get('specification'),
                'product_count': receipt.get('product_count'),
                'forward_chaining': receipt.get('forward_chaining'),
                'generator': receipt.get('generator'),
                'dataset': receipt.get('dataset'),
            },
        }
        source_format = 'bsbm-official-query-stream'
    else:
        root = query_root.resolve(); queries = []
        for path in _query_files(root):
            relative = path.relative_to(root).as_posix()
            query = path.read_text(encoding='utf-8').strip()
            if not query:
                raise ValueError(f'BSBM query file is empty: {relative}')
            queries.append({'query_id': relative, 'query': query,
                            'query_sha256': sha256_text(query),
                            'source_relative_path': relative})
        source = {'kind': 'query_tree', 'path': str(root), 'files': [
            {'path': q['source_relative_path'],
             'sha256': sha256_file(root / q['source_relative_path'])}
            for q in queries]}
        source_format = 'bsbm-instantiated-queries'
    manifest = {'schema_version': 1, 'workload': workload, 'dataset': dataset,
                'source_format': source_format, 'query_count': len(queries),
                'source': source, 'queries': queries}
    validated = validate_manifest(manifest)
    write_json_atomic(output, validated)
    return validated
